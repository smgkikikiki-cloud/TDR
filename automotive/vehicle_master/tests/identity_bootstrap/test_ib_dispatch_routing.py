"""The pre-activation dispatch boundary and the generic review signals. Pure, offline, synthetic fixtures: runs everywhere, needs no archived data."""
from __future__ import annotations

import copy

import pytest

from identity_bootstrap.market_activity import classify, load_policy
from identity_bootstrap.routing import CURRENT, current_dispatch, dispatch_all, project, review_flags
from identity_bootstrap.routing import signals

APOL = load_policy()
PERIODS = [f"2568-{m:02d}" for m in range(1, 13)] + [f"2569-{m:02d}" for m in range(1, 10)]
CONFIRMED = {"absent_row": "ABSENT_IS_ZERO", "coverage_guarantee": "contractual completeness", "covered_from": PERIODS[0], "covered_to": PERIODS[-1]}
BUSY = {p: 20.0 for p in PERIODS[:10]}


def create(gid="x-model"):
    return {"subject": {"entity_id": gid}, "outcome": "CREATE_IDENTITY", "primary_reason": "NEW_IDENTITY_CONFIRMED", "reason_codes": ["NEW_IDENTITY_CONFIRMED"],
            "identity": {"canonical_model_id": "x.model"}, "write_plan": {"apply_mode": "PROPOSE", "operations": []}}


def lane(state, **kw):
    return project(create(), state, **kw)["lane"]


@pytest.mark.parametrize("state,expected", [("ACTIVE", "CURRENT_DISCOVERY"), ("DECLINING", "CURRENT_DISCOVERY"), ("REACTIVATED", "CURRENT_DISCOVERY"),
                                            ("INACTIVE_INFERRED", "HISTORICAL_INACTIVE"), ("UNKNOWN", "ACTIVITY_UNCLASSIFIED"), (None, "ACTIVITY_UNCLASSIFIED"), ("SOMETHING_NEW", "ACTIVITY_UNCLASSIFIED")])
def test_the_lane_follows_the_activity_state_and_unknown_never_defaults_to_current(state, expected):
    assert lane(state) == expected


@pytest.mark.parametrize("outcome", ["IDENTITY_REVIEW", "HOLD"])
def test_only_a_create_is_ever_dispatched(outcome):
    d = create()
    d["outcome"] = outcome
    assert project(d, "ACTIVE")["lane"] == "NOT_DISPATCHED"


def test_a_mandatory_owner_review_keeps_a_create_out_of_every_activity_lane():
    review = {"flags": ["POSSIBLE_EXISTING_IDENTITY_CROSS_BRAND"], "mandatory_owner_review": True}
    for state in ("ACTIVE", "DECLINING", "REACTIVATED", "UNKNOWN", "INACTIVE_INFERRED", None):
        assert lane(state, review=review) == "OWNER_REVIEW"
    advisory = {"flags": ["LEGACY_R6_STRONG_PROPOSAL"], "mandatory_owner_review": False}
    assert lane("ACTIVE", review=advisory) == "CURRENT_DISCOVERY", "an advisory hint informs the owner but does not block"


def test_the_projection_never_changes_a_decision_or_its_write_plan():
    decisions = [create("a"), create("b"), {**create("c"), "outcome": "HOLD", "write_plan": None, "identity": None}]
    before = copy.deepcopy(decisions)
    out = dispatch_all(decisions, {"a": "ACTIVE", "b": "INACTIVE_INFERRED"}, {"b": {"flags": [], "mandatory_owner_review": False}})
    assert decisions == before
    assert [r["lane"] for r in out] == ["CURRENT_DISCOVERY", "HISTORICAL_INACTIVE", "NOT_DISPATCHED"]
    assert all(r["bootstrap_outcome"] == d["outcome"] for r, d in zip(out, decisions))


def test_unknown_and_inactive_cannot_reach_the_current_dispatch_output():
    ds = [create(f"g{i}") for i in range(6)]
    states = {"g0": "ACTIVE", "g1": "UNKNOWN", "g2": "INACTIVE_INFERRED", "g3": "REACTIVATED", "g4": "DECLINING"}        # g5 has no state at all
    cur = current_dispatch(dispatch_all(ds, states, {}))
    assert [r["external_id"] for r in cur] == ["g0", "g3", "g4"]
    assert all(r["lane"] == CURRENT for r in cur)


# ---- end to end from a monthly series (the synthetic sequences the QA asked for)
def route(counts, cap, **kw):
    out = classify(counts, PERIODS, cap, APOL, **kw)
    return out["state"], project(create(), out["state"])["lane"]


def test_confirmed_four_zero_sequence_goes_to_the_historical_lane():
    assert route(BUSY, CONFIRMED) == ("INACTIVE_INFERRED", "HISTORICAL_INACTIVE")


def test_unconfirmed_missing_rows_are_unknown_and_unclassified():
    assert route(BUSY, {"absent_row": "UNKNOWN"}) == ("UNKNOWN", "ACTIVITY_UNCLASSIFIED")
    assert route(BUSY, None) == ("UNKNOWN", "ACTIVITY_UNCLASSIFIED")


