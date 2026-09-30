"""Execute one already-approved immutable Retail Lineup Bootstrap plan.

The Admin/Vercel side only transitions a reviewed plan to APPLYING. This worker
fetches that durable row, strictly decodes the stored ``compiled_plan`` without
recompiling the workbook, runs the whole-tree atomic transaction, and exposes
small CLI transitions for the workflow to record the pushed commit and serving
release.

A scheduled workflow calls ``next`` as a recovery sweep, so a lost
repository_dispatch after Admin confirmation cannot strand APPLYING forever.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from tools.retail_lineup_plan_store import (
    _rest,
    fetch_preview,
    mark_completed,
    mark_failed,
    mark_stale,
    mark_written,
)
from vehreg.retail_lineup_bootstrap import RetailLineupBootstrapError
from vehreg.retail_lineup_bootstrap_transaction import apply_retail_lineup_plan_atomically
from vehreg.retail_lineup_plan_codec import decode_retail_lineup_plan


def _write_result(path: str | None, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text + "\n", encoding="utf-8")
    print(text)


def next_plan(status: str = "APPLYING") -> str:
    status = str(status or "").strip().upper()
    if status not in {"APPLYING", "WRITTEN_PENDING_PUBLISH"}:
        raise SystemExit("next status must be APPLYING or WRITTEN_PENDING_PUBLISH")
    rows = _rest(
        "GET",
        "retail_lineup_plans?select=id&status=eq." + quote(status)
        + "&order=applying_at.asc.nullslast,created_at.asc&limit=1",
    ) or []
    if not rows:
        return ""
    return str(rows[0].get("id") or "").strip()


def prepare(plan_id: str, *, result_file: str | None = None) -> dict[str, Any]:
    row = fetch_preview(plan_id)
    status = str(row.get("status") or "").upper()
    if status != "APPLYING":
        payload = {"plan_id": plan_id, "status": status, "prepared": False}
        _write_result(result_file, payload)
        return payload

    plan_hash = str(row.get("plan_hash") or "")
    baseline_hash = str(row.get("baseline_hash") or "")
    try:
        plan = decode_retail_lineup_plan(
            row.get("compiled_plan") or {},
            expected_plan_hash=plan_hash,
            expected_baseline_hash=baseline_hash,
        )
        actor = str(row.get("approved_by") or "").strip()
        submitted_at = str(row.get("approved_at") or row.get("applying_at") or "").strip()
        result = apply_retail_lineup_plan_atomically(
            plan,
            actor=actor,
            submitted_at=submitted_at,
            reason=f"Retail Lineup Bootstrap plan {plan.plan_hash}",
        )
    except RetailLineupBootstrapError as exc:
        message = str(exc)
        if "STALE_BASELINE" in message:
            mark_stale(plan_id, expected_plan_hash=plan_hash, error=message)
            payload = {"plan_id": plan_id, "status": "STALE", "prepared": False,
                       "error": message}
        else:
            mark_failed(plan_id, expected_plan_hash=plan_hash, error=message)
            payload = {"plan_id": plan_id, "status": "FAILED", "prepared": False,
                       "error": message}
        _write_result(result_file, payload)
        return payload
    except Exception as exc:  # noqa: BLE001 - durable state must record any apply failure
        message = str(exc)[:4000] or exc.__class__.__name__
        mark_failed(plan_id, expected_plan_hash=plan_hash, error=message)
        payload = {"plan_id": plan_id, "status": "FAILED", "prepared": False,
                   "error": message}
        _write_result(result_file, payload)
        return payload

    payload = {
        "plan_id": plan_id,
        "status": "APPLYING",
        "prepared": True,
        "plan_hash": plan.plan_hash,
        "baseline_hash": plan.baseline_hash,
        "changed_files": list(result.changed_files),
        "idempotent_replay": result.idempotent_replay,
        "counts": result.counts,
        "validated_release_id": result.release.release_id,
    }
    _write_result(result_file, payload)
    return payload


def record_written(plan_id: str, commit_sha: str) -> dict[str, Any]:
    row = fetch_preview(plan_id)
    result = mark_written(
        plan_id,
        expected_plan_hash=str(row.get("plan_hash") or ""),
        commit_sha=commit_sha,
    )
    print(json.dumps({"plan_id": plan_id, "status": result.get("status"),
                      "commit_sha": result.get("applied_commit_sha")}, ensure_ascii=False))
    return result


def complete(plan_id: str, commit_sha: str, release_id: str) -> dict[str, Any]:
    row = fetch_preview(plan_id)
    result = mark_completed(
        plan_id,
        expected_plan_hash=str(row.get("plan_hash") or ""),
        commit_sha=commit_sha,
        release_id=release_id,
    )
    print(json.dumps({"plan_id": plan_id, "status": result.get("status"),
                      "commit_sha": result.get("applied_commit_sha"),
                      "release_id": result.get("release_id")}, ensure_ascii=False))
    return result


def describe(plan_id: str) -> dict[str, Any]:
    row = fetch_preview(plan_id)
    payload = {
        "id": row.get("id"),
        "status": row.get("status"),
        "plan_hash": row.get("plan_hash"),
        "baseline_hash": row.get("baseline_hash"),
        "applied_commit_sha": row.get("applied_commit_sha"),
        "release_id": row.get("release_id"),
    }
    print(json.dumps(payload, ensure_ascii=False))
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_next = sub.add_parser("next")
    p_next.add_argument("--status", default="APPLYING")

    p_prepare = sub.add_parser("prepare")
    p_prepare.add_argument("--plan-id", required=True)
    p_prepare.add_argument("--result-file")

    p_written = sub.add_parser("mark-written")
    p_written.add_argument("--plan-id", required=True)
    p_written.add_argument("--commit-sha", required=True)

    p_complete = sub.add_parser("complete")
    p_complete.add_argument("--plan-id", required=True)
    p_complete.add_argument("--commit-sha", required=True)
    p_complete.add_argument("--release-id", required=True)

    p_describe = sub.add_parser("describe")
    p_describe.add_argument("--plan-id", required=True)

    args = parser.parse_args(argv)
    if args.command == "next":
        print(next_plan(args.status))
        return 0
    if args.command == "prepare":
        prepare(args.plan_id, result_file=args.result_file)
        return 0
    if args.command == "mark-written":
        record_written(args.plan_id, args.commit_sha)
        return 0
    if args.command == "complete":
        complete(args.plan_id, args.commit_sha, args.release_id)
        return 0
    describe(args.plan_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
