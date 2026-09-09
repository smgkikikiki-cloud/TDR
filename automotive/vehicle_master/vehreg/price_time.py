"""Shared time semantics for the Price Intelligence pipeline.

Price Intelligence keeps observation/review timestamps as offset-aware instants.
Whenever one of those instants must be reduced to the date-only canonical price
ledger, TDR uses the Thailand business calendar (Asia/Bangkok).

Literal source dates such as ``effective_from`` / ``effective_to`` are *not*
passed through this module: they are evidence stated by the source and must be
preserved exactly rather than timezone-converted.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo


PRICE_BUSINESS_TIMEZONE = "Asia/Bangkok"
PRICE_BUSINESS_TZ = ZoneInfo(PRICE_BUSINESS_TIMEZONE)


def parse_aware_timestamp(raw: object) -> Optional[datetime]:
    """Parse an offset-aware ISO timestamp, returning ``None`` if invalid."""
    if not raw:
        return None
    text = str(raw).strip().replace("Z", "+00:00")
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return None
    return value


def thailand_business_date(value: datetime) -> date:
    """Reduce an aware instant to TDR's Thailand business calendar date."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("price timestamp must be offset-aware")
    return value.astimezone(PRICE_BUSINESS_TZ).date()


def thailand_business_date_from_iso(raw: object) -> Optional[date]:
    """Parse an aware timestamp and return its Thailand business date."""
    value = parse_aware_timestamp(raw)
    return thailand_business_date(value) if value is not None else None
