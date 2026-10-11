"""Market-activity routing: a classification step beside Bootstrap, never evidence for existence and never a Bootstrap input."""
from __future__ import annotations

from pathlib import Path

import pytest

from identity_bootstrap.market_activity import STATES, classify, load_policy
from identity_bootstrap.shadow import activity_report, run as shadow_run

POL = load_policy()
PERIODS = [f"2568-{m:02d}" for m in range(1, 13)] + [f"2569-{m:02d}" for m in range(1, 10)]     # 21 months
CONFIRMED = {"absent_row": "ABSENT_IS_ZERO", "coverage_guarantee": "contractual monthly completeness", "covered_from": PERIODS[0], "covered_to": PERIODS[-1]}
UNCONFIRMED = {"absent_row": "UNKNOWN"}
BUSY = {p: 20.0 for p in PERIODS[:10]}                       # meaningful prior activity, then silence


def st(counts, cap, **kw):
    return classify(counts, PERIODS, cap, POL, **kw)["state"]


def test_states_are_the_five_required_ones():
    assert STATES == ("ACTIVE", "DECLINING", "INACTIVE_INFERRED", "REACTIVATED", "UNKNOWN")
    assert set(POL["lanes"]) == set(STATES)


def test_missing_rows_are_unknown_until_absent_is_zero_is_confirmed():
    assert st(BUSY, UNCONFIRMED) == "UNKNOWN"
    assert st(BUSY, None) == "UNKNOWN"
    assert st(BUSY, CONFIRMED) == "INACTIVE_INFERRED"


@pytest.mark.parametrize("cap", [
    {"absent_row": "ABSENT_IS_ZERO", "covered_from": PERIODS[0], "covered_to": PERIODS[-1]},                                               # no named guarantee
    {"absent_row": "ABSENT_IS_ZERO", "coverage_guarantee": "x", "covered_from": PERIODS[0], "covered_to": "2568-12"},                      # does not cover the tail
    {"absent_row": "REGISTERED_COMBINATIONS_ONLY", "coverage_guarantee": "x", "covered_from": PERIODS[0], "covered_to": PERIODS[-1]},
])
def test_a_zero_needs_the_named_guarantee_over_the_covered_period(cap):
    assert st(BUSY, cap) == "UNKNOWN"


def test_the_streak_is_exactly_four_true_zeros():
    shorter = {**BUSY, **{p: 20.0 for p in PERIODS[10:]}}
    shorter.pop(PERIODS[-1])                                     # 1 zero month only
    assert st(shorter, CONFIRMED) == "ACTIVE"
    three = {p: 20.0 for p in PERIODS[:-3]}                       # exactly three trailing zeros
    assert st(three, CONFIRMED) != "INACTIVE_INFERRED"
    four = {p: 20.0 for p in PERIODS[:-4]}
    assert st(four, CONFIRMED) == "INACTIVE_INFERRED"


def test_a_unknown_month_breaks_the_streak():
    c = {p: 20.0 for p in PERIODS[:-4]}
    cap = {**CONFIRMED, "covered_from": PERIODS[-3]}             # first trailing month falls outside the guarantee
    assert st(c, cap) == "UNKNOWN"


def test_meaningful_prior_activity_is_required():
    assert st({PERIODS[0]: 2.0}, CONFIRMED) == "UNKNOWN"
    assert "INSUFFICIENT_PRIOR_ACTIVITY" in classify({PERIODS[0]: 2.0}, PERIODS, CONFIRMED, POL)["reason"]


def test_sporadic_registrations_do_not_reactivate():
    c = {**{p: 20.0 for p in PERIODS[:8]}, PERIODS[12]: 1.0, PERIODS[15]: 2.0, PERIODS[18]: 1.0, PERIODS[20]: 1.0}
    out = classify(c, PERIODS, CONFIRMED, POL)
    assert out["state"] == "INACTIVE_INFERRED" and out["reactivated_at"] is None


