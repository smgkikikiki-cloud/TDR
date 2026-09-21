"""Move server-side input batches through canonical files, PRs and releases."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from vehreg.catalog import DATA_DIR
from vehreg.input_pipeline import CanonicalInputError, CanonicalInputPipeline


def _strip_wrapper_quotes(value: str) -> str:
    cleaned = value.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
        return cleaned[1:-1].strip()
    return cleaned


def _clean_env_value(value: str | None, *names: str) -> str:
    """Accept a bare secret or copied/quoted ``NAME=value`` assignment."""
    cleaned = _strip_wrapper_quotes(value or "")
    if "=" in cleaned:
        prefix, remainder = cleaned.split("=", 1)
        if prefix.strip() in names:
            cleaned = remainder.strip()
    return _strip_wrapper_quotes(cleaned)


def _env() -> tuple[str, str]:
    url = _clean_env_value(
        os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL"),
        "SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL",
    )
    key = _clean_env_value(
        os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
        "SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY",
    )
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SECRET_KEY/SUPABASE_SERVICE_ROLE_KEY are required")
    return url.rstrip("/"), key


def _request(method: str, path: str, payload=None, *, prefer: str | None = None):
    url, key = _env()
    headers = {"apikey": key, "accept": "application/json"}
    if key.startswith("eyJ"):
        headers["authorization"] = f"Bearer {key}"
    body = None
    if payload is not None:
        headers["content-type"] = "application/json"
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    if prefer:
        headers["prefer"] = prefer
    request = Request(f"{url}/rest/v1/{path}", data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=60) as response:
            content = response.read().decode()
    except HTTPError as exc:
        content = exc.read().decode(errors="replace")
        raise RuntimeError(f"Supabase request failed ({exc.code}): {content[:1000]}") from exc
    return json.loads(content) if content else None


def _rows(status: str, limit: int) -> list[dict]:
    return _request(
        "GET",
        "canonical_input_batches?select=id,batch_key,payload,status,attempts,actor,created_at,processing_started_at"
        f"&status=eq.{status}&order=created_at.asc&limit={limit}",
    ) or []


def _patch(row_id: str, expected_status: str, payload: dict):
    return _request(
        "PATCH",
        f"canonical_input_batches?id=eq.{quote(row_id)}&status=eq.{quote(expected_status)}",
        payload,
        prefer="return=representation",
    ) or []


def check_connection() -> int:
    _request("GET", "canonical_input_batches?select=id&limit=0")
    print(json.dumps({"supabase": "ready", "canonical_input_batches": "accessible"}))
    return 0


def pull(data_dir: Path, result_file: Path, limit: int) -> int:
    now = datetime.now(timezone.utc)
    candidates = _rows("QUEUED", limit)
    remaining = max(limit - len(candidates), 0)
    if remaining:
        for row in _rows("PROCESSING", remaining * 4 or 4):
            started = row.get("processing_started_at")
            try:
                stale = datetime.fromisoformat(str(started).replace("Z", "+00:00")) < now - timedelta(hours=1)
            except (TypeError, ValueError):
                stale = True
            if stale:
                candidates.append(row)
                if len(candidates) >= limit:
                    break

    output = {"applied": [], "failed": []}
    pipeline = CanonicalInputPipeline(data_dir)
    for row in candidates:
        claimed = _patch(row["id"], row["status"], {
            "status": "PROCESSING",
            "attempts": int(row.get("attempts") or 0) + 1,
            "processing_started_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "error": None,
        })
        if not claimed:
            continue
        try:
            batch_payload = dict(row["payload"])
            batch_payload.setdefault("actor", row.get("actor") or "system")
            batch_payload.setdefault("submitted_at", row.get("created_at"))
            result = pipeline.apply(batch_payload)
            output["applied"].append({
                "id": row["id"], "batch_key": row["batch_key"],
                "batch_hash": result.batch_hash,
                "changed_files": list(result.changed_files),
            })
        except (CanonicalInputError, ValueError) as exc:
            message = str(exc)[:2000]
            _patch(row["id"], "PROCESSING", {
                "status": "FAILED", "error": message, "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            output["failed"].append({"id": row["id"], "batch_key": row["batch_key"], "error": message})
    result_file.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"applied": len(output["applied"]), "failed": len(output["failed"])}, ensure_ascii=False))
    return 0


def mark_staged(result_file: Path, pull_request_url: str) -> int:
    payload = json.loads(result_file.read_text(encoding="utf-8"))
    for row in payload.get("applied", []):
        _patch(row["id"], "PROCESSING", {
            "status": "STAGED", "pull_request_url": pull_request_url,
            "staged_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
    return 0


def mark_published(result_file: Path, release_id: str) -> int:
    """Mark PUBLISHED exactly the batches this run's own pull applied.

    Named batches only, read from the same result file mark_staged() used
    -- not a glob over every input_batches marker ever written to the
    tree. A marker sweep would mark PUBLISHED any STAGED batch whose file
    still happens to be on disk regardless of which run applied it or
    which release call is doing the marking, the same class of bug
    tools.import_worker.finalize()'s own "named runs only" rule exists to
    avoid. Called only after publish has actually succeeded, so a batch
    whose publish failed is never marked PUBLISHED at all -- it stays
    STAGED, exactly where a retried publish will find and finish it.
    """
    if not release_id:
        raise SystemExit("mark-published needs the release_id the publish produced")
    payload = json.loads(result_file.read_text(encoding="utf-8"))
    batch_keys = [str(row["batch_key"]) for row in payload.get("applied", [])]
    count = 0
    for batch_key in batch_keys:
        rows = _request(
            "PATCH",
            "canonical_input_batches?batch_key=eq."
            f"{quote(batch_key)}&status=in.(STAGED,PROCESSING)",
            {
                "status": "PUBLISHED", "release_id": release_id,
                "published_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(), "error": None,
            },
            prefer="return=representation",
        ) or []
        count += len(rows)
    print(json.dumps({"published_batches": count, "release_id": release_id}))
    return 0


def _commit_sha_from_commit_url(url: str) -> str | None:
    """pull_request_url is actually a commit URL for this repo -- it pushes
    straight to main rather than through a PR (see mark_staged()'s own
    caller in canonical-input.yml, which passes
    ``.../commit/$(git rev-parse HEAD)``). Its trailing path segment is
    exactly the commit sha a stuck batch was pushed in, so recovering a
    STAGED batch needs no new column: this field already carries it."""
    trimmed = str(url or "").rstrip("/")
    if not trimmed:
        return None
    sha = trimmed.rsplit("/", 1)[-1]
    return sha or None


def staged_batches(result_file: Path, limit: int) -> int:
    """The oldest commit still stuck STAGED, so a failed publish can be
    retried without re-applying any canonical write.

    A STAGED batch already has its commit pushed -- mark_staged() only
    ever runs after that succeeds -- so nothing here re-runs
    CanonicalInputPipeline.apply(); it only asks tools.publish_canonical to
    build and activate a release from the tree that commit already put on
    disk. Only the SINGLE oldest commit is recovered per call: one workflow
    run's own "Apply N canonical input batch(es)" commit can carry several
    batches together, and grouping strictly by that shared commit is what
    keeps a batch from ever being marked PUBLISHED under a release actually
    built from a different commit's tree. A later tick recovers the next
    stuck commit, if there still is one.
    """
    rows = _request(
        "GET",
        "canonical_input_batches?select=id,batch_key,pull_request_url,created_at"
        f"&status=eq.STAGED&order=created_at.asc&limit={limit}",
    ) or []
    if not rows:
        result_file.write_text(json.dumps({"applied": [], "revision": None}), encoding="utf-8")
        print(json.dumps({"staged": 0, "revision": None}))
        return 0

    oldest_sha = _commit_sha_from_commit_url(str(rows[0].get("pull_request_url") or ""))
    if not oldest_sha:
        # Nothing to recover automatically -- surfaced on the row itself
        # so an operator sees why, rather than this retrying forever with
        # no revision to publish.
        _request("PATCH", f"canonical_input_batches?id=eq.{quote(str(rows[0]['id']))}", {
            "error": "STAGED with no recorded commit URL; cannot recover automatically",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        result_file.write_text(json.dumps({"applied": [], "revision": None}), encoding="utf-8")
        print(json.dumps({"staged": len(rows), "revision": None, "recovering": 0}))
        return 0

    matching = [row for row in rows
               if _commit_sha_from_commit_url(str(row.get("pull_request_url") or "")) == oldest_sha]
    output = {
        "applied": [{"id": row["id"], "batch_key": row["batch_key"]} for row in matching],
        "revision": oldest_sha,
    }
    result_file.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"staged": len(rows), "revision": oldest_sha, "recovering": len(matching)}))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    p_pull = sub.add_parser("pull")
    p_pull.add_argument("--data-dir", type=Path, default=DATA_DIR)
    p_pull.add_argument("--result-file", type=Path, required=True)
    p_pull.add_argument("--limit", type=int, default=10)
    p_stage = sub.add_parser("mark-staged")
    p_stage.add_argument("--result-file", type=Path, required=True)
    p_stage.add_argument("--pull-request-url", required=True)
    p_publish = sub.add_parser("mark-published")
    p_publish.add_argument("--result-file", type=Path, required=True)
    p_publish.add_argument("--release-id", required=True)
    p_staged = sub.add_parser("staged-batches")
    p_staged.add_argument("--result-file", type=Path, required=True)
    p_staged.add_argument("--limit", type=int, default=50)
    args = parser.parse_args(argv)
    if args.command == "check":
        try:
            return check_connection()
        except RuntimeError as exc:
            print(json.dumps({"supabase": "unavailable", "error": str(exc)}, ensure_ascii=False))
            return 2
    if args.command == "pull":
        return pull(args.data_dir, args.result_file, max(1, min(args.limit, 50)))
    if args.command == "mark-staged":
        return mark_staged(args.result_file, args.pull_request_url)
    if args.command == "staged-batches":
        return staged_batches(args.result_file, max(1, min(args.limit, 200)))
    return mark_published(args.result_file, args.release_id)


if __name__ == "__main__":
    raise SystemExit(main())
