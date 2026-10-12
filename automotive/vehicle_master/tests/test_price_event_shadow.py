"""PEE-2 tests: the shadow harness itself, and what it measures about PEE-1.

Nothing here uses the network or a model.  The expensive corpus run is done once
per module and shared.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile

import pytest

from vehreg import price_event, price_event_shadow as shadow, price_event_validate
from vehreg.catalog import Catalog, DATA_DIR, DEFAULT_YEAR
from vehreg.price_event_shadow import (
    FIXTURE_DIR,
    NetworkAttempted,
    ShadowFixtureError,
    aggregate,
    estimate_cost,
    evaluate_scenario,
    load_scenarios,
    offline_guard,
    render_artifacts,
    run_corpus,
    run_scenario,
    validate_scenario,
)

ROOT = Path(__file__).resolve().parent.parent
STORED = ROOT / "docs" / "price-intelligence" / "pee2"


@pytest.fixture(scope="module")
def catalog() -> Catalog:
    return Catalog.load(DATA_DIR, DEFAULT_YEAR)


@pytest.fixture(scope="module")
def corpus(catalog) -> dict:
    return run_corpus(FIXTURE_DIR, catalog=catalog)


def _raw(name: str) -> dict:
    return json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _subset(tmp_path: Path, *names: str) -> Path:
    for name in names:
        (tmp_path / f"{name}.json").write_text(
            (FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path


# ------------------------------------------------------------- fixture integrity

def test_seed_corpus_is_honest_about_its_provenance(corpus) -> None:
    scenarios = load_scenarios()
    assert len(scenarios) >= 23
    for scn in scenarios:
        assert scn.provenance["rights"], scn.id
        assert scn.label_status == "PROPOSED_PENDING_OWNER_REVIEW", scn.id
        assert not scn.provenance.get("labelled_by"), scn.id
        assert scn.evidence_kind in {"RECONSTRUCTED_FROM_PILOT_NOTES",
                                     "SYNTHETIC_ADVERSARIAL"}, scn.id
    # Nothing is dressed up as owner-labelled or recorded evidence...
    assert not any("OWNER_LABELLED" in key or "RECORDED_SNAPSHOT" in key
                   for key in corpus["provenance_counts"])
    assert corpus["summary_owner_labelled"] is None
    # ...and the generated report says so before it says anything else.
    report = shadow.render_report_md(corpus)
    assert "Owner-labelled scenarios: 0" in report
    assert report.index("Read this first") < report.index("Fixture provenance") \
        < report.index("Safety counters")


@pytest.mark.parametrize("mutate,expected", [
    (lambda r: r["provenance"].update(label_status="OWNER_LABELLED"), "OWNER_LABELLED requires"),
    (lambda r: r["provenance"].update(labelled_by="x", labelled_at="2026-10-01"),
     "must not carry an owner sign-off"),
    (lambda r: r["provenance"].update(evidence_kind="RECORDED_SNAPSHOT"), "capture.url"),
    (lambda r: r["provenance"].pop("rights"), "provenance.rights"),
    (lambda r: r["provenance"].update(source_refs=[]), "source_refs"),
    (lambda r: r.update(config={"enabled": False}), "not allowed"),
    (lambda r: r.update(observations=r["observations"][:1]), "at least two"),
    (lambda r: r["observations"][0]["expect"].pop("baseline"), "labelled baseline"),
    (lambda r: r["observations"][1].update(t="2026-01-01T00:00:00+07:00"), "strictly increasing"),
    (lambda r: r["observations"][1].update(t="2026-10-06T11:00:00"), "timezone-aware"),
    (lambda r: r["observations"][1]["expect"].update(disposition="MAYBE"), "disposition"),
    (lambda r: r["observations"][1]["expect"].update(event="SOMETIMES"), "expect.event"),
    (lambda r: r.update(known_finding={"id": "X", "summary": "s", "status": "FIXED"}),
     "known_finding"),
    (lambda r: r["observations"][1].update(html="<p/>"), "exactly one of"),
])
def test_fixture_validator_rejects_unsound_scenarios(mutate, expected) -> None:
    raw = deepcopy(_raw("s03_promo_terms_only_change"))
    mutate(raw)
    assert any(expected in problem for problem in validate_scenario(raw)), expected


def test_recorded_snapshot_needs_capture_and_permission_facts() -> None:
    raw = deepcopy(_raw("s01_home_cards_stable"))
    raw["provenance"] = {
        "evidence_kind": "RECORDED_SNAPSHOT", "rights": "owner-approved capture",
        "label_status": "OWNER_LABELLED", "labelled_by": "owner", "labelled_at": "2026-10-12",
        "capture": {"url": "https://example.test/p", "captured_at": "2026-10-05T10:00:00+07:00",
                    "permission_basis": "robots allowed; owner approval", "robots_checked": True}}
    assert validate_scenario(raw) == []
    raw["provenance"]["capture"]["robots_checked"] = False
    assert any("robots_checked" in p for p in validate_scenario(raw))


def test_every_labelled_claim_spec_is_well_formed() -> None:
    for scn in load_scenarios():
        for obs in scn.observations:
            problems: list[str] = []
            for name in ("claims", "forbidden", "tolerated"):
                for spec in obs.expect.get(name, []):
                    assert shadow._claim_spec(spec, name, problems) is not None, (scn.id, spec)
            assert not problems


# ------------------------------------------------------- offline / no-write rules

def test_offline_guard_blocks_network_and_restores_it() -> None:
    real = socket.socket.connect
    with offline_guard():
        with pytest.raises(NetworkAttempted):
            socket.create_connection(("example.com", 80), timeout=1)
        with pytest.raises(NetworkAttempted):
            socket.getaddrinfo("example.com", 80)
    assert socket.socket.connect is real


def test_replay_provider_cannot_make_up_a_reply(catalog) -> None:
    scn = next(s for s in load_scenarios() if s.id.startswith("s03"))
    stripped = replace(scn, observations=tuple(
        replace(o, replies=()) for o in scn.observations))
    record = run_scenario(stripped, catalog)
    assert record["unscripted_calls"] >= 1
    # The engine fails closed on an unusable provider rather than inventing a claim.
    assert record["observations"][1]["status"] == "REVIEW"
    assert "PROVIDER_FAILED" in record["observations"][1]["review"]


def test_run_leaves_no_state_behind_and_does_not_touch_fixtures(catalog) -> None:
    def tmp_dirs() -> set[str]:
        return {p.name for p in Path(tempfile.gettempdir()).glob("pee2-*")}

    def digest() -> str:
        h = hashlib.sha256()
        for path in sorted(FIXTURE_DIR.glob("*")):
            h.update(path.read_bytes())
        return h.hexdigest()

    before_tmp, before_fx = tmp_dirs(), digest()
    run_corpus(FIXTURE_DIR, catalog=catalog)
    assert tmp_dirs() == before_tmp
    assert digest() == before_fx


# ------------------------------------------------------------- reproducibility

def test_two_runs_are_byte_identical_and_match_the_stored_artifacts(corpus, catalog) -> None:
    again = run_corpus(FIXTURE_DIR, catalog=catalog)
    first, second = render_artifacts(corpus), render_artifacts(again)
    assert first == second
    for name, text in first.items():
        stored = (STORED / name).read_text(encoding="utf-8")
        assert stored == text, (
            f"{name} drifted from the stored artifact; regenerate with "
            "`python tools/price_event_shadow.py --out docs/price-intelligence/pee2` "
            "and review the diff")


def test_timelines_are_independent_of_hash_seed_and_working_directory(tmp_path) -> None:
    env = {"PYTHONHASHSEED": "987", "PATH": "/usr/bin:/bin"}
    done = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "price_event_shadow.py"),
         "--out", str(STORED), "--check", "--enforce"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stdout + done.stderr
    assert json.loads(done.stdout) == {"drift": [], "failed_gates": []}


# --------------------------------------- what the seed corpus says about PEE-1

def test_regression_gates_pass_on_the_seed_corpus(corpus) -> None:
    gates = corpus["summary"]["gates"]
    assert all(g["pass"] for g in gates.values()), {
        k: g["value"] for k, g in gates.items() if not g["pass"]}
    # Sanity: the gates ran over real work, not an empty set.
    s = corpus["summary"]
    assert s["observations"] >= 50 and s["event_detection"]["labelled_events"] >= 20
    assert s["p5"]["checked"] >= 15 and s["claims"]["labelled"] >= 100


def test_unchanged_noisy_pages_make_no_event_and_no_ai_call(corpus) -> None:
    storm = next(t for t in corpus["timelines"] if t["id"].startswith("s12"))
    rows = storm["observations"]
    assert len(rows) == 8
    assert [r["status"] for r in rows].count("UNCHANGED") == 6
    assert sum(r["ai_calls"] for r in rows) == 0
    # Eight scrapes, one real price event.
    ev = next(e for e in corpus["evaluations"] if e["id"].startswith("s12"))
    assert ev["totals"]["engine_price_events"] == ev["totals"]["truth_price_events"] == 1


def test_terms_only_change_is_fail_closed_then_resolved_on_retry(corpus) -> None:
    rows = {r["obs"]: r for r in next(
        t for t in corpus["timelines"] if t["id"].startswith("s03"))["observations"]}
    assert rows["o2"]["status"] == "AI_EXTRACTED" and rows["o2"]["conditions"]
    assert rows["o3"]["status"] == "UNCHANGED" and rows["o3"]["ai_calls"] == 0
    assert rows["o4"]["status"] == "REVIEW"
    assert rows["o4"]["review"] == ["CONDITIONS_NOT_INTERPRETED"]
    assert rows["o5"]["status"] == "AI_EXTRACTED" and rows["o5"]["conditions"] == [
        "limited to the first 100 customers"]


def test_p5_24h_rule_holds_for_rule_and_ai_claims_alike(corpus) -> None:
    by_id = {t["id"]: {r["obs"]: r for r in t["observations"]} for t in corpus["timelines"]}

    def disposition(scn: str, obs: str, amount: int) -> str:
        return next(x["disposition"] for x in by_id[scn][obs]["p5"]
                    if x["claim"][2] == amount and x["claim"][3] == "LIST_PRICE")

    # Rule-read price cut: pending, then confirmed by a fresh observation 25h later.
    assert disposition("s02_home_price_cut_p5_24h", "o2", 679000) == "PENDING_REPLACEMENT"
    assert disposition("s02_home_price_cut_p5_24h", "o3", 679000) == "CONFIRMED_REPLACEMENT"
    # AI-read price: the second observation is served from the stored interpretation
    # (no new model call) and still confirms.
    first = by_id["s16_ai_claim_p5_24h_reobservation"]
    assert disposition("s16_ai_claim_p5_24h_reobservation", "o1", 679000) == "PENDING_REPLACEMENT"
    assert first["o2"]["ai_calls"] == 0 and first["o2"]["cache_hit"] is True
    assert disposition("s16_ai_claim_p5_24h_reobservation", "o2", 679000) == "CONFIRMED_REPLACEMENT"


def test_a_vanished_offer_is_neither_a_price_event_nor_an_expiry(corpus) -> None:
    """Roadmap P-1: missing offer != zero; absence is not expiry."""
    tl = next(t for t in corpus["timelines"] if t["id"].startswith("s23"))
    ev = next(e for e in corpus["evaluations"] if e["id"].startswith("s23"))
    gone = tl["observations"][1]
    assert gone["status"] == "DETERMINISTIC" and gone["changes"]       # the page did change
    assert gone["rule_claims"] == [] and gone["ai_claims"] == []       # nothing invented
    assert gone["ai_calls"] == 0
    assert ev["totals"]["engine_price_events"] == ev["totals"]["truth_price_events"] == 0
    assert ev["notes"] == []


def test_cache_and_budget_behaviour_is_measured(corpus) -> None:
    u = corpus["summary"]["usage"]
    assert u["cache_hits"] >= 5 and u["calls_avoided_vs_naive"] > 0
    assert 0 < u["input_token_reduction_vs_naive"] < 1
    budget = next(t for t in corpus["timelines"] if t["id"].startswith("s14"))["observations"]
    assert [r["ai_calls"] for r in budget] == [1, 1, 0, 1]
    assert budget[2]["review"] == ["TOKEN_BUDGET_EXHAUSTED"]
    outage = next(t for t in corpus["timelines"] if t["id"].startswith("s15"))["observations"]
    assert outage[0]["ai_calls"] == 3 and outage[0]["status"] == "REVIEW"


# --------------------------------------------------- OPEN findings (not fixed here)

def test_open_findings_still_reproduce_and_are_excluded_only_from_the_gates(corpus) -> None:
    findings = corpus["open_findings"]
    assert {f["finding"] for f in findings} == {"PEE2-F1", "PEE2-F2"}
    assert {f["scenario"][:3] for f in findings} == {
        "s17", "s18", "s19", "s20", "s21", "s22"}
    for f in findings:
        # If this fails the engine was fixed: mark the fixture resolved and move
        # the scenario into the regression set instead of deleting the evidence.
        assert f["reproduces"], f"{f['scenario']} no longer reproduces {f['finding']}"
    headline = corpus["summary"]["claims"]
    assert headline["false_accepts"] >= 12 and headline["forbidden_hits"] >= 12
    assert corpus["summary"]["gates"]["false_accepts"]["value"] == 0
    # The consequence that matters downstream: a wrong claim reaches P5 confirmation.
    assert corpus["summary"]["p5"]["forbidden_hits"] >= 3


def test_wrong_pairing_is_resolved_and_then_kept_alive_by_the_cache(corpus) -> None:
    rows = next(t for t in corpus["timelines"] if t["id"].startswith("s19"))["observations"]
    assert rows[0]["status"] == "AI_EXTRACTED"            # PEE2-F2: should have been REVIEW
    assert rows[1]["status"] == "UNCHANGED" and rows[1]["ai_calls"] == 0
    assert rows[1]["ai_claims"] == rows[0]["ai_claims"]   # the wrong pair is re-emitted
    assert all(x["disposition"] == "CONFIRMED_REPLACEMENT" for x in rows[1]["p5"])


# ------------------------------------------- the harness can actually see defects

def _gate_failures(tmp_path, catalog, *names) -> dict:
    result = run_corpus(_subset(tmp_path, *names), catalog=catalog)
    return {k: g["value"] for k, g in result["summary"]["gates"].items() if not g["pass"]}


def test_mutation_unanswered_trigger_is_caught(tmp_path, catalog, monkeypatch) -> None:
    assert _gate_failures(tmp_path, catalog, "s03_promo_terms_only_change") == {}
    monkeypatch.setattr(price_event, "unaccounted_triggers", lambda *a, **k: [])
    failed = _gate_failures(tmp_path, catalog, "s03_promo_terms_only_change")
    assert failed.get("unsafe_resolves", 0) >= 1 and failed.get("lost_pending_events", 0) >= 1


def test_mutation_conditional_wording_guard_removed_is_caught(
        tmp_path, catalog, monkeypatch) -> None:
    names = ("s07_finance_conditional_not_msrp",)
    assert _gate_failures(tmp_path, catalog, *names) == {}
    never = re.compile(r"(?!x)x")
    monkeypatch.setattr(price_event_validate, "_TRAIL_FINANCE", never)
    monkeypatch.setattr(price_event_validate, "_TRAIL_CONDITIONAL", never)
    failed = _gate_failures(tmp_path, catalog, *names)
    assert failed.get("forbidden_hits", 0) >= 1 and failed.get("false_accepts", 0) >= 1


def test_mutation_noise_sensitive_fingerprint_is_caught(tmp_path, catalog, monkeypatch) -> None:
    names = ("s12_noise_storm_one_real_change",)
    assert _gate_failures(tmp_path, catalog, *names) == {}
    monkeypatch.setattr(price_event, "price_segments", lambda text, window: [text])
    failed = _gate_failures(tmp_path, catalog, *names)
    assert failed.get("false_events", 0) >= 1


def test_mutation_no_interpretation_reuse_loses_p5_reobservation(
        tmp_path, catalog, monkeypatch) -> None:
    names = ("s16_ai_claim_p5_24h_reobservation",)
    assert _gate_failures(tmp_path, catalog, *names) == {}
    monkeypatch.setattr(price_event.EventState, "interpretation", lambda *a, **k: None)
    failed = _gate_failures(tmp_path, catalog, *names)
    assert failed.get("p5_mismatches", 0) >= 1 and failed.get("missed_claims", 0) >= 1


def test_mutation_ignoring_the_daily_cap_is_caught(tmp_path, catalog, monkeypatch) -> None:
    names = ("s14_daily_budget_exhaustion",)
    assert _gate_failures(tmp_path, catalog, *names) == {}
    monkeypatch.setattr(price_event.PriceEventConfig, "call_budget", lambda self, s: 10 ** 6)
    monkeypatch.setattr(price_event.PriceEventConfig, "token_budget", lambda self, s: 10 ** 9)
    failed = _gate_failures(tmp_path, catalog, *names)
    # o3 now calls the provider although the labels say the cap must hold.
    assert failed.get("ai_call_budget_violations", 0) >= 1


# -------------------------------------------------------- metric arithmetic

def _tiny_scenario(expect_by_obs: list[dict]):
    raw = {
        "schema_version": 1, "id": "t", "role": "PRICE_LIST",
        "provenance": {"evidence_kind": "SYNTHETIC_ADVERSARIAL", "rights": "synthetic",
                       "label_status": "PROPOSED_PENDING_OWNER_REVIEW"},
        "observations": [
            {"id": f"o{i}", "t": f"2026-10-0{i + 1}T10:00:00+07:00", "body": "<p/>",
             "expect": e} for i, e in enumerate(expect_by_obs)]}
    assert validate_scenario(raw) == [], validate_scenario(raw)
    tmp = Path(tempfile.mkdtemp())
    (tmp / "t.json").write_text(json.dumps(raw), encoding="utf-8")
    return load_scenarios(tmp)[0]


def _row(**over) -> dict:
    row = {"scenario": "t", "obs": "o0", "t": "x", "status": "DETERMINISTIC", "changes": [],
           "fallback_reasons": [], "rule_claims": [], "ai_claims": [], "twin_claims": [],
           "conditions": [], "review": [], "ai_calls": 0, "cache_hit": False,
           "tokens_in": 0, "tokens_out": 0, "naive_input_tokens": 0, "provider_calls": 0,
           "unused_scripted_replies": 0, "p5": []}
    row.update(over)
    return row


M = "JAECOO 5 EV"
GOOD = [M, "MAX+", 699000, "LIST_PRICE", None, None]
BAD = [M, "MAX+", 599000, "LIST_PRICE", None, None]


def _score(expects: list[dict], rows: list[dict], unscripted: int = 0) -> dict:
    scn = _tiny_scenario(expects)
    return evaluate_scenario(scn, {"unscripted_calls": unscripted, "observations": [
        {**r, "obs": f"o{i}"} for i, r in enumerate(rows)]})["totals"]


def spec(amount: int) -> dict:
    return {"model": M, "trim": "MAX+", "amount": amount, "type": "LIST_PRICE"}


def test_metrics_count_each_kind_of_error_once() -> None:
    base = {"baseline": True, "disposition": "DETERMINISTIC", "claims": [spec(699000)]}
    t = _score(
        [base,
         {"disposition": "UNCHANGED", "event": "NEW", "claims": [spec(699000)],
          "forbidden": [spec(599000)]},                       # missed event + forbidden accept
         {"disposition": "REVIEW", "event": "NONE", "claims": []},   # false event + unsafe resolve
         {"disposition": "UNCHANGED", "event": "PENDING_RETRY", "claims": [spec(699000)]}],
        [_row(rule_claims=[GOOD]),
         _row(status="UNCHANGED", changes=[], rule_claims=[GOOD], ai_claims=[BAD]),
         _row(status="AI_EXTRACTED", changes=["AMOUNTS"], ai_claims=[GOOD]),
         _row(status="UNCHANGED", changes=[], rule_claims=[GOOD])])
    assert t["missed_events"] == 1 and t["lost_pending_events"] == 1
    assert t["false_events"] == 1
    assert t["false_accepts_ai"] == 2 and t["forbidden_hits"] == 1
    assert t["unsafe_resolves"] == 1 and t["disposition_mismatches"] == 1


def test_metrics_missed_claims_coverage_and_review_load() -> None:
    t = _score(
        [{"baseline": True, "disposition": "DETERMINISTIC", "claims": [spec(699000)]},
         {"disposition": "REVIEW", "event": "NEW", "claims": [], "max_ai_calls": 0}],
        [_row(rule_claims=[]),
         _row(status="REVIEW", changes=["AMOUNTS"], review=["UNCOVERED_AMOUNT", "TRIM_AMBIGUOUS"],
              ai_calls=2)], unscripted=1)
    assert t["missed_claims"] == 1 and t["covered_claims"] == 0
    assert t["review_observations"] == 1 and t["review_items"] == 2
    assert t["ai_call_budget_violations"] == 1 and t["unscripted_calls"] == 1


def test_metrics_p5_expectations_and_forbidden_outcomes() -> None:
    p5_row = {"claim": GOOD, "disposition": "CONFIRMED_REPLACEMENT", "reasons": []}
    key = f"{M}|MAX+|LIST_PRICE|699000"
    t = _score(
        [{"baseline": True, "disposition": "DETERMINISTIC", "claims": [spec(699000)],
          "p5": {key: "PENDING_REPLACEMENT"},
          "p5_forbidden": {key: "CONFIRMED_REPLACEMENT"}},
         {"disposition": "UNCHANGED", "claims": [spec(699000)], "p5": {key: "NO_CHANGE"}}],
        [_row(rule_claims=[GOOD], p5=[p5_row]), _row(status="UNCHANGED", rule_claims=[GOOD])])
    assert t["p5_mismatches"] == 2 and t["p5_forbidden_hits"] == 1


def test_price_event_counts_changes_not_scrapes_and_absence_is_not_a_change() -> None:
    a = {(M, "MAX+", 699000, "LIST_PRICE", None, None)}
    b = {(M, "MAX+", 679000, "LIST_PRICE", None, None)}
    events = shadow._stream_events([a, a, set(), a, b, b, set(), b])
    assert sum(events.values()) == 1                       # one price cut, eight scrapes
    assert sum(shadow._stream_events([a, a, a]).values()) == 0
    late = {(M, "ULTRA", 789000, "LIST_PRICE", None, None)}
    assert sum(shadow._stream_events([a, a | late]).values()) == 1   # a new offer appearing


def test_cost_is_never_assumed() -> None:
    usage = {"tokens_in": 2_000_000, "tokens_out": 500_000,
             "naive_every_fetch_input_tokens": 4_000_000}
    assert estimate_cost(usage, in_per_mtok=None, out_per_mtok=None) is None
    assert estimate_cost(usage, in_per_mtok=1.0, out_per_mtok=None) is None
    cost = estimate_cost(usage, in_per_mtok=1.0, out_per_mtok=2.0)
    assert cost["engine"] == 3.0 and cost["naive_input_only"] == 4.0


def test_aggregate_gates_ignore_open_findings_but_headline_counts_them() -> None:
    clean = {"id": "a", "evidence_kind": "SYNTHETIC_ADVERSARIAL", "known_finding": None,
             "label_status": "PROPOSED_PENDING_OWNER_REVIEW", "totals": {"observations": 2},
             "review_reasons": {}}
    dirty = {**clean, "id": "b", "known_finding": {"id": "F"},
             "totals": {"observations": 2, "false_accepts": 3}}
    agg = aggregate([clean, dirty], gated=[clean])
    assert agg["claims"]["false_accepts"] == 3
    assert agg["gates"]["false_accepts"]["value"] == 0 and agg["gates"]["false_accepts"]["pass"]
    assert not aggregate([clean, dirty])["gates"]["false_accepts"]["pass"]


def test_loading_rejects_an_empty_or_duplicate_corpus(tmp_path) -> None:
    with pytest.raises(ShadowFixtureError):
        load_scenarios(tmp_path)
    raw = _raw("s03_promo_terms_only_change")
    (tmp_path / "a.json").write_text(json.dumps(raw), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ShadowFixtureError, match="duplicate"):
        load_scenarios(tmp_path)
    raw["provenance"]["label_status"] = "OWNER_LABELLED"
    (tmp_path / "b.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ShadowFixtureError, match="OWNER_LABELLED requires"):
        load_scenarios(tmp_path)
