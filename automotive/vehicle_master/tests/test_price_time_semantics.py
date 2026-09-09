from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from tools.price_promote_batch import _candidate_window
from vehreg.price_reconcile import (
    CandidateState,
    PriceCandidate,
    ReconcileDisposition,
)
from vehreg.price_sources import TargetRole
from vehreg.price_time import (
    PRICE_BUSINESS_TIMEZONE,
    parse_aware_timestamp,
    thailand_business_date,
    thailand_business_date_from_iso,
)
from vehreg.pricing import PriceType


def test_same_instant_maps_to_one_thailand_business_date() -> None:
    # 2026-09-09 18:30Z is already 2026-09-10 in Thailand.
    stamps = (
        "2026-09-09T18:30:00Z",
        "2026-09-10T01:30:00+07:00",
        "2026-09-09T14:30:00-04:00",
    )
    assert {thailand_business_date_from_iso(value) for value in stamps} == {
        __import__("datetime").date(2026, 9, 10)
    }


def test_business_date_boundary_is_bangkok_midnight_not_utc_midnight() -> None:
    assert thailand_business_date_from_iso("2026-09-09T16:59:59+00:00").isoformat() == "2026-09-09"
    assert thailand_business_date_from_iso("2026-09-09T17:00:00+00:00").isoformat() == "2026-09-10"


def test_naive_timestamp_is_not_an_instant() -> None:
    assert parse_aware_timestamp("2026-09-10T01:30:00") is None
    assert thailand_business_date_from_iso("2026-09-10T01:30:00") is None
    with pytest.raises(ValueError, match="offset-aware"):
        thailand_business_date(datetime(2026, 9, 10, 1, 30))


def test_timezone_contract_is_explicit_and_not_machine_local() -> None:
    assert PRICE_BUSINESS_TIMEZONE == "Asia/Bangkok"


def _confirmed_candidate(*, confirmed_at: str) -> PriceCandidate:
    return PriceCandidate(
        candidate_id="pcand:timezone-batch",
        state=CandidateState.CONFIRMED,
        trim_id="test.brand.model.g1.trim.max",
        amount_thb=719000,
        price_type=PriceType.LIST_PRICE,
        source_id="official_test_th",
        target_id="test_price",
        target_role=TargetRole.PRICE_LIST,
        first_seen_at="2026-09-08T18:30:00+00:00",
        last_seen_at=confirmed_at,
        observation_count=2,
        claim_ids=("claim-1", "claim-2"),
        confirmed_at=confirmed_at,
        replaces_amount_thb=699000,
    )


def test_p6_batch_window_uses_thailand_business_date_for_inferred_start() -> None:
    candidate = _confirmed_candidate(confirmed_at="2026-09-09T18:30:00+00:00")

    start, _ = _candidate_window(
        candidate, ReconcileDisposition.CONFIRMED_REPLACEMENT)

    assert start.isoformat() == "2026-09-10"


def test_p6_batch_guards_do_not_reduce_system_instants_with_raw_date() -> None:
    """The CLI write boundary must use the same Bangkok date contract as P5/P6."""
    root = Path(__file__).resolve().parents[1]
    text = (root / "tools" / "price_promote_batch.py").read_text(encoding="utf-8")

    for forbidden in (
        "reviewed_at.date()",
        "last_seen.date()",
        "confirmed_at.date()",
        "first_seen.date()",
    ):
        assert forbidden not in text
