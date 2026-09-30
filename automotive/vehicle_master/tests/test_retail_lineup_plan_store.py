from __future__ import annotations

from pathlib import Path

import pytest

from tools.retail_lineup_plan_store import (
    RetailLineupPlanStoreError,
    begin_apply,
    mark_completed,
    mark_written,
    persist_preview,
    preview_summary,
)
from vehreg.retail_lineup_bootstrap import (
    LineupAction,
    LineupPlanItem,
    ModelLineupPlan,
    RetailLineupPlan,
)
from vehreg.retail_lineup_workbook import (
    RetailLineupWorkbookCompileResult,
    RetailLineupWorkbookMeta,
)

HEX_A = "a" * 64
HEX_B = "b" * 64
HEX_C = "c" * 64
COMMIT = "d" * 40


def _plan() -> RetailLineupPlan:
    return RetailLineupPlan(
        schema_version=1,
        as_of="2026-09-30",
        catalog_year=2026,
        base_release_id="vehicle-2026-test",
        baseline_hash=HEX_B,
        plan_hash=HEX_C,
        models=(
            ModelLineupPlan(
                model_id="acme.echo",
                before_current_trim_ids=("acme.echo.e1.trim.old_bev",),
                target_current_trim_ids=("acme.echo.e1.trim.new_bev",),
                items=(
                    LineupPlanItem(
                        LineupAction.CREATE,
                        "acme.echo",
                        "acme.echo.e1",
                        "acme.echo.e1.trim.new_bev",
                        "New",
                        "BEV",
                        "DETERMINISTIC_NEW_ID",
                    ),
                    LineupPlanItem(
                        LineupAction.ARCHIVE,
                        "acme.echo",
                        "acme.echo.e1",
                        "acme.echo.e1.trim.old_bev",
                        "Old",
                        "BEV",
                        "OMITTED_FROM_TARGET",
                    ),
                ),
            ),
        ),
    )


def _compiled() -> RetailLineupWorkbookCompileResult:
    plan = _plan()
    return RetailLineupWorkbookCompileResult(
        source_sha256=HEX_A,
        meta=RetailLineupWorkbookMeta(
            schema_version=1,
            generated_at="2026-09-30T09:00:00+00:00",
            as_of="2026-09-30",
            catalog_year=2026,
            base_release_id="vehicle-2026-test",
            baseline_hash=HEX_B,
            mode="REPLACE_AND_ARCHIVE",
            target_model_ids=("acme.echo",),
        ),
        rows_read=1,
        plan=plan,
    )


class FakeRest:
    def __init__(self):
        self.calls: list[tuple[str, str, object, str | None]] = []

    def __call__(self, method, path, payload=None, *, prefer=None):
        self.calls.append((method, path, payload, prefer))
        if path == "retail_lineup_plans":
            return [{"id": "plan-1", **payload}]
        if path.startswith("rpc/"):
            status = {
                "rpc/tdr_begin_retail_lineup_plan_apply": "APPLYING",
                "rpc/tdr_mark_retail_lineup_plan_written": "WRITTEN_PENDING_PUBLISH",
                "rpc/tdr_complete_retail_lineup_plan": "COMPLETED",
            }.get(path, "FAILED")
            return [{"id": "plan-1", "status": status}]
        raise AssertionError(path)


def test_preview_summary_is_small_but_complete_for_review_counts():
    summary = preview_summary(_plan())
    assert summary == {
        "schema_version": 1,
        "models": 1,
        "before_current": 1,
        "after_current": 1,
        "keep": 0,
        "create": 1,
        "reactivate": 0,
        "archive": 1,
        "model_diffs": [{
            "model_id": "acme.echo",
            "before_current": 1,
            "after_current": 1,
            "keep": 0,
            "create": 1,
            "reactivate": 0,
            "archive": 1,
        }],
    }