def test_sustained_activity_reactivates_and_later_stays_reported_for_the_window():
    c = {**{p: 20.0 for p in PERIODS[:8]}, **{p: 8.0 for p in PERIODS[14:]}}
    out = classify(c, PERIODS, CONFIRMED, POL)
    assert out["state"] == "REACTIVATED" and out["reactivated_at"] == PERIODS[16]
    short = {**{p: 20.0 for p in PERIODS[:8]}, PERIODS[14]: 8.0, PERIODS[15]: 8.0}      # only two strong months, then silence again
    assert st(short, CONFIRMED) == "INACTIVE_INFERRED"


def test_authoritative_relaunch_evidence_reactivates():
    c = {**{p: 20.0 for p in PERIODS[:8]}, PERIODS[14]: 1.0}
    assert st(c, CONFIRMED) == "INACTIVE_INFERRED"
    assert st(c, CONFIRMED, relaunch_evidence=True) == "REACTIVATED"


def test_decline_needs_a_fully_known_window():
    falling = {**{p: 40.0 for p in PERIODS[:-3]}, **{p: 6.0 for p in PERIODS[-3:]}}
    assert st(falling, CONFIRMED) == "DECLINING"
    assert st(falling, UNCONFIRMED) == "ACTIVE" or st(falling, UNCONFIRMED) == "DECLINING"     # unknowns elsewhere may block; never INACTIVE
    assert st(falling, UNCONFIRMED) != "INACTIVE_INFERRED"


def test_classification_is_a_pure_function_of_monthly_counts():
    a = classify(BUSY, PERIODS, CONFIRMED, POL)
    b = classify(dict(reversed(list(BUSY.items()))), PERIODS, CONFIRMED, POL)
    assert a == b


def test_no_model_is_hardcoded_in_policy_or_code():
    here = Path(activity_report.__file__).parent.parent / "market_activity"
    text = (here / "policy.yaml").read_text(encoding="utf-8") + (here / "classify.py").read_text(encoding="utf-8")
    for g in activity_report.REPRESENTATIVE + ["sienta", "jazz", "vios", "march"]:
        assert g not in text.lower()


def test_bootstrap_never_imports_or_reads_market_activity_or_the_routing_layer():
    import re
    root = Path(activity_report.__file__).parent.parent
    pattern = re.compile(r"market_activity|identity_bootstrap\.routing|from\s+\.+routing|import\s+routing")
    for sub in ("engine", "providers", "contract"):
        for f in (root / sub).rglob("*"):
            if f.is_file() and f.suffix in (".py", ".yaml", ".json", ".md"):
                assert not pattern.search(f.read_text(encoding="utf-8")), f


@pytest.fixture(scope="module")
def real():
    if not shadow_run.DEFAULT_PACKAGE.exists():
        pytest.skip("pinned Ice package not in this checkout")
    from identity_bootstrap.shadow import ir_rev4
    a = shadow_run.run("A", ir=ir_rev4.load())
    return a, activity_report.build(a)


def test_real_package_has_no_explicit_zero_rows_so_nothing_can_be_inactive_today(real):
    a, s = real
    assert all(v > 0 for m in a["package"]["monthly"].values() for v in m.values())
    assert s["create_candidates"] == 73
    assert "INACTIVE_INFERRED" not in s["actual"]["states"]
    assert sum(s["actual"]["states"].values()) == 73
    assert s["actual"]["states"].get("UNKNOWN", 0) == 63 and s["actual"]["lanes"].get("HISTORICAL_INACTIVE", 0) == 0


def test_the_what_if_is_labelled_non_authoritative_and_split_is_reported(real):
    _, s = real
    assert "NOT AUTHORITATIVE" in s["what_if_absent_is_zero"]["scenario"]
    assert s["what_if_absent_is_zero"]["states"].get("INACTIVE_INFERRED", 0) == 23
    assert sum(s["what_if_absent_is_zero"]["states"].values()) == 73


def test_routing_leaves_every_bootstrap_decision_unchanged(real):
    a, s = real
    import collections
    before = [(d["subject"]["entity_id"], d["outcome"], tuple(d["reason_codes"])) for d in a["decisions"]]
    activity_report.build(a)
    assert before == [(d["subject"]["entity_id"], d["outcome"], tuple(d["reason_codes"])) for d in a["decisions"]]
    assert collections.Counter(o for _, o, _ in before) == {"CREATE_IDENTITY": 73, "IDENTITY_REVIEW": 89, "HOLD": 1038}
