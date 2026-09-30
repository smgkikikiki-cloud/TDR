"""Durable Supabase state for Retail Lineup Bootstrap preview plans.

Chunk 5 only persists/retrieves immutable compiled plans and drives the small
status machine exposed by migration_v53.  It never compiles a workbook and it
never touches canonical files.  Chunk 7 will wire this helper into the source
import worker; Chunk 6 will add the Admin UI that reviews/approves the rows.
"""
from __future__ import annotations

from collections.abc import Callable
import json
import re
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from tools.canonical_input_worker import _env
from vehreg.retail_lineup_bootstrap import RetailLineupPlan
from vehreg.retail_lineup_workbook import RetailLineupWorkbookCompileResult

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40,64}$")


class RetailLineupPlanStoreError(RuntimeError):
    pass


def _headers(key: str) -> dict[str, str]:
    headers = {"apikey": key, "accept": "application/json"}
    if key.startswith("eyJ"):
        headers["authorization"] = f"Bearer {key}"
    return headers


def _rest(method: str, path: str, payload: Any = None, *, prefer: str | None = None):
    url, key = _env()
    headers = _headers(key)
    body = None
    if payload is not None:
        headers["content-type"] = "application/json"
        body = json.dumps(payload, ensure_ascii=False).encode()
    if prefer:
        headers["prefer"] = prefer
    request = Request(f"{url}/rest/v1/{path}", data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=120) as response:
            content = response.read().decode()
    except HTTPError as exc:
        raise RetailLineupPlanStoreError(
            f"Supabase request failed ({exc.code}): "
            f"{exc.read().decode(errors='replace')[:500]}"
        ) from exc
    return json.loads(content) if content else None


RestCall = Callable[..., Any]


def _hash(value: str, *, label: str) -> str:
    normalized = str(value or "").strip().lower()
    if not _HEX64.fullmatch(normalized):
        raise RetailLineupPlanStoreError(f"{label} must be a lowercase SHA-256 hex digest")
    return normalized


