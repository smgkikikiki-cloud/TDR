"""Thin bridge: validate and insert ONE row into canonical_input_batches.

This exists so a session with GitHub Actions access but no Supabase
credentials (e.g. Claude Code running locally) can still hand a prepared
canonical batch to the real production queue. It reuses exactly the schema
and validation the admin web app already enforces for the same table --
lib/canonical-input-queue.ts's enqueueCanonicalInputBatch() and
app/admin/input-actions.ts's enqueuePayload() -- the same full structural/
semantic validator the real worker itself uses
(vehreg.input_pipeline.CanonicalInputBatch.from_dict), and the same
Supabase credential loading tools.canonical_input_worker already uses.

It does nothing else: no CanonicalInputPipeline.apply(), no vehreg/data
write, no git commit, no publish. Everything after "row exists in
canonical_input_batches with status QUEUED" is the existing
canonical-input worker's job (tools/canonical_input_worker.py, run from
.github/workflows/canonical-input.yml), unchanged.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from tools.canonical_input_worker import _env
from vehreg.canonical_write import CanonicalWriteError
from vehreg.input_pipeline import CanonicalInputBatch, CanonicalInputError

# Same pattern the DB's own batch_key check constraint and the admin
# server actions already enforce -- see supabase/migration_v22_unified_vehicle_input.sql
# and lib/canonical-input-queue.ts.
_BATCH_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SOURCE_KINDS = {"ADMIN", "ECO", "OEM", "MEDIA", "PRICE_HARVEST", "MIGRATION", "API"}
_REGISTRATION_KINDS = {"DLT", "REGISTRATION"}
_MAX_COMMANDS = 500

# Statuses under which this batch_key already exists and is genuinely
# still QUEUED for the worker -- everything else means work has already
# started or finished on it, and this bridge must say so rather than
# claim a fresh "QUEUED".
_WAKE_WORKER_STATUSES = {"QUEUED"}


class EnqueueError(ValueError):
    pass


def _js_number(value: int | float) -> str:
    """The exact digits JSON.stringify(value) would produce in JavaScript.

    Python's json.dumps distinguishes int/float (1 vs 1.0) and formats
    negative zero and small-magnitude scientific notation differently from
    JS's Number::toString (ECMA-262 7.1.12.1), which JSON.stringify uses
    for every JS number regardless of how it was constructed. Two engines
    computing payload_sha256 over the "same" value must produce the same
    digits, so this reimplements that algorithm rather than deferring to
    json.dumps for numbers.
    """
    if isinstance(value, int):
        return str(value)
    if value != value:  # NaN
        return "null"  # JSON.stringify(NaN) === "null"
    if value in (float("inf"), float("-inf")):
        return "null"  # JSON.stringify(Infinity) === "null"
    if value == 0.0:
        return "0"  # JSON.stringify(-0) === "0"

    negative = value < 0
    magnitude = -value if negative else value
    # repr() gives the shortest decimal string that round-trips to this
    # float, same guarantee ECMA-262's number-to-string algorithm makes;
    # Decimal() then exposes its exact digits/exponent without re-rounding.
    _sign, digit_tuple, exponent = Decimal(repr(magnitude)).as_tuple()
    digits = list(digit_tuple)
    while len(digits) > 1 and digits[-1] == 0:
        digits.pop()
        exponent += 1
    s = "".join(str(d) for d in digits)
    k = len(s)
    n = k + exponent  # value == int(s) * 10**(n - k), per the ECMA-262 definition

    if k <= n <= 21:
        body = s + "0" * (n - k)
    elif 0 < n <= 21:
        body = s[:n] + "." + s[n:]
    elif -6 < n <= 0:
        body = "0." + "0" * (-n) + s
    elif k == 1:
        body = f"{s}e{'+' if n - 1 >= 0 else ''}{n - 1}"
    else:
        body = f"{s[0]}.{s[1:]}e{'+' if n - 1 >= 0 else ''}{n - 1}"
    return f"-{body}" if negative else body


def _canonical(value: Any) -> str:
    """Deterministic JSON key-sorted stringify.

    Must produce the same ordering AND the same number formatting as
    lib/canonical-input-queue.ts's own canonical() (which delegates numbers
    to JS's own JSON.stringify) so a batch built by this tool hashes the
    way the admin UI would hash the identical payload -- the duplicate-
    detection compare below only means anything if both sides compute the
    hash the same way.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return _js_number(value)
    if isinstance(value, list):
        return "[" + ",".join(_canonical(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ",".join(
            f"{json.dumps(key, ensure_ascii=False)}:{_canonical(value[key])}"
            for key in sorted(value)
        ) + "}"
    return json.dumps(value, ensure_ascii=False)


def normalize_and_validate(payload: Any, *, authenticated_actor: str) -> tuple[dict, str, str, str]:
    """Returns (normalized_payload, batch_key, source_kind, actor).

    Raises EnqueueError for anything the admin server actions -- or the
    real worker's own CanonicalInputBatch.from_dict -- would also have
    rejected before ever reaching Supabase.

    ``authenticated_actor`` is the GitHub user who dispatched this
    workflow (github.actor). It always wins: the payload's own "actor"
    field (and any per-command "actor") is discarded rather than trusted,
    the same way the admin server action derives actor from the
    authenticated editor's session instead of the submitted form/JSON.
    """
    authenticated_actor = str(authenticated_actor or "").strip()
    if not authenticated_actor:
        raise EnqueueError("an authenticated actor is required (e.g. github.actor)")

    if not isinstance(payload, dict):
        raise EnqueueError("payload must be a JSON object")
    if payload.get("schema_version") != 1:
        raise EnqueueError("only schema_version 1 is supported")
    batch_key = str(payload.get("batch_id") or "").strip()
    if not _BATCH_KEY_RE.fullmatch(batch_key):
        raise EnqueueError("batch_id is invalid")
    commands = payload.get("commands")
    if not isinstance(commands, list) or not (1 <= len(commands) <= _MAX_COMMANDS):
        raise EnqueueError(f"commands must be an array of 1-{_MAX_COMMANDS} items")
    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    kind = str(source.get("kind") or "ADMIN").strip().upper()
    if kind in _REGISTRATION_KINDS:
        raise EnqueueError("registration facts use a separate ingest path, not this bridge")
    if kind not in _SOURCE_KINDS:
        raise EnqueueError(f"unsupported source.kind {kind!r}")

    submitted_at = str(payload.get("submitted_at") or "").strip() \
        or datetime.now(timezone.utc).isoformat()

    normalized = dict(payload)
    normalized["source"] = {**source, "kind": kind}
    normalized["actor"] = authenticated_actor
    normalized["submitted_at"] = submitted_at
    normalized["commands"] = [
        {**command, "actor": authenticated_actor, "submitted_at": submitted_at}
        if isinstance(command, dict) else command
        for command in commands
    ]

    # Full structural/semantic validation -- the exact parser the real
    # worker runs before ever touching Catalog: catches a malformed
    # command, an unknown/invalid operation, a bad submitted_at/timezone,
    # a malformed source object, a duplicate command_id, an invalid
    # special-operation payload, and so on. This is validation only --
    # its return value is discarded; nothing is applied.
    try:
        CanonicalInputBatch.from_dict(normalized)
    except (CanonicalInputError, CanonicalWriteError) as exc:
        raise EnqueueError(f"batch fails canonical input validation: {exc}") from exc

    return normalized, batch_key, kind, authenticated_actor


def build_row(normalized: dict, *, batch_key: str, source_kind: str, actor: str) -> dict:
    """Exactly the columns tools/canonical_input_worker.py's pull() expects."""
    source = normalized.get("source") if isinstance(normalized.get("source"), dict) else {}
    payload_sha256 = hashlib.sha256(_canonical(normalized).encode("utf-8")).hexdigest()
    return {
        "domain": "VEHICLE_MARKET",
        "batch_key": batch_key,
        "source_kind": source_kind,
        "source_ref": source.get("ref") if isinstance(source.get("ref"), str) else None,
        "payload": normalized,
        "payload_sha256": payload_sha256,
        "item_count": len(normalized["commands"]),
        "actor": actor,
        "status": "QUEUED",
    }


def _insert_row(row: dict) -> tuple[int, Any]:
    url, key = _env()
    body = json.dumps(row, ensure_ascii=False).encode("utf-8")
    headers = {
        "apikey": key, "content-type": "application/json",
        "accept": "application/json", "prefer": "return=representation",
    }
    if key.startswith("eyJ"):
        headers["authorization"] = f"Bearer {key}"
    request = Request(f"{url}/rest/v1/canonical_input_batches", data=body,
                      headers=headers, method="POST")
    try:
        with urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read().decode() or "null")
    except HTTPError as exc:
        content = exc.read().decode(errors="replace")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            parsed = {"message": content[:1000]}
        return exc.code, parsed


def _existing_batch_row(batch_key: str) -> dict[str, Any] | None:
    """id/payload_sha256/status of the row already sitting at this batch_key."""
    url, key = _env()
    headers = {"apikey": key, "accept": "application/json"}
    if key.startswith("eyJ"):
        headers["authorization"] = f"Bearer {key}"
    request = Request(
        f"{url}/rest/v1/canonical_input_batches"
        f"?select=id,payload_sha256,status&batch_key=eq.{quote(batch_key)}",
        headers=headers, method="GET",
    )
    with urlopen(request, timeout=60) as response:
        rows = json.loads(response.read().decode() or "[]")
    return rows[0] if rows else None


def enqueue(payload_file: Path, *, authenticated_actor: str, result_file: Path) -> int:
    try:
        payload = json.loads(payload_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EnqueueError(f"cannot read payload JSON: {exc}") from exc

    normalized, batch_key, kind, actor = normalize_and_validate(
        payload, authenticated_actor=authenticated_actor)
    row = build_row(normalized, batch_key=batch_key, source_kind=kind, actor=actor)

    status_code, body = _insert_row(row)
    if status_code in (200, 201):
        result = {
            "batch_key": batch_key, "status": "QUEUED", "duplicate": False,
            "item_count": row["item_count"], "actor": actor,
            "payload_sha256": row["payload_sha256"],
            "should_wake_worker": True,
        }
    elif status_code == 409 or (isinstance(body, dict) and body.get("code") == "23505"):
        existing = _existing_batch_row(batch_key)
        existing_hash = existing["payload_sha256"] if existing else None
        if existing_hash != row["payload_sha256"]:
            raise EnqueueError(
                f"batch_id {batch_key!r} was already used with different content "
                "(existing payload_sha256 does not match) -- refusing to enqueue "
                "a second semantic batch under the same batch_id"
            )
        # This is the SAME batch, already sitting at whatever real status
        # it has reached. Never claim it is freshly "QUEUED" -- report the
        # actual status, and only ask to wake the worker when that status
        # is one the worker's own pull() would still act on. A batch that
        # already FAILED/REJECTED/NEEDS_REVIEW is not silently retried
        # here; a batch already PROCESSING/STAGED/PUBLISHED is not
        # re-presented as new work.
        real_status = str(existing["status"]) if existing else "UNKNOWN"
        result = {
            "batch_key": batch_key, "status": real_status, "duplicate": True,
            "existing_batch_id": existing["id"] if existing else None,
            "item_count": row["item_count"], "actor": actor,
            "payload_sha256": row["payload_sha256"],
            "should_wake_worker": real_status in _WAKE_WORKER_STATUSES,
        }
    else:
        raise EnqueueError(f"Supabase insert failed ({status_code}): {json.dumps(body)[:1000]}")

    result_file.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload-file", type=Path, required=True)
    parser.add_argument("--actor", required=True,
                        help="The authenticated GitHub user who dispatched this "
                             "workflow (github.actor). Always overrides any actor "
                             "the payload itself carries.")
    parser.add_argument("--result-file", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        return enqueue(args.payload_file, authenticated_actor=args.actor,
                       result_file=args.result_file)
    except EnqueueError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