def test_sporadic_trickles_do_not_reactivate():
    trickle = {**BUSY, PERIODS[14]: 1.0, PERIODS[17]: 2.0, PERIODS[20]: 1.0}      # four zero months first, then single units
    assert route(trickle, CONFIRMED) == ("INACTIVE_INFERRED", "HISTORICAL_INACTIVE")


def test_sustained_activity_and_authoritative_relaunch_return_to_the_current_lane():
    sustained = {**BUSY, **{p: 9.0 for p in PERIODS[15:]}}
    assert route(sustained, CONFIRMED) == ("REACTIVATED", "CURRENT_DISCOVERY")
    one_unit = {**BUSY, PERIODS[14]: 1.0}
    assert route(one_unit, CONFIRMED)[0] == "INACTIVE_INFERRED"
    assert route(one_unit, CONFIRMED, relaunch_evidence=True) == ("REACTIVATED", "CURRENT_DISCOVERY")


def test_an_incomplete_trailing_month_can_never_supply_a_true_zero():
    four_zero = {p: 20.0 for p in PERIODS[:-4]}
    assert classify(four_zero, PERIODS, CONFIRMED, APOL, complete_through=PERIODS[-1])["state"] == "INACTIVE_INFERRED"
    # the last month is not complete yet: only three complete zero months remain, and the unfinished month is unknown, not zero
    out = classify(four_zero, PERIODS, CONFIRMED, APOL, complete_through=PERIODS[-2])
    assert out["state"] != "INACTIVE_INFERRED" and out["unknown_months_in_trailing_window"] == 1
    assert out["lane"] != "HISTORICAL_INACTIVE"
    # several incomplete months do not help either
    assert classify(four_zero, PERIODS, CONFIRMED, APOL, complete_through=PERIODS[-4])["state"] != "INACTIVE_INFERRED"


def test_a_registration_in_an_incomplete_month_still_shows_activity_but_never_inactivity():
    c = {**{p: 20.0 for p in PERIODS[:-4]}, PERIODS[-1]: 8.0}
    out = classify(c, PERIODS, CONFIRMED, APOL, complete_through=PERIODS[-2])
    assert out["state"] in ("ACTIVE", "DECLINING", "REACTIVATED")


# ---- generic review signals: invented names only, nothing about any real marque
def catalog():
    return {"brands": {"acme": {"name_en": "ACME"}}, "identities": [{"canonical_id": "acme.acme_zork_7", "brand_id": "acme", "name_en": "ACME Zork 7"},
                                                                    {"canonical_id": "acme.acme_roadster", "brand_id": "acme", "name_en": "ACME Roadster"}], "aliases": {"acme.acme_zork_7": ["zork 7"]}}


def subject(gid, status="settled", brand="ACME", relations=()):
    return {"entity_id": gid, "identity_status": status, "relations": list(relations),
            "brand": {"raw": brand, "brand_id": "acme", "relation": "EXACT", "spellings": [brand, "ACME", "acme"]}}


def test_a_provider_id_label_found_inside_an_existing_identity_is_a_mandatory_cross_brand_review():
    subs = [subject("zork-model-9"), subject("acme-roadster-2"), subject("zork-model-5", status="unmapped_name")]
    flags = review_flags(subs, catalog(), {}, ["zork-model-9", "acme-roadster-2"])
    assert flags["zork-model-9"]["flags"] == ["POSSIBLE_EXISTING_IDENTITY_CROSS_BRAND"] and flags["zork-model-9"]["mandatory_owner_review"] is True
    assert flags["zork-model-9"]["evidence"][0]["existing_identities"] == ["acme.acme_zork_7"]
    assert flags["acme-roadster-2"]["flags"] == [] and not flags["acme-roadster-2"]["mandatory_owner_review"], "the id prefix is the brand itself"
    assert signals.provider_id_label_evidence(subs, catalog(), signals.load_policy()).keys() == {"zork-model-9"}, "unsettled ids are never evidence"


def test_short_labels_and_labels_absent_from_existing_names_raise_nothing():
    subs = [subject("zk-model"), subject("bolt-model")]
    assert signals.provider_id_label_evidence(subs, catalog(), signals.load_policy()) == {}


def test_a_sibling_that_is_already_an_existing_identity_is_attached_as_evidence():
    sib = subject("zork-model-9", relations=[{"peer_kind": "SUBJECT", "peer_id": "zork-model-8", "name_relation": "SIBLING"}])
    peer = subject("zork-model-8", relations=[{"peer_kind": "TARGET", "peer_id": "acme.acme_zork_7", "name_relation": "EQUAL"}])
    ev = signals.sibling_mapped_evidence([sib, peer])
    assert ev["zork-model-9"][0]["existing_identity"] == "acme.acme_zork_7" and "zork-model-8" not in ev, "the mapped subject needs no warning"
    # the relation is stored once, from the smaller id: the candidate must get the evidence from either end
    mapped_first = subject("zork-model-1", relations=[{"peer_kind": "SUBJECT", "peer_id": "zork-model-9", "name_relation": "SIBLING"}, {"peer_kind": "TARGET", "peer_id": "acme.acme_zork_7", "name_relation": "EQUAL"}])
    assert signals.sibling_mapped_evidence([mapped_first, subject("zork-model-9")])["zork-model-9"][0]["sibling"] == "zork-model-1"