def test_persist_preview_stores_exact_immutable_plan_and_hashes():
    rest = FakeRest()
    row = persist_preview(
        _compiled(), actor="Owner", import_run_id="run-1", rest=rest)

    assert row["status"] == "PREVIEW_READY"
    assert len(rest.calls) == 1
    method, path, payload, prefer = rest.calls[0]
    assert (method, path, prefer) == ("POST", "retail_lineup_plans", "return=representation")
    assert payload["import_run_id"] == "run-1"
    assert payload["source_sha256"] == HEX_A
    assert payload["baseline_hash"] == HEX_B
    assert payload["plan_hash"] == HEX_C
    assert payload["compiled_plan"] == _plan().as_dict()
    assert payload["summary"]["create"] == 1
    assert payload["summary"]["archive"] == 1


def test_begin_apply_uses_both_reviewed_hashes_and_admin_identity():
    rest = FakeRest()
    row = begin_apply(
        "plan-1",
        actor="Second Admin",
        expected_plan_hash=HEX_C,
        expected_baseline_hash=HEX_B,
        rest=rest,
    )
    assert row["status"] == "APPLYING"
    _, path, payload, _ = rest.calls[0]
    assert path == "rpc/tdr_begin_retail_lineup_plan_apply"
    assert payload == {
        "p_plan_id": "plan-1",
        "p_actor": "Second Admin",
        "p_expected_plan_hash": HEX_C,
        "p_expected_baseline_hash": HEX_B,
    }


def test_write_and_complete_are_bound_to_same_plan_and_commit():
    rest = FakeRest()
    written = mark_written(
        "plan-1", expected_plan_hash=HEX_C, commit_sha=COMMIT, rest=rest)
    completed = mark_completed(
        "plan-1", expected_plan_hash=HEX_C, commit_sha=COMMIT,
        release_id="vehicle-2026-abc", rest=rest)

    assert written["status"] == "WRITTEN_PENDING_PUBLISH"
    assert completed["status"] == "COMPLETED"
    assert rest.calls[0][2]["p_commit_sha"] == COMMIT
    assert rest.calls[1][2]["p_commit_sha"] == COMMIT
    assert rest.calls[1][2]["p_release_id"] == "vehicle-2026-abc"


def test_empty_rpc_result_fails_closed():
    def empty(*_args, **_kwargs):
        return []

    with pytest.raises(RetailLineupPlanStoreError, match="exactly one durable plan row"):
        begin_apply(
            "plan-1", actor="Owner", expected_plan_hash=HEX_C,
            expected_baseline_hash=HEX_B, rest=empty)


def test_bad_commit_is_rejected_before_network():
    called = False

    def never(*_args, **_kwargs):
        nonlocal called
        called = True

    with pytest.raises(RetailLineupPlanStoreError, match="commit_sha"):
        mark_written("plan-1", expected_plan_hash=HEX_C, commit_sha="not-a-sha", rest=never)
    assert called is False


def test_migration_makes_preview_payload_write_once_and_service_only():
    root = Path(__file__).resolve().parents[3]
    sql = (root / "supabase" / "migration_v53_retail_lineup_plans.sql").read_text(
        encoding="utf-8")

    assert "create table if not exists public.retail_lineup_plans" in sql
    assert "RETAIL_LINEUP_PLAN_IMMUTABLE" in sql
    assert "new.compiled_plan is distinct from old.compiled_plan" in sql
    assert "new.source_sha256 is distinct from old.source_sha256" in sql
    assert "new.baseline_hash is distinct from old.baseline_hash" in sql
    assert "new.plan_hash is distinct from old.plan_hash" in sql
    assert "tdr_begin_retail_lineup_plan_apply" in sql
    assert "p_expected_plan_hash" in sql
    assert "p_expected_baseline_hash" in sql
    assert "WRITTEN_PENDING_PUBLISH" in sql
    assert "alter table public.retail_lineup_plans enable row level security" in sql
    assert "revoke all on table public.retail_lineup_plans from public, anon, authenticated" in sql
    assert "grant select, insert, update on table public.retail_lineup_plans to service_role" in sql