def _commit(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if not _GIT_SHA.fullmatch(normalized):
        raise RetailLineupPlanStoreError("commit_sha must be a 40-64 character lowercase hex digest")
    return normalized


def _one(rows: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise RetailLineupPlanStoreError(f"{label} expected exactly one durable plan row")
    return dict(rows[0])


def preview_summary(plan: RetailLineupPlan) -> dict[str, Any]:
    """Small durable diff summary for list/review screens.

    The full immutable truth remains ``compiled_plan``.  This summary is stored
    beside it only so Admin pages never need to reverse engineer counts from a
    JSON payload to render a queue/list view.
    """
    models = []
    for model in plan.models:
        models.append({
            "model_id": model.model_id,
            "before_current": len(model.before_current_trim_ids),
            "after_current": len(model.target_current_trim_ids),
            **model.counts,
        })
    return {
        "schema_version": 1,
        "models": len(plan.models),
        "before_current": sum(row["before_current"] for row in models),
        "after_current": sum(row["after_current"] for row in models),
        **plan.counts,
        "model_diffs": models,
    }


def persist_preview(
    compiled: RetailLineupWorkbookCompileResult,
    *,
    actor: str,
    import_run_id: str | None = None,
    rest: RestCall = _rest,
) -> dict[str, Any]:
    """Insert one immutable PREVIEW_READY row.

    Retries intentionally create a new preview unless the caller chooses to
    reuse the returned id.  A preview is an audit object, not a mutable slot.
    """
    actor = str(actor or "").strip()
    if not actor:
        raise RetailLineupPlanStoreError("actor is required")
    source_sha256 = _hash(compiled.source_sha256, label="source_sha256")
    baseline_hash = _hash(compiled.plan.baseline_hash, label="baseline_hash")
    plan_hash = _hash(compiled.plan.plan_hash, label="plan_hash")
    plan_payload = compiled.plan.as_dict()
    if plan_payload.get("baseline_hash") != baseline_hash:
        raise RetailLineupPlanStoreError("compiled plan baseline hash changed during persistence")
    if plan_payload.get("plan_hash") != plan_hash:
        raise RetailLineupPlanStoreError("compiled plan hash changed during persistence")

    payload: dict[str, Any] = {
        "status": "PREVIEW_READY",
        "actor": actor,
        "source_sha256": source_sha256,
        "baseline_hash": baseline_hash,
        "plan_hash": plan_hash,
        "compiled_plan": plan_payload,
        "summary": preview_summary(compiled.plan),
    }
    if import_run_id:
        payload["import_run_id"] = str(import_run_id).strip()

    row = _one(
        rest("POST", "retail_lineup_plans", payload, prefer="return=representation") or [],
        label="persist preview",
    )
    for key, expected in (
        ("source_sha256", source_sha256),
        ("baseline_hash", baseline_hash),
        ("plan_hash", plan_hash),
        ("status", "PREVIEW_READY"),
    ):
        if str(row.get(key) or "") != expected:
            raise RetailLineupPlanStoreError(f"persisted preview returned unexpected {key}")
    return row


def fetch_preview(plan_id: str, *, rest: RestCall = _rest) -> dict[str, Any]:
    plan_id = str(plan_id or "").strip()
    if not plan_id:
        raise RetailLineupPlanStoreError("plan_id is required")
    rows = rest(
        "GET",
        "retail_lineup_plans?select=*&id=eq." + quote(plan_id) + "&limit=2",
    ) or []
    return _one(rows, label="fetch preview")


def begin_apply(
    plan_id: str,
    *,
    actor: str,
    expected_plan_hash: str,
    expected_baseline_hash: str,
    rest: RestCall = _rest,
) -> dict[str, Any]:
    actor = str(actor or "").strip()
    if not actor:
        raise RetailLineupPlanStoreError("actor is required")
    payload = {
        "p_plan_id": str(plan_id or "").strip(),
        "p_actor": actor,
        "p_expected_plan_hash": _hash(expected_plan_hash, label="plan_hash"),
        "p_expected_baseline_hash": _hash(expected_baseline_hash, label="baseline_hash"),
    }
    if not payload["p_plan_id"]:
        raise RetailLineupPlanStoreError("plan_id is required")
    return _one(
        rest("POST", "rpc/tdr_begin_retail_lineup_plan_apply", payload,
             prefer="return=representation") or [],
        label="begin apply",
    )


def mark_written(
    plan_id: str,
    *,
    expected_plan_hash: str,
    commit_sha: str,
    rest: RestCall = _rest,
) -> dict[str, Any]:
    payload = {
        "p_plan_id": str(plan_id or "").strip(),
        "p_expected_plan_hash": _hash(expected_plan_hash, label="plan_hash"),
        "p_commit_sha": _commit(commit_sha),
    }
    if not payload["p_plan_id"]:
        raise RetailLineupPlanStoreError("plan_id is required")
    return _one(
        rest("POST", "rpc/tdr_mark_retail_lineup_plan_written", payload,
             prefer="return=representation") or [],
        label="mark written",
    )


def mark_completed(
    plan_id: str,
    *,
    expected_plan_hash: str,
    commit_sha: str,
    release_id: str,
    rest: RestCall = _rest,
) -> dict[str, Any]:
    release_id = str(release_id or "").strip()
    if not release_id:
        raise RetailLineupPlanStoreError("release_id is required")
    payload = {
        "p_plan_id": str(plan_id or "").strip(),
        "p_expected_plan_hash": _hash(expected_plan_hash, label="plan_hash"),
        "p_commit_sha": _commit(commit_sha),
        "p_release_id": release_id,
    }
    if not payload["p_plan_id"]:
        raise RetailLineupPlanStoreError("plan_id is required")
    return _one(
        rest("POST", "rpc/tdr_complete_retail_lineup_plan", payload,
             prefer="return=representation") or [],
        label="mark completed",
    )


def mark_failed(
    plan_id: str,
    *,
    expected_plan_hash: str,
    error: str,
    rest: RestCall = _rest,
) -> dict[str, Any]:
    payload = {
        "p_plan_id": str(plan_id or "").strip(),
        "p_expected_plan_hash": _hash(expected_plan_hash, label="plan_hash"),
        "p_error": str(error or "apply failed")[:4000],
    }
    if not payload["p_plan_id"]:
        raise RetailLineupPlanStoreError("plan_id is required")
    return _one(
        rest("POST", "rpc/tdr_fail_retail_lineup_plan_apply", payload,
             prefer="return=representation") or [],
        label="mark failed",
    )


def mark_stale(
    plan_id: str,
    *,
    expected_plan_hash: str,
    error: str = "STALE_BASELINE",
    rest: RestCall = _rest,
) -> dict[str, Any]:
    payload = {
        "p_plan_id": str(plan_id or "").strip(),
        "p_expected_plan_hash": _hash(expected_plan_hash, label="plan_hash"),
        "p_error": str(error or "STALE_BASELINE")[:4000],
    }
    if not payload["p_plan_id"]:
        raise RetailLineupPlanStoreError("plan_id is required")
    return _one(
        rest("POST", "rpc/tdr_mark_retail_lineup_plan_stale", payload,
             prefer="return=representation") or [],
        label="mark stale",
    )


__all__ = [
    "RetailLineupPlanStoreError",
    "begin_apply",
    "fetch_preview",
    "mark_completed",
    "mark_failed",
    "mark_stale",
    "mark_written",
    "persist_preview",
    "preview_summary",
]