def test_legacy_r6_hints_are_advisory_and_thresholded():
    flags = review_flags([subject("acme-roadster-2")], catalog(), {"acme-roadster-2": [["acme.acme_roadster", "PROPOSED", "NAME", 0.61], ["acme.acme_zork_7", "PROPOSED", "NAME", 0.3]]}, ["acme-roadster-2"])
    f = flags["acme-roadster-2"]
    assert f["flags"] == ["LEGACY_R6_STRONG_PROPOSAL"] and f["mandatory_owner_review"] is False and len(f["evidence"]) == 1


def test_the_routing_layer_names_no_brand_or_model():
    from pathlib import Path
    root = Path(signals.__file__).parent
    text = "".join(p.read_text(encoding="utf-8").casefold() for p in root.glob("*") if p.suffix in (".py", ".yaml"))
    for needle in ("maxus", "mifa", "mg.", "honda", "toyota", "mazda", "jazz"):
        assert needle not in text, needle


# ---- an EXPLICIT zero row in an incomplete month is not a qualifying zero either
def test_an_explicit_zero_row_in_an_incomplete_month_cannot_establish_a_true_zero_streak():
    explicit = {**{p: 20.0 for p in PERIODS[:-4]}, **{p: 0.0 for p in PERIODS[-4:]}}        # four EXPLICIT zero rows, no capability needed
    full = classify(explicit, PERIODS, {"absent_row": "UNKNOWN"}, APOL, complete_through=PERIODS[-1])
    assert full["state"] == "INACTIVE_INFERRED", "four explicit zeros in complete months are true zeros"
    partial = classify(explicit, PERIODS, {"absent_row": "UNKNOWN"}, APOL, complete_through=PERIODS[-2])
    assert partial["state"] != "INACTIVE_INFERRED" and partial["unknown_months_in_trailing_window"] == 1
    assert partial["trailing_months"][PERIODS[-1]] is None, "the unfinished month's explicit zero is unknown, not zero"
    assert project(create(), partial["state"])["lane"] != "HISTORICAL_INACTIVE"
    # also when the unfinished tail is longer, and under a confirmed capability
    assert classify(explicit, PERIODS, CONFIRMED, APOL, complete_through=PERIODS[-3])["state"] != "INACTIVE_INFERRED"
    assert classify(explicit, PERIODS, CONFIRMED, APOL, complete_through=PERIODS[-1])["state"] == "INACTIVE_INFERRED"


def test_a_positive_count_in_an_incomplete_month_is_still_activity_and_a_complete_explicit_zero_is_unchanged():
    c = {**{p: 20.0 for p in PERIODS[:-4]}, **{p: 0.0 for p in PERIODS[-4:-1]}, PERIODS[-1]: 6.0}
    out = classify(c, PERIODS, CONFIRMED, APOL, complete_through=PERIODS[-2])
    assert out["state"] in ("ACTIVE", "DECLINING", "REACTIVATED") and out["trailing_months"][PERIODS[-1]] == 6.0
    from identity_bootstrap.market_activity import resolve_series
    assert resolve_series({PERIODS[0]: 0.0}, PERIODS[:2], None, APOL, complete_through=PERIODS[0])[0] == 0.0


# ---- the current-discovery lane is a projection, never an authorization
def test_no_dispatch_record_is_ever_an_activation_authorization():
    ds = [create(f"g{i}") for i in range(4)]
    out = dispatch_all(ds, {"g0": "ACTIVE", "g1": "REACTIVATED", "g2": "UNKNOWN", "g3": "DECLINING"}, {})
    assert any(r["lane"] == "CURRENT_DISCOVERY" for r in out)
    for r in out:
        assert r["activation_authorized"] is False
        assert r["activation_blockers"] == ["IR_PARITY_UNRESOLVED", "OWNER_APPROVAL_PENDING", "GOVERNED_WRITER_NOT_BUILT"]
    for r in current_dispatch(out):
        assert r["activation_authorized"] is False and "OWNER_APPROVAL_PENDING" in r["activation_blockers"]
    # even a resolved parity cannot authorize: owner approval and the governed writer are still outstanding
    r = project(create(), "ACTIVE", parity_status="IR_PARITY_RESOLVED")
    assert r["activation_authorized"] is False and r["activation_blockers"] == ["OWNER_APPROVAL_PENDING", "GOVERNED_WRITER_NOT_BUILT"]


def test_no_code_path_sets_activation_authorized_true():
    from pathlib import Path
    root = Path(signals.__file__).parent.parent
    for f in root.rglob("*.py"):
        text = f.read_text(encoding="utf-8")
        assert '"activation_authorized": True' not in text and "activation_authorized=True" not in text and "activation_authorized'] = True" not in text, f
