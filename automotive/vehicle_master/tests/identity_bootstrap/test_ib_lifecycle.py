"""The lifecycle separates identity existence from completeness and from publication; Bootstrap owns exactly one act of it."""
from __future__ import annotations

import itertools

import ib_reference as R
import ib_support as S

LC = S.lifecycle()
STATES = set(LC["identity_states"])
PAIRS = [tuple(p) for p in LC["allowed_state_pairs"]]
ACTORS = LC["actors"]


def test_states_and_pairs_are_defined_once():
    assert set(LC["identity_states"]) == {"DISCOVERED", "ENRICHING", "VERIFIED", "PUBLISHED", "WITHDRAWN"}
    assert set(LC["enrichment_states"]) == {"PENDING", "IN_PROGRESS", "COMPLETE", "BLOCKED"}
    assert len(PAIRS) == len(set(PAIRS))
    for state, enrichment in PAIRS:
        assert state in STATES and enrichment in LC["enrichment_states"]
    assert tuple(LC["initial_state"].values()) in PAIRS
    assert tuple(LC["legacy_backfill_state"]) in PAIRS


def test_every_transition_goes_between_legal_pairs_by_known_actors():
    for t in LC["transitions"]:
        assert set(t["actors"]) <= set(ACTORS), t["id"]
        assert set(t.get("proposal_for", [])) <= set(t["actors"]), t["id"]
        if t["to"][1] is not None:
            assert tuple(t["to"]) in PAIRS, t["id"]
        frm = t["from"] if "from" in t else None
        if frm:
            assert tuple(frm) in PAIRS, t["id"]
        for field in t["writes"]:
            assert field in {"canonical_id", "brand_id", "slug", "name_en", "identity_state", "enrichment_state"}, f"{t['id']} would write {field}: enrichment attributes are not lifecycle writes"


def test_bootstrap_performs_exactly_one_lifecycle_act():
    by_bootstrap = [t["id"] for t in LC["transitions"] if "BOOTSTRAP" in t["actors"]]
    assert by_bootstrap == ["CREATE"]
    create = next(t for t in LC["transitions"] if t["id"] == "CREATE")
    assert create["from"] is None and create["to"] == ["DISCOVERED", "PENDING"] and create["emits"] == "VEHICLE_IDENTITY_CREATED"
    assert set(create["writes"]) == set(S.policy()["writes"]["shell_columns"])
    assert [t["id"] for t in LC["transitions"] if t.get("emits")] == ["CREATE"]


def test_the_consumer_catalog_sees_only_published_identities():
    v = LC["visibility"]
    assert v["consumer_catalog"] == ["PUBLISHED"] and v["public_links"] == ["PUBLISHED"]
    for surface, states in v.items():
        assert set(states) <= STATES, surface
    assert "DISCOVERED" in v["internal_market_engine"] and "DISCOVERED" in v["external_crosswalk_target"]
    assert "WITHDRAWN" not in v["internal_market_engine"] and "WITHDRAWN" not in v["external_crosswalk_target"] and "WITHDRAWN" not in v["identity_resolution_pool"]
    assert set(v["enrichment_queue"]) == {"DISCOVERED", "ENRICHING"}
    assert "WITHDRAWN" in v["backup_export"], "withdrawn rows keep their ids reserved, so they stay in the export"


def test_publication_is_unreachable_without_passing_verified():
    edges = {}
    for t in LC["transitions"]:
        if t["id"] == "CREATE":
            continue
        starts = [t["from"][0]] if "from" in t else t["from_states"]
        for s in starts:
            edges.setdefault(s, set()).add(t["to"][0])

    def reach(blocked=()):
        seen, stack = set(), ["DISCOVERED"]
        while stack:
            s = stack.pop()
            if s in seen or s in blocked:
                continue
            seen.add(s)
            stack += edges.get(s, ())
        return seen

    assert "PUBLISHED" in reach()
    assert "PUBLISHED" not in reach(blocked={"VERIFIED"})
    assert "VERIFIED" not in reach(blocked={"ENRICHING"}), "verification requires an enrichment pass"


def test_forbidden_transitions_are_refused_for_every_actor_and_pair():
    for forbidden in LC["forbidden_transitions"]:
        for actor in ACTORS:
            for a, b in itertools.product([p for p in PAIRS if p[0] == forbidden["from"]], [p for p in PAIRS if p[0] == forbidden["to"]]):
                assert R.transition(LC, list(a), list(b), actor)["allowed"] is False, (forbidden, actor, a, b)


def test_only_admin_can_publish_and_nobody_can_publish_unverified():
    for actor in ACTORS:
        for frm in (p for p in PAIRS if p[0] != "VERIFIED"):
            assert R.transition(LC, list(frm), ["PUBLISHED", "COMPLETE"], actor)["allowed"] is False
    assert [a for a in ACTORS if R.transition(LC, ["VERIFIED", "COMPLETE"], ["PUBLISHED", "COMPLETE"], a)["allowed"]] == ["ADMIN"]


def test_every_state_pair_request_has_a_deterministic_answer():
    for frm, to, actor in itertools.product([None, *PAIRS], PAIRS, ACTORS):
        answer = R.transition(LC, list(frm) if frm else None, list(to), actor)
        assert isinstance(answer["allowed"], bool)
        if frm is None and answer["allowed"]:
            assert tuple(to) == tuple(LC["initial_state"].values()) and actor in ("BOOTSTRAP", "ADMIN")
