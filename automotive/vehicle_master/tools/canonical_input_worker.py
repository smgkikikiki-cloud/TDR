"""Move server-side input batches through canonical files, PRs and releases."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
from typing import Callable
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


def _active_vehicle_catalog_release() -> dict | None:
    """The release currently serving scope 'vehicle_catalog', read through
    the same canonical_vehicle_state -> canonical_vehicle_releases join
    every other reader of "what is live right now" uses (migration_v15).
    No new storage: this is the existing DB shape, read once here.

    Returns None on any read failure or missing/incomplete row -- callers
    treat that as "cannot determine ancestry", never as "nothing is live".
    """
    try:
        state = _request(
            "GET", "canonical_vehicle_state?select=active_release_id&scope=eq.vehicle_catalog",
        ) or []
        active_release_id = str(state[0].get("active_release_id") or "") if state else ""
        if not active_release_id:
            return None
        releases = _request(
            "GET", "canonical_vehicle_releases?select=release_id,canonical_revision"
            f"&release_id=eq.{quote(active_release_id)}",
        ) or []
        if not releases:
            return None
        release_id = str(releases[0].get("release_id") or "")
        canonical_revision = str(releases[0].get("canonical_revision") or "")
        if not release_id or not canonical_revision:
            return None
        return {"release_id": release_id, "canonical_revision": canonical_revision}
    except (RuntimeError, KeyError, IndexError, TypeError):
        return None


def _git_is_ancestor(ancestor_sha: str, descendant_sha: str) -> bool | None:
    """True/False from real git ancestry (`git merge-base --is-ancestor`),
    never from revision counting or ordinals: an active revision that is
    numerically newer is not proof it descends from a given commit if
    history ever diverged, and main normally fast-forwarding is not a
    guarantee worth trusting here when a one-line, authoritative check is
    just as easy to run.

    Returns None when the check itself could not be run or answered
    (unknown revision, no git binary, timeout, garbled repo state) -- the
    caller must not treat that as either a yes or a no.
    """
    try:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor_sha, descendant_sha],
            capture_output=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    return None  # unknown/invalid revision or another git-level error


def _resolve_staged_recovery(
    rows: list[dict],
    active_release: dict | None,
    is_ancestor: Callable[[str, str], bool | None],
) -> dict:
    """Decide, for the oldest commit still stuck STAGED, whether its
    canonical changes are already served by the active release (in which
    case nothing needs republishing -- the batch is simply marked
    PUBLISHED under that release) or whether it genuinely still needs the
    existing republish-exact-SHA recovery path.

    Pure decision logic, kept apart from the Supabase/git I/O in
    staged_batches() so scripts/check-*.ts's Python counterpart --
    tests/test_canonical_staged_publish_recovery.py -- can drive it with
    fakes for `active_release` and `is_ancestor` and assert the exact
    outcome, the same separation lib/canonical-vehicle-create.ts's
    classifyCreatedVehicleStatus already uses on the TypeScript side.

    Returns one of:
      {"mode": "none"}                                    -- nothing STAGED
      {"mode": "already_published", "release_id", "applied"}
      {"mode": "republish", "revision", "applied"}
      {"mode": "no_commit_url", "batch_id"}                -- unrecoverable automatically
    """
    if not rows:
        return {"mode": "none"}

    oldest_sha = _commit_sha_from_commit_url(str(rows[0].get("pull_request_url") or ""))
    if not oldest_sha:
        return {"mode": "no_commit_url", "batch_id": rows[0]["id"]}

    matching = [row for row in rows
               if _commit_sha_from_commit_url(str(row.get("pull_request_url") or "")) == oldest_sha]
    applied = [{"id": row["id"], "batch_key": row["batch_key"]} for row in matching]

    # Never guess "already live". Any uncertainty here -- no active release
    # on record, an incomplete row, ancestry that could not be checked --
    # falls through to the existing, already-safe republish path rather
    # than marking anything PUBLISHED on a hunch.
    if active_release is not None:
        active_revision = active_release.get("canonical_revision")
        if active_revision:
            if oldest_sha == active_revision:
                return {"mode": "already_published",
                       "release_id": active_release["release_id"], "applied": applied}
            ancestor = is_ancestor(oldest_sha, active_revision)
            if ancestor is True:
                return {"mode": "already_published",
                       "release_id": active_release["release_id"], "applied": applied}

    return {"mode": "republish", "revision": oldest_sha, "applied": applied}


def staged_batches(result_file: Path, limit: int) -> int:
    """The oldest commit still stuck STAGED, so a failed publish can be
    retried without re-applying any canonical write -- or, when a LATER
    batch's own publish already carried this commit's changes into the
    active release (this commit is a git ancestor of what is serving now),
    marked PUBLISHED directly with no republish at all.

    A STAGED batch already has its commit pushed -- mark_staged() only
    ever runs after that succeeds -- so nothing here ever re-runs
    CanonicalInputPipeline.apply(); either it asks tools.publish_canonical
    to build and activate a release from the tree that commit already put
    on disk, or it does not touch the write path at all. Only the SINGLE
    oldest commit is recovered per call: one workflow run's own "Apply N
    canonical input batch(es)" commit can carry several batches together,
    and grouping strictly by that shared commit is what keeps a batch from
    ever being marked PUBLISHED under a release built from a different
    commit's tree. A later tick recovers the next stuck commit, if there
    still is one.
    """
    rows = _request(
        "GET",
        "canonical_input_batches?select=id,batch_key,pull_request_url,created_at"
        f"&status=eq.STAGED&order=created_at.asc&limit={limit}",
    ) or []

    decision = _resolve_staged_recovery(rows, _active_vehicle_catalog_release(), _git_is_ancestor)

    if decision["mode"] == "none":
        result_file.write_text(json.dumps(
            {"applied": [], "revision": None, "already_published_release_id": None}), encoding="utf-8")
        print(json.dumps({"staged": 0, "revision": None}))
        return 0

    if decision["mode"] == "no_commit_url":
        # Nothing to recover automatically -- surfaced on the row itself
        # so an operator sees why, rather than this retrying forever with
        # no revision to publish.
        _request("PATCH", f"canonical_input_batches?id=eq.{quote(str(decision['batch_id']))}", {
            "error": "STAGED with no recorded commit URL; cannot recover automatically",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        result_file.write_text(json.dumps(
            {"applied": [], "revision": None, "already_published_release_id": None}), encoding="utf-8")
        print(json.dumps({"staged": len(rows), "revision": None, "recovering": 0}))
        return 0

    if decision["mode"] == "already_published":
        output = {
            "applied": decision["applied"], "revision": None,
            "already_published_release_id": decision["release_id"],
        }
        result_file.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({
            "staged": len(rows), "revision": None, "already_published": True,
            "release_id": decision["release_id"], "recovering": len(decision["applied"]),
        }))
        return 0

    output = {
        "applied": decision["applied"], "revision": decision["revision"],
        "already_published_release_id": None,
    }
    result_file.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "staged": len(rows), "revision": decision["revision"], "recovering": len(decision["applied"]),
    }))
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
