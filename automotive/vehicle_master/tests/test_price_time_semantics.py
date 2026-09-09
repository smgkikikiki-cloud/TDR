from __future__ import annotations

from datetime import datetime

import pytest

from vehreg.price_time import (
    PRICE_BUSINESS_TIMEZONE,
    parse_aware_timestamp,
    thailand_business_date,
    thailand_business_date_from_iso,
)


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
