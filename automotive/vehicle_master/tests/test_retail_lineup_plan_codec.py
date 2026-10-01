from __future__ import annotations

from copy import deepcopy

import pytest

from vehreg.retail_lineup_bootstrap import (
    LineupAction,
    LineupPlanItem,
    ModelLineupPlan,
    RetailLineupBootstrapError,
    RetailLineupPlan,
)
from vehreg.retail_lineup_plan_codec import decode_retail_lineup_plan


# These fixtures intentionally use the real planner hash shape.  A durable row
# must be executable without recompiling the workbook, but any JSON tampering
# has to fail before the apply engine sees it.
def _plan_without_hash() -> RetailLineupPlan:
    return RetailLineupPlan(
        schema_version=1,
        as_of="2026-09-30",
        catalog_year=2026,
        base_release_id="vehicle-2026-test",
        baseline_hash="b" * 64,
        plan_hash="",
        models=(
            ModelLineupPlan(
                model_id="acme.echo",
                before_current_trim_ids=("acme.echo.e1.trim.a_bev",),
                target_current_trim_ids=("acme.echo.e1.trim.b_bev",),
                items=(
                    LineupPlanItem(
                        LineupAction.CREATE,
                        "acme.echo",
                        "acme.echo.e1",
                        "acme.echo.e1.trim.b_bev",
                        "B",
                        "BEV",
                        "DETERMINISTIC_NEW_ID",
                        False,
                    ),
                    LineupPlanItem(
                        LineupAction.ARCHIVE,
                        "acme.echo",
                        "acme.echo.e1",
                        "acme.echo.e1.trim.a_bev",
                        "A",
                        "BEV",
                        "OMITTED_FROM_TARGET",
                        False,
                    ),
                ),
            ),
        ),
    )


def _payload() -> dict:
    # Use the same canonical hash algorithm that Chunk 1/2 use by importing the
    # local helper only inside the test. The production decoder independently
    # recomputes it and must agree.
    from vehreg.retail_lineup_bootstrap_apply import _plan_hash

    plan = _plan_without_hash()
    plan = RetailLineupPlan(
        schema_version=plan.schema_version,
        as_of=plan.as_of,
        catalog_year=plan.catalog_year,
        base_release_id=plan.base_release_id,
        baseline_hash=plan.baseline_hash,
        plan_hash=_plan_hash(plan),
        models=plan.models,
    )
    return plan.as_dict()


def test_persisted_plan_round_trips_without_recompiling_workbook():
    payload = _payload()
    decoded = decode_retail_lineup_plan(
        payload,
        expected_plan_hash=payload["plan_hash"],
        expected_baseline_hash=payload["baseline_hash"],
    )
    assert decoded.as_dict() == payload


def test_changed_item_content_fails_plan_hash_integrity():
    payload = deepcopy(_payload())
    payload["models"][0]["items"][0]["trim_name"] = "Tampered"
    with pytest.raises(RetailLineupBootstrapError, match="PLAN_HASH_MISMATCH"):
        decode_retail_lineup_plan(payload)


def test_row_hash_mismatch_fails_before_apply():
    payload = _payload()
    with pytest.raises(RetailLineupBootstrapError, match="durable row"):
        decode_retail_lineup_plan(payload, expected_plan_hash="f" * 64)


def test_persisted_counts_are_not_trusted():
    payload = deepcopy(_payload())
    payload["counts"]["create"] = 99
    with pytest.raises(RetailLineupBootstrapError, match="top-level counts"):
        decode_retail_lineup_plan(payload)


def test_unknown_json_field_is_rejected():
    payload = deepcopy(_payload())
    payload["secret_recompile_hint"] = True
    with pytest.raises(RetailLineupBootstrapError, match="schema mismatch"):
        decode_retail_lineup_plan(payload)


def test_item_cannot_claim_another_model():
    payload = deepcopy(_payload())
    payload["models"][0]["items"][0]["model_id"] = "acme.other"
    with pytest.raises(RetailLineupBootstrapError, match="belongs to"):
        decode_retail_lineup_plan(payload)
