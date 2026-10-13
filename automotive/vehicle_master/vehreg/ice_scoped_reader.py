"""Offline M4 registration reader over the reviewed R6 scoped crosswalk.

This adapter is deliberately disconnected from production routes. It maps each
Ice fact one-for-one before deriving model/segment/body totals, so repetitions
across period, province and DLT class remain facts rather than duplicates.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping

from .ice_scoped_crosswalk import IceFact, ResolvedFact, ScopedCrosswalk


@dataclass(frozen=True)
class IceRegistrationFact:
    period: str
    province: str
    reg_type: str
    model_group_id: str
    brand: str
    model_name: str
    registrations: int


@dataclass(frozen=True)
class ScopedRegistrationFact:
    period: str
    province: str
    reg_type: str
    model_group_id: str
    brand: str
    model_name: str
    registrations: int
    canonical_model_id: str | None
    mapping_status: str
    owner_decision_ref: str | None


def resolve_registration_rows(
    facts: Iterable[IceRegistrationFact],
    resolver: ScopedCrosswalk,
) -> list[ScopedRegistrationFact]:
    """Resolve every period×province×class×group row exactly once."""
    out: list[ScopedRegistrationFact] = []
    for fact in facts:
        if not fact.period or not fact.province or not fact.brand:
            raise ValueError("Ice registration fact is missing period/province/brand")
        resolved: ResolvedFact = resolver.resolve(
            IceFact(fact.model_group_id, fact.reg_type, fact.registrations)
        )
        out.append(ScopedRegistrationFact(
            period=fact.period,
            province=fact.province,
            reg_type=resolved.reg_type,
            model_group_id=fact.model_group_id,
            brand=fact.brand,
            model_name=fact.model_name,
            registrations=fact.registrations,
            canonical_model_id=resolved.canonical_id,
            mapping_status=resolved.disposition,
            owner_decision_ref=resolved.decision_ref,
        ))
    return out


def scoped_totals(
    rows: Iterable[ScopedRegistrationFact],
    model_dimensions: Mapping[str, Mapping[str, str | None]],
) -> dict[str, object]:
    """Return conserved raw, canonical model, segment and body totals.

    Unresolved facts remain in explicit unknown buckets. Canonical model totals
    collapse many source groups onto a single target exactly once.
    """
    data = list(rows)
    raw_total = sum(row.registrations for row in data)
    by_model: Counter[str] = Counter()
    by_segment: Counter[str] = Counter()
    by_body: Counter[str] = Counter()
    by_status: Counter[str] = Counter()
    by_period_province_class: Counter[tuple[str, str, str]] = Counter()
    for row in data:
        model_key = row.canonical_model_id or "UNMAPPED"
        by_model[model_key] += row.registrations
        by_status[row.mapping_status] += row.registrations
        by_period_province_class[(row.period, row.province, row.reg_type)] += row.registrations
        dimensions = model_dimensions.get(row.canonical_model_id or "", {})
        by_segment[dimensions.get("segment") or "ไม่ระบุ"] += row.registrations
        by_body[dimensions.get("body_type") or "ไม่ระบุ"] += row.registrations
    if any(sum(counter.values()) != raw_total for counter in (by_model, by_segment, by_body, by_status,
                                                               by_period_province_class)):
        raise AssertionError("Scoped reader totals do not reconcile to raw Ice registrations")
    return {
        "raw_registrations": raw_total,
        "resolved_fact_count": len(data),
        "canonical_model_totals": dict(sorted(by_model.items())),
        "segment_totals": dict(sorted(by_segment.items())),
        "body_type_totals": dict(sorted(by_body.items())),
        "mapping_status_totals": dict(sorted(by_status.items())),
        "period_province_reg_type_totals": [
            {"period": key[0], "province": key[1], "reg_type": key[2], "registrations": value}
            for key, value in sorted(by_period_province_class.items())
        ],
    }
