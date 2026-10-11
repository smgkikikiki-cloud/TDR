"""Pure classifier. Input: a monthly series (period -> registrations, or absent), the complete observed periods, the provider's absent-row capability."""
from __future__ import annotations

from pathlib import Path

import yaml

STATES = ("ACTIVE", "DECLINING", "INACTIVE_INFERRED", "REACTIVATED", "UNKNOWN")
POLICY_FILE = Path(__file__).with_name("policy.yaml")


def load_policy(path: Path = POLICY_FILE) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def absent_is_zero(capability: dict | None, period: str, policy: dict) -> bool:
    """True only for a guaranteed zero: confirmed capability value + named coverage guarantee + period inside the covered range."""
    c = capability or {}
    if c.get("absent_row") != policy["absent_row"]["confirming_value"] or not c.get("coverage_guarantee"):
        return False
    return c.get("covered_from", "") <= period <= c.get("covered_to", "")


def resolve_series(counts: dict[str, float], periods: list[str], capability: dict | None, policy: dict, complete_through: str | None = None) -> list[float | None]:
    """One value per observed period: the registered count, a TRUE zero (guaranteed), or None (unknown).

    `complete_through` is the last period the provider has finished publishing. A later (incomplete) period can never supply a true zero: an unfinished month is
    unknown whatever the capability says, and that holds for an EXPLICIT zero row as much as for a missing one: an unfinished month never contributes a qualifying zero.
    A positive count in an incomplete month is still a registration (it can only show activity, never inactivity)."""
    out: list[float | None] = []
    for p in periods:
        incomplete = complete_through is not None and p > complete_through
        if p in counts:
            v = float(counts[p])
            out.append(None if incomplete and v == 0 else v)
        else:
            out.append(0.0 if absent_is_zero(capability, p, policy) and not incomplete else None)
    return out


def classify(counts: dict[str, float], periods: list[str], capability: dict | None = None, policy: dict | None = None, relaunch_evidence: bool = False,
             complete_through: str | None = None) -> dict:
    pol = policy or load_policy()
    series = resolve_series(counts, periods, capability, pol, complete_through)
    n, streak_need = len(series), pol["zero_streak_months"]
    streak = sust = 0
    cum_total, cum_active = 0.0, 0
    inactive_since = reactivated_at = None
    inactive = False
    for i, v in enumerate(series):
        if v is None:                                   # unknown: breaks both runs, can neither start nor end inactivity
            streak = sust = 0
            continue
        if v == 0:
            streak += 1
            sust = 0
            if streak >= streak_need and not inactive and cum_total >= pol["min_prior_total"] and cum_active >= pol["min_prior_active_months"]:
                inactive, inactive_since, reactivated_at = True, periods[i - streak_need + 1], None
            continue
        streak = 0
        if inactive:
            sust = sust + 1 if v >= pol["reactivation_monthly_min"] else 0
            if sust >= pol["reactivation_sustained_months"]:
                inactive, reactivated_at, sust = False, periods[i], 0
        cum_total += v
        cum_active += 1
    tail = series[-streak_need:]
    unknown_tail = sum(v is None for v in tail)
    base = {"inactive_since": inactive_since, "reactivated_at": reactivated_at, "trailing_months": dict(zip(periods[-streak_need:], tail)),
            "zero_streak_now": streak, "unknown_months_in_trailing_window": unknown_tail}

    def done(state: str, reason: str) -> dict:
        return {"state": state, "reason": reason, "lane": pol["lanes"][state], **base}

    if inactive and relaunch_evidence:
        return done("REACTIVATED", "authoritative relaunch evidence overrides the inferred-inactive spell")
    if inactive:
        return done("INACTIVE_INFERRED", f"true-zero streak of {streak_need}+ months since {inactive_since} after meaningful prior activity; no sustained reactivation")
    if reactivated_at is not None and periods.index(reactivated_at) >= n - pol["reactivated_window_months"]:
        return done("REACTIVATED", "sustained activity (or relaunch evidence) after an inferred-inactive spell")
    if any(v is not None and v >= pol["active_monthly_min"] for v in tail):
        rec, basel = pol["decline_recent_months"], pol["decline_baseline_months"]
        win = series[-(rec + basel):]
        if len(win) == rec + basel and all(v is not None for v in win):
            r_mean, b_mean = sum(win[-rec:]) / rec, sum(win[:basel]) / basel
            if b_mean > 0 and r_mean <= pol["decline_ratio"] * b_mean:
                return done("DECLINING", f"recent {rec}-month mean {r_mean:.1f} <= {pol['decline_ratio']} x baseline {b_mean:.1f}")
            return done("ACTIVE", "active months in the trailing window; no decline")
        return done("ACTIVE", "active months in the trailing window; decline not assessable (unknown months in the window)")
    if unknown_tail:
        return done("UNKNOWN", "ZERO_SEMANTICS_UNCONFIRMED: missing rows in the trailing window are not guaranteed zeros and nothing there reaches the active threshold")
    if cum_total < pol["min_prior_total"] or cum_active < pol["min_prior_active_months"]:
        return done("UNKNOWN", "INSUFFICIENT_PRIOR_ACTIVITY: no meaningful history to infer inactivity from")
    return done("DECLINING", "trickle: trailing months known, below the active threshold, not a full zero streak")
