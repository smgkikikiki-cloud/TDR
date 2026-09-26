"""Publish a prepared canonical vehicle release through the Supabase RPCs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _strip_wrapper_quotes(value: str) -> str:
    cleaned = value.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
        return cleaned[1:-1].strip()
    return cleaned


def _clean_env_value(value: str | None, *names: str) -> str:
    """Accept a bare secret value or copied/quoted NAME=value assignment."""
    cleaned = _strip_wrapper_quotes(value or "")
    if "=" in cleaned:
        prefix, remainder = cleaned.split("=", 1)
        if prefix.strip() in names:
            cleaned = remainder.strip()
    return _strip_wrapper_quotes(cleaned)


#: Comfortably above publish_vehicle_release(jsonb)'s own 45s function-level
#: statement_timeout (migration_v47) and the 30s each staged-protocol RPC
#: carries (migration_v48) -- every RPC this module calls always errors out
#: on its own budget first, so this only needs to outlast the largest of
#: them, not guess at how long the request itself might otherwise hang for.
REQUEST_TIMEOUT_SECONDS = 55

#: Rows per stage_vehicle_release_chunk() call. At this size the largest
#: single section in the September 2026 ECO Sticker release (~20,800 spec
#: facts) is ~42 chunks, each well inside that RPC's own 30s budget --
#: publish_vehicle_release's single-transaction rewrite of the same release
#: measured ~34.5s in total and still didn't finish within its 45s one.
CHUNK_SIZE = 500

#: Foreign-key order: models reference brands, generations reference
#: models, market_trims reference both models and generations, price_ledger
#: and spec_facts both reference market_trims. stage_vehicle_release_chunk
#: itself refuses a section staged before its prerequisites are complete
#: (migration_v48) -- this order is what keeps every call a first try
#: instead of a caught-and-retried rejection.
RELEASE_SECTIONS = ("brands", "models", "generations",
                    "market_trims", "price_ledger", "spec_facts")

#: The manifest's identity/activation fields, kept in exact lockstep with
#: migration_v48's _release_semantic_manifest() SQL-side allowlist. An
#: explicit list, deliberately not "the release minus the bulk arrays and
#: trim_reconciliation" -- that phrasing means every *new* release field
#: (another large diagnostic report, some future piece of metadata) gets
#: sent to begin_vehicle_release and stored in its payload column by
#: default, unless someone remembers to add it to an exclusion list.  An
#: allowlist fails safe instead: a new field is simply not sent until it
#: is deliberately added here (and to the SQL side, so the two stay in
#: lockstep). Audited against every production reader of
#: canonical_vehicle_releases.payload (lib/canonical-editor.ts,
#: app/admin/retail-lifecycle-actions.ts, app/admin/price-coverage-actions.ts,
#: app/admin/input-actions.ts, lib/historical-model-state.ts): all of them
#: read only payload.year (falling back to payload.as_of) and
#: payload.historical_model_state -- both included below.
MANIFEST_FIELDS = (
    "schema_version", "release_id", "canonical_revision", "source_hash",
    "year", "as_of", "counts", "historical_model_state", "revision_ordinal",
)


def _manifest(release: dict) -> dict:
    """The release's identity/activation fields for begin_vehicle_release --
    never the six bulk section arrays that made a single-transaction
    publish too slow to finish in the first place, and never anything
    outside MANIFEST_FIELDS."""
    return {key: release[key] for key in MANIFEST_FIELDS if key in release}


def _chunk_hash(rows: list) -> str:
    body = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()


def _chunks(rows: list, size: int):
    for index in range(0, len(rows), size):
        yield index // size, rows[index:index + size]


def _headers(service_key: str) -> dict:
    headers = {
        "apikey": service_key,
        "content-type": "application/json",
        "accept": "application/json",
    }
    # Legacy service_role keys are JWTs and may be used as Bearer credentials.
    # Modern sb_secret_* keys are API keys, not JWTs, so they belong only in apikey.
    if service_key.startswith("eyJ"):
        headers["authorization"] = f"Bearer {service_key}"
    return headers


def _rpc(name: str, params: dict, *, url: str, service_key: str,
        timeout: int = REQUEST_TIMEOUT_SECONDS, attempts: int = 3,
        backoff_seconds: float = 2.0) -> dict:
    endpoint = url.rstrip("/") + f"/rest/v1/rpc/{name}"
    request = Request(
        endpoint,
        data=json.dumps(params, ensure_ascii=False, separators=(",", ":")).encode(),
        headers=_headers(service_key),
        method="POST",
    )
    for attempt in range(1, attempts + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                body = response.read().decode()
            return json.loads(body) if body else {}
        except HTTPError as exc:
            # The RPC ran and Postgres/PostgREST returned a real error --
            # a conflict, a validation failure, a stale revision. Retrying
            # the same request would just fail the same way again.
            body = exc.read().decode(errors="replace")
            raise RuntimeError(f"{name} failed ({exc.code}): {body}") from exc
        except (URLError, socket.timeout, ConnectionError) as exc:
            if attempt == attempts:
                raise RuntimeError(
                    f"{name} failed after {attempts} attempts: {exc}") from exc
            time.sleep(backoff_seconds * attempt)
    raise AssertionError("unreachable")  # pragma: no cover


def _prune_releases(*, url: str, service_key: str) -> dict:
    """Apply the bounded release-retention policy from migration_v51.

    Keep the current ACTIVE release plus one SUPERSEDED rollback release;
    stale STAGING attempts are removed by the database only after its grace
    period. The RPC shares activate_vehicle_release's advisory lock, so it
    cannot race an activation.
    """
    return _rpc("prune_vehicle_releases", {}, url=url, service_key=service_key)


def publish(release: dict, *, url: str, service_key: str) -> dict:
    """The legacy, unstaged path: one call to publish_vehicle_release(jsonb),
    followed by the same bounded release retention as the staged path."""
    result = _rpc("publish_vehicle_release", {"release": release}, url=url, service_key=service_key)
    result["retention"] = _prune_releases(url=url, service_key=service_key)
    return result


def publish_staged(release: dict, *, url: str, service_key: str,
                   chunk_size: int = CHUNK_SIZE) -> dict:
    """begin_vehicle_release -> stage_vehicle_release_chunk (in FK order,
    chunked) -> activate_vehicle_release -> prune_vehicle_releases.

    Every call is safe to resend: begin_vehicle_release no-ops for an
    already-ACTIVE/SUPERSEDED release_id and resumes an in-progress STAGING
    one, each stage_vehicle_release_chunk call is idempotent by
    (release_id, section, chunk_index, chunk_hash), and activate_vehicle_release
    is a no-op once the release is already ACTIVE. Retention is also retried
    when begin reports that this release is already ACTIVE, so a publish that
    activated successfully but failed during pruning converges on the next
    invocation instead of leaving storage growth silent.
    """
    release_id = str(release["release_id"])
    manifest = _manifest(release)
    timings: dict = {"chunks": {}}

    t_start = time.monotonic()
    begun = _rpc("begin_vehicle_release", {"manifest": manifest}, url=url, service_key=service_key)
    timings["begin"] = time.monotonic() - t_start

    if begun.get("already_finalized"):
        status = begun["status"]
        if status != "ACTIVE":
            # SUPERSEDED means this exact release_id was once served and no
            # longer is -- some other release is active now. An exact
            # publish request for it succeeding would be a false positive:
            # the caller asked to publish THIS release, not to confirm it
            # was once live. (A later commit whose canonical changes already
            # reached production through a newer release is a different
            # question, answered by canonical_input_worker's own ancestry
            # -aware recovery, not by this function claiming success here.)
            raise RuntimeError(
                f"release {release_id} is already finalized as {status}, not ACTIVE -- "
                "this publish did not make it the active release"
            )
        t_prune = time.monotonic()
        retention = _prune_releases(url=url, service_key=service_key)
        timings["prune"] = time.monotonic() - t_prune
        timings["total"] = time.monotonic() - t_start
        return {"release_id": release_id, "status": status,
               "already_finalized": True, "retention": retention, "timings": timings}

    largest_chunk_seconds = 0.0
    for section in RELEASE_SECTIONS:
        rows = release.get(section) or []
        chunk_durations = []
        for chunk_index, chunk_rows in _chunks(rows, chunk_size):
            chunk_hash = _chunk_hash(chunk_rows)
            t_chunk = time.monotonic()
            _rpc("stage_vehicle_release_chunk", {
                "p_release_id": release_id,
                "p_section": section,
                "p_chunk_index": chunk_index,
                "p_chunk_hash": chunk_hash,
                "p_rows": chunk_rows,
            }, url=url, service_key=service_key)
            elapsed = time.monotonic() - t_chunk
            chunk_durations.append(elapsed)
            largest_chunk_seconds = max(largest_chunk_seconds, elapsed)
        if chunk_durations:
            timings["chunks"][section] = {
                "count": len(chunk_durations),
                "total_seconds": sum(chunk_durations),
            }

    t_activate = time.monotonic()
    activated = _rpc("activate_vehicle_release", {"p_release_id": release_id},
                     url=url, service_key=service_key)
    timings["activate"] = time.monotonic() - t_activate

    t_prune = time.monotonic()
    retention = _prune_releases(url=url, service_key=service_key)
    timings["prune"] = time.monotonic() - t_prune
    timings["largest_chunk"] = largest_chunk_seconds
    timings["total"] = time.monotonic() - t_start

    return {"release_id": release_id, "status": activated.get("status", "ACTIVE"),
           "counts": activated.get("counts"), "retention": retention,
           "timings": timings}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release", type=Path)
    parser.add_argument("--publish", action="store_true",
                        help="call Supabase; without this flag only validate and print")
    parser.add_argument("--chunk-size", type=int, default=CHUNK_SIZE)
    parser.add_argument("--legacy-single-call", action="store_true",
                        help="use the old one-transaction publish_vehicle_release(jsonb) "
                             "path instead of the staged protocol")
    args = parser.parse_args(argv)
    release = json.loads(args.release.read_text(encoding="utf-8"))
    expected = release.get("counts", {})
    for key in RELEASE_SECTIONS:
        if expected.get(key) != len(release.get(key, [])):
            raise SystemExit(f"count mismatch for {key}")
    if not args.publish:
        print(json.dumps({"validated": True, "release_id": release["release_id"],
                          "counts": expected}, ensure_ascii=False))
        return 0
    url = _clean_env_value(
        os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL"),
        "SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL",
    )
    key = _clean_env_value(
        os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
        "SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY",
    )
    if not url or not key:
        raise SystemExit(
            "SUPABASE_URL/NEXT_PUBLIC_SUPABASE_URL and "
            "SUPABASE_SECRET_KEY/SUPABASE_SERVICE_ROLE_KEY are required"
        )
    if args.legacy_single_call:
        print(json.dumps(publish(release, url=url, service_key=key), ensure_ascii=False))
    else:
        print(json.dumps(
            publish_staged(release, url=url, service_key=key, chunk_size=args.chunk_size),
            ensure_ascii=False,
        ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
