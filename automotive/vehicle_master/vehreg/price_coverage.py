"""Catalog-driven price coverage gaps: what work Price Feed's coverage/scout
entry mode should fetch next.

This asks the same question app/admin's price-coverage dashboard
(lib/price-coverage-worklist.ts) already asks of the serving Supabase
projection, but locally, against the same Catalog + PriceLedger the
harvest/write pipeline itself reads before anything is published --
coverage mode has to plan its next fetch from the tree it is about to
publish from, not from what is already being served.

Nothing here fetches, matches, resolves or writes a price. It only says
which MarketTrims currently lack a resolvable LIST_PRICE, which one has a
LIST_PRICE old enough to be worth re-checking, and which one the ledger
itself cannot resolve at all (a genuine conflict) -- grouped by model, so
the caller can turn that into a handful of source-target fetches instead
of one request per trim.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from .catalog import Catalog
from .price_coverage_review import load_coverage_decisions
from .pricing import PriceLedger, PricingError

#: A served LIST_PRICE older than this (by its own effective_from/observed_at)
#: is worth a fresh look, not because it is wrong -- most of the time it will
#: still be exactly right -- but because nothing else in this pipeline ever
#: re-confirms a price once it has one. Deliberately generous: this is a
#: "worth checking" threshold, not a validity window, and a shorter one
#: would just mean re-fetching pages that had not actually changed.
DEFAULT_STALE_AFTER_DAYS = 180

MISSING = "MISSING"
STALE = "STALE"
CONFLICT = "CONFLICT"
REASONS = (MISSING, STALE, CONFLICT)


@dataclass(frozen=True, slots=True)
class TrimGap:
    trim_id: str
    reason: str            # MISSING | STALE | CONFLICT
    detail: str = ""        # e.g. "last observed 2026-01-04" or the PricingError text


@dataclass(frozen=True, slots=True)
class ModelCoverageGap:
    model_id: str
    brand_id: str
    trims: tuple[TrimGap, ...]

    def as_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "brand_id": self.brand_id,
            "trims": [{"trim_id": t.trim_id, "reason": t.reason, "detail": t.detail}
                     for t in self.trims],
        }


def _trim_gap(ledger: PriceLedger, trim_id: str, *,
             as_of: date, stale_after_days: int) -> Optional[TrimGap]:
    try:
        current = ledger.current_list_price(trim_id, as_of=as_of)
    except PricingError as exc:
        return TrimGap(trim_id, CONFLICT, str(exc))
    if current is None:
        return TrimGap(trim_id, MISSING)
    start = current.effective_from or current.observed_at
    if start and (as_of - date.fromisoformat(start)).days > stale_after_days:
        return TrimGap(trim_id, STALE, f"current since {start}")
    return None


def coverage_gaps(catalog: Catalog, ledger: PriceLedger, *,
                  as_of: Optional[date] = None,
                  stale_after_days: int = DEFAULT_STALE_AFTER_DAYS,
                  data_dir=None, year: Optional[int] = None,
                  skip_deferred: bool = True) -> list[ModelCoverageGap]:
    """Every model with at least one trim needing price work, sorted by
    model_id -- deterministic, so two runs over the same tree produce the
    same work list and the same fetch order.

    A trim a HUMAN has explicitly deferred (price_coverage_review.py,
    the same dashboard workflow that defers MISSING_LIST_PRICE work today)
    is left out of MISSING/STALE by default: the point of a defer decision
    is that it must not be re-surfaced as work again next tick. A CONFLICT
    is never deferrable this way -- that decision itself requires the
    ledger to already resolve a LIST_PRICE, which a conflicted trim by
    definition does not.
    """
    when = as_of or date.today()
    deferred: set[str] = set()
    if skip_deferred and data_dir is not None and year is not None:
        deferred = {row["trim_id"] for row in
                   load_coverage_decisions(data_dir=data_dir, year=year)}

    by_model: dict[str, list[TrimGap]] = {}
    for trim_id in sorted(catalog.trims):
        gap = _trim_gap(ledger, trim_id, as_of=when, stale_after_days=stale_after_days)
        if gap is None:
            continue
        if gap.reason != CONFLICT and trim_id in deferred:
            continue
        model = catalog.model_for_trim(trim_id)
        by_model.setdefault(model.id, []).append(gap)

    gaps = [
        ModelCoverageGap(
            model_id=model_id,
            brand_id=catalog.models[model_id].brand_id,
            trims=tuple(sorted(trims, key=lambda t: t.trim_id)),
        )
        for model_id, trims in by_model.items()
    ]
    return sorted(gaps, key=lambda g: g.model_id)


def summarize(catalog: Catalog, ledger: PriceLedger, *,
             as_of: Optional[date] = None) -> dict:
    """Aggregate counts for a report/log line -- not the work list itself."""
    when = as_of or date.today()
    total = len(catalog.trims)
    with_current = 0
    counts = {reason: 0 for reason in REASONS}
    for trim_id in catalog.trims:
        gap = _trim_gap(ledger, trim_id, as_of=when,
                        stale_after_days=DEFAULT_STALE_AFTER_DAYS)
        if gap is None:
            with_current += 1
        else:
            counts[gap.reason] += 1
    return {"total_trims": total, "trims_with_current_list_price": with_current,
           **{f"trims_{reason.lower()}": count for reason, count in counts.items()}}
