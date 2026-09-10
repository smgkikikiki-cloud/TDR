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


def mark_published(data_dir: Path, release_file: Path) -> int:
    release = json.loads(release_file.read_text(encoding="utf-8"))
    release_id = str(release["release_id"])
    markers = data_dir.glob("*/canonical_state/input_batches/*.json")
    count = 0
    for marker in markers:
        batch_key = str(json.loads(marker.read_text(encoding="utf-8"))["batch_id"])
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
    p_publish.add_argument("--data-dir", type=Path, default=DATA_DIR)
    p_publish.add_argument("--release-file", type=Path, required=True)
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
    return mark_published(args.data_dir, args.release_file)


if __name__ == "__main__":
    raise SystemExit(main())
