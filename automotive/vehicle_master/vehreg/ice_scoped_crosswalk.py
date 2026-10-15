"""Pure read-only Ice group/registration-type → canonical identity resolver.

R6 v2 OFFLINE CONTRACT ONLY. This module never accesses Supabase or writes data.
Approvals MUST come from frozen, provenanced owner decisions, not a fuzzy matcher.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import re
from typing import Iterable

_OWNER_ACTIONS = frozenset({"APPROVED", "EXCLUDED", "PENDING"})
_ACTIVE_LEGACY = frozenset({"AUTO", "APPROVED"})


def normalize_reg_type(value: str) -> str:
    """Normalize native DLT reg types; RY2 is never silently converted to RY1."""
    raw = value.strip()
    if raw.upper() == "ALL":
        return "ALL"
    match = re.fullmatch(r"(?:RY|รย\.)\s*([0-9]+)", raw, re.IGNORECASE)
    if not match:
        raise ValueError(f"Invalid registration type: {value!r}; expected รย.N/RYN or ALL")
    return f"รย.{int(match.group(1))}"


@dataclass(frozen=True)
class OwnerScope:
    group_id: str
    reg_type: str  # Specific รย.N or ALL fallback
    action: str    # APPROVED, EXCLUDED, PENDING
    canonical_id: str | None
    decision_ref: str
    master_version: str


@dataclass(frozen=True)
class LegacyLink:
    group_id: str
    canonical_id: str
    status: str


@dataclass(frozen=True)
class IceFact:
    group_id: str
    reg_type: str
    registrations: int


@dataclass(frozen=True)
class ResolvedFact:
    group_id: str
    reg_type: str
    registrations: int
    canonical_id: str | None
    disposition: str
    decision_ref: str | None


class ScopedCrosswalk:
    """Owner-first deterministic resolver; one canonical may serve many Ice groups.

    Exact source+registration class wins over ALL. Scoped-only pickup groups
    cannot fall back to a legacy parent/ALL when one class is unresolved.
    """

    def __init__(
        self,
        owner: Iterable[OwnerScope],
        legacy: Iterable[LegacyLink],
        materialized_canonical_ids: Iterable[str],
        master_version: str,
        scoped_only_groups: Iterable[str] = (),
    ) -> None:
        if not master_version:
            raise ValueError("master_version is required")
        self.materialized = frozenset(materialized_canonical_ids)
        self.master_version = master_version
        self.scoped_only_groups = frozenset(scoped_only_groups)
        self.owner: dict[tuple[str, str], OwnerScope] = {}
        for row in owner:
            scope = normalize_reg_type(row.reg_type)
            if not row.group_id or not row.decision_ref:
                raise ValueError("Owner decisions need Ice group ID and audit decision_ref")
            if row.master_version != master_version:
                raise ValueError(
                    f"Owner decision for {row.group_id} belongs to {row.master_version}, not {master_version}"
                )
            if row.action not in _OWNER_ACTIONS:
                raise ValueError(f"Unknown owner action: {row.action}")
            if row.action == "APPROVED" and not row.canonical_id:
                raise ValueError("APPROVED requires canonical ID")
            if row.action == "EXCLUDED" and row.canonical_id:
                raise ValueError("EXCLUDED must not silently carry a canonical target")
            key = (row.group_id, scope)
            if key in self.owner:
                raise ValueError(f"Conflicting/duplicate owner decision for {key}")
            self.owner[key] = row
        grouped: dict[str, set[str]] = defaultdict(set)
        for row in legacy:
            if row.status in _ACTIVE_LEGACY and row.canonical_id:
                grouped[row.group_id].add(row.canonical_id)
        self.legacy = grouped

    def resolve(self, fact: IceFact) -> ResolvedFact:
        reg_type = normalize_reg_type(fact.reg_type)
        if reg_type == "ALL":
            raise ValueError("Ice fact requires a concrete registration class, not ALL")
        if not fact.group_id or fact.registrations < 0:
            raise ValueError("Ice fact needs a group ID and nonnegative registrations")
        exact = self.owner.get((fact.group_id, reg_type))
        decision = exact or (
            None if fact.group_id in self.scoped_only_groups
            else self.owner.get((fact.group_id, "ALL"))
        )
        if decision:
            if decision.action == "EXCLUDED":
                return ResolvedFact(fact.group_id, reg_type, fact.registrations, None,
                                    "OWNER_EXCLUDED", decision.decision_ref)
            if decision.action == "PENDING":
                return ResolvedFact(fact.group_id, reg_type, fact.registrations, None,
                                    "OWNER_PENDING", decision.decision_ref)
            if decision.canonical_id not in self.materialized:
                return ResolvedFact(fact.group_id, reg_type, fact.registrations, None,
                                    "PENDING_MATERIALIZATION", decision.decision_ref)
            return ResolvedFact(fact.group_id, reg_type, fact.registrations,
                                decision.canonical_id, "OWNER_APPROVED", decision.decision_ref)
        if fact.group_id in self.scoped_only_groups:
            return ResolvedFact(fact.group_id, reg_type, fact.registrations, None,
                                "SCOPED_CLASS_UNRESOLVED", None)
        candidates = self.legacy.get(fact.group_id, set())
        if len(candidates) > 1:
            return ResolvedFact(fact.group_id, reg_type, fact.registrations, None,
                                "AMBIGUOUS_LEGACY_ACTIVE", None)
        if len(candidates) == 1:
            canonical_id = next(iter(candidates))
            if canonical_id not in self.materialized:
                return ResolvedFact(fact.group_id, reg_type, fact.registrations, None,
                                    "LEGACY_TARGET_MISSING", None)
            return ResolvedFact(fact.group_id, reg_type, fact.registrations,
                                canonical_id, "LEGACY_ACTIVE", None)
        return ResolvedFact(fact.group_id, reg_type, fact.registrations, None,
                            "UNMATCHED", None)

    def resolve_all(self, facts: Iterable[IceFact]) -> list[ResolvedFact]:
        seen: set[tuple[str, str]] = set()
        results: list[ResolvedFact] = []
        for fact in facts:
            key = (fact.group_id, normalize_reg_type(fact.reg_type))
            if key in seen:
                raise ValueError(
                    f"Duplicate Ice aggregate grain {key}: aggregate periods/provinces first"
                )
            seen.add(key)
            results.append(self.resolve(fact))
        return results


def summarize(rows: Iterable[ResolvedFact]) -> dict[str, object]:
    """Never silently shrink the fixed registration denominator."""
    data = list(rows)
    fixed = sum(x.registrations for x in data)
    excluded = sum(x.registrations for x in data if x.disposition == "OWNER_EXCLUDED")
    covered = sum(x.registrations for x in data if x.canonical_id is not None)
    return {
        "fixed_denominator": fixed,
        "owner_excluded_units": excluded,
        "adjusted_denominator": fixed - excluded,
        "approved_or_legacy_active_covered_units": covered,
        "fixed_denominator_coverage_pct": 100 * covered / fixed if fixed else 0.0,
        "by_disposition_rows": dict(Counter(x.disposition for x in data)),
        "by_disposition_units": {
            status: sum(x.registrations for x in data if x.disposition == status)
            for status in {x.disposition for x in data}
        },
    }
