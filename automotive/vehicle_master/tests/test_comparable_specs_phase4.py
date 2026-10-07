from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import shutil
import warnings

import pytest

from vehreg.battlecard import BattleCardEngine
from vehreg.catalog import Catalog, CatalogError, DATA_DIR
from vehreg.cli import main
from vehreg.comparable_specs import (
    ComparableCohort, ComparableSpecError, ECOCandidateSpecStore, SpecLedger,
    SpecRegistry, ValueState,
)
from vehreg.product import ProductMaster, import_spec_facts


ATTO3 = "762c0806-4101-4155-9343-7c2dc815dd3b"
MGS5 = "ee5085a9-67ca-40f6-9944-550da794d94c"
EX5 = "e9901aa9-5f90-406e-a56d-3d19da56b895"
JAECOO_TRIM = "jaecoo.jaecoo_5_ev.j5.trim.max_plus_bev"


@pytest.fixture
def local_data(tmp_path):
    shutil.copytree(DATA_DIR / "2026", tmp_path / "2026")
    return tmp_path


def fact(**changes):
    row = {
        "fact_id": "test.jaecoo.max_plus.power.2026",
        "trim_id": JAECOO_TRIM,
        "field_key": "powertrain.max_power_kw",
        "value_state": "KNOWN",
        "value": 155,
        "unit": "kW",
        "qualifiers": {"output_scope": "MOTOR", "rating_basis": "PEAK"},
        "effective_from": "2026-01-01",
        "effective_to": None,
        "observed_at": "2026-09-08",
        "claim_ids": ["claim.official.example"],
        "verification_status": "VERIFIED",
        "source": "official_oem",
        "source_ref": "https://example.com/specification",
        "source_locator": "Powertrain table / MAX+",
    }
    row.update(changes)
    return row


def payload(*facts):
    return {"schema_version": 1, "facts": list(facts)}


def test_registry_and_c_crossover_cohort_are_closed_and_valid():
    registry = SpecRegistry.load()
    # 60 originally; +36 to accept the monthly ECO Sticker export, which
    # carried fuel consumption, emissions standards, equipment booleans and
    # the EV charging/warranty facts the registry had no home for.
    assert len(registry.fields) == 96
    assert set(registry.profiles) == {
        "c_crossover_core", "c_crossover_safety", "c_crossover_comfort",
        "c_crossover_fitment",
    }
    cohort = ComparableCohort.load()
    catalog = Catalog.load()
    assert cohort.validate(catalog) == []
    for model_id in cohort.model_ids:
        assert catalog.models[model_id].body_type.value == "CROSSOVER"
        assert any(g.segment.value == "C" for g in catalog.generations_of(model_id))


def test_the_cohort_is_the_rule_it_says_it_is():
    """A hand-picked list described as a segment is not a segment.

    Leaving the X1, the XC40 and the Q3 out of "C-crossover" while keeping cars
    with a single ECO row would make every card in it quietly unrepresentative.
    """
    import gzip
    import json as _json
    cohort = ComparableCohort.load()
    catalog = Catalog.load()
    eligible = {
        model_id for model_id, model in catalog.models.items()
        if model.body_type.value == "CROSSOVER"
        and any(g.segment.value == "C" for g in catalog.generations_of(model_id))}
    path = (DATA_DIR / "2026/ingest/ecosticker/snapshots/2026-09-08"
            / "normalized.jsonl.gz")
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        rows = [_json.loads(line) for line in handle]
    with_evidence = {
        row["matched_model_id"] for row in rows
        if row["detail_status"] == "available" and row.get("powertrain_candidate")}
    assert set(cohort.model_ids) == eligible & with_evidence


def test_a_model_without_a_representative_stays_in_the_segment():
    """Dropping it would hide a whole car and still call the result the segment."""
    cohort = ComparableCohort.load()
    missing = cohort.models_without_representative
    assert set(missing) <= set(cohort.model_ids)
    assert cohort.validate(Catalog.load()) == []


def test_eco_candidates_cover_the_cohort_but_publish_nothing():
    store = ECOCandidateSpecStore.load()
    coverage = store.coverage()
    assert coverage == {
        # The universe the segment rule admits...
        "eligible_models": 31,
        # ...and what is actually published today.
        "pilot_models": 20,
        "expansion_backlog": 11,
        "models_with_candidates": 31,
        "candidate_trims": 118,
        "representative_candidates": 20,
        "candidate_spec_values": 1740,
        # Nothing is promoted, and the reason is recorded rather than implied.
        "published_market_trims": 0,
        "pilot_models_with_current_oem_evidence": 0,
    }
    representatives = store.list(representatives_only=True)
    assert len(representatives) == 20
    assert all(r["publication_status"] == "PROVISIONAL_UNRESOLVED_TRIM"
               for r in representatives)
    assert all(r["price_classification"] == "ECO_STICKER_PRICE"
               for r in representatives)


def test_candidate_battle_card_keeps_price_noncanonical_and_has_cell_sources():
    store = ECOCandidateSpecStore.load()
    card = BattleCardEngine(store.registry).candidate_card(
        store, [ATTO3, MGS5, EX5])
    assert card["mode"] == "PROVISIONAL_ECO_CANDIDATES"
    assert card["global_winner"] is None
    assert all(s["current_list_price"] is None for s in card["subjects"])
    assert all(s["price_evidence"]["price_type"] == "ECO_STICKER_PRICE"
               and not s["price_evidence"]["canonical_retail_price"]
               for s in card["subjects"])
    range_row = next(r for r in card["rows"]
                     if r["field_key"] == "ev.rated_range_km")
    assert range_row["comparison_status"] == "COMPARABLE"
    assert range_row["leaders"] == [f"ecosticker:{EX5}"]
    assert range_row["cells"][f"ecosticker:{ATTO3}"]["source_ref"].startswith(
        "https://car.ecosticker.go.th/")


def test_unknown_is_not_rendered_as_false_and_mismatched_basis_is_not_compared():
    registry = SpecRegistry.load()
    engine = BattleCardEngine(registry)
    subjects = [
        {"subject_id": "a", "label": "A", "values": [
            {"field_key": "safety.aeb", "value_state": "KNOWN", "value": False,
             "unit": "", "qualifiers": {}, "source": "oem", "source_ref": "a",
             "verification_status": "VERIFIED"},
            {"field_key": "ev.rated_range_km", "value_state": "KNOWN", "value": 500,
             "unit": "km", "qualifiers": {"measurement_basis": "WLTP"},
             "source": "oem", "source_ref": "a", "verification_status": "VERIFIED"},
        ]},
        {"subject_id": "b", "label": "B", "values": [
            {"field_key": "ev.rated_range_km", "value_state": "KNOWN", "value": 600,
             "unit": "km", "qualifiers": {"measurement_basis": "NEDC"},
             "source": "oem", "source_ref": "b", "verification_status": "VERIFIED"},
        ]},
    ]
    profile = deepcopy(registry.profiles)
    registry.profiles["test"] = ["safety.aeb", "ev.rated_range_km"]
    card = engine._build(subjects, profile_id="test", mode="TEST")
    aeb = card["rows"][0]
    assert aeb["cells"]["a"]["display"] == "ไม่มี"
    assert aeb["cells"]["b"]["value_state"] == "UNKNOWN"
    assert aeb["cells"]["b"]["display"] is None
    range_rows = [row for row in card["rows"]
                  if row["field_key"] == "ev.rated_range_km"]
    assert {row["comparison_context"]["measurement_basis"] for row in range_rows} \
        == {"NEDC", "WLTP"}
    # Two cars measured on different cycles are two rows, and neither wins.
    # This is a context split, not a hole in the research, and it says so.
    assert all(row["comparison_status"] == "CONTEXT_NOT_SHARED"
               and not row["leaders"] for row in range_rows)
    registry.profiles = profile


def test_fact_ledger_is_temporal_and_never_resurrects_expired_new_fact():
    registry = SpecRegistry.load()
    ledger = SpecLedger(registry)
    ledger.add_payload(payload(
        fact(fact_id="old", value=150, effective_from="2026-01-01"),
        fact(fact_id="new", value=160, effective_from="2026-06-01",
             effective_to="2026-06-30"),
    ))
    assert ledger.resolved(JAECOO_TRIM, as_of=date(2026, 6, 15))[0].value == 160
    assert ledger.resolved(JAECOO_TRIM, as_of=date(2026, 7, 1)) == []


def test_conflicting_values_at_one_start_fail_closed():
    registry = SpecRegistry.load()
    ledger = SpecLedger(registry)
    ledger.add_payload(payload(
        fact(fact_id="a"), fact(fact_id="b", value=999),
    ))
    assert any("conflicting" in problem for problem in ledger.validate())


def test_a_stray_field_on_a_fact_is_rejected():
    ledger = SpecLedger(SpecRegistry.load())
    with pytest.raises(ComparableSpecError, match="invalid/unknown fact fields"):
        ledger.add_payload({"schema_version": 1, "facts": [
            dict(fact(), price_thb=1)
        ]})


@pytest.mark.parametrize(("field_key", "unit"), [
    ("market.list_price_thb", "THB"),
    ("retail.msrp", ""),
    ("cost.total", ""),
    ("vehicle.range", "THB"),
])
def test_a_price_shaped_fact_is_rejected(field_key, unit):
    ledger = SpecLedger(SpecRegistry.load())
    with pytest.raises(ComparableSpecError, match="prices belong in PriceLedger"):
        ledger.add_payload({"schema_version": 1, "facts": [
            dict(fact(), field_key=field_key, unit=unit)
        ]})


def test_a_price_field_cannot_be_registered_at_all():
    """The only way a price gets into the spec store is by being registered.

    Guarding the payload alone was not a guard: a fact naming an unregistered
    key is refused anyway, and one naming a *registered* price key sailed
    through. The registry itself now refuses to hold a price field.
    """
    from vehreg.comparable_specs import SpecFieldDefinition, ValueType, ComparisonRule
    registry = SpecRegistry([SpecFieldDefinition(
        key="market.list_price_thb", group="identity", label_th="ราคา",
        label_en="List price", value_type=ValueType.NUMBER,
        comparison_rule=ComparisonRule.LOWER_BETTER, canonical_unit="THB")])
    assert any("PriceLedger" in problem for problem in registry.validate())


def test_spec_import_is_dry_run_idempotent_and_registration_safe(local_data):
    before = [r.as_row() for r in Catalog.load(local_data).iter_resolved()]
    data = payload(fact())
    dry = import_spec_facts(local_data, 2026, data)
    assert dry["added"] == 1 and not dry["written"]
    assert not Path(dry["path"]).exists()
    written = import_spec_facts(local_data, 2026, data, write=True)
    assert written["written"] and written["added"] == 1
    repeated = import_spec_facts(local_data, 2026, data, write=True)
    assert not repeated["written"] and repeated["added"] == 0
    master = ProductMaster.load(local_data)
    resolved = master.detail(JAECOO_TRIM, as_of=date(2026, 9, 8))["comparable_specs"]
    # By field_key, not position: this trim carries other resolved comparable
    # specs too (from the bulk ECO import), and resolved() is sorted by
    # field_key across all of them, not just this test's own injected fact.
    power = next(row for row in resolved if row["field_key"] == "powertrain.max_power_kw")
    assert power["value"] == 155
    assert master.validate() == []
    after = [r.as_row() for r in Catalog.load(local_data).iter_resolved()]
    assert after == before
    changed = payload(fact(value=999))
    with pytest.raises(CatalogError, match="fact_id"):
        import_spec_facts(local_data, 2026, changed, write=True)


def test_cli_exposes_coverage_candidates_and_battle_card(capsys):
    assert main(["market", "spec-coverage"]) == 0
    candidates = json.loads(capsys.readouterr().out)["candidates"]
    assert (candidates["eligible_models"], candidates["pilot_models"]) == (31, 20)
    assert main(["market", "battle-card", "--candidate", ATTO3,
                 "--candidate", MGS5]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == \
        "PROVISIONAL_ECO_CANDIDATES"
    assert main(["market", "battle-card", "--candidate", ATTO3]) == 2
    assert "2 to 6" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# A comparison that ranks incomparable things is worse than no comparison.
# ---------------------------------------------------------------------------

def _subject(subject_id, powertrain, values):
    return {"subject_id": subject_id, "label": subject_id,
            "powertrain": powertrain, "values": values}


def _range(value, scope, basis="ECO_STICKER_DECLARED"):
    return {"field_key": "ev.rated_range_km", "value_state": "KNOWN",
            "value": value, "unit": "km",
            "qualifiers": {"measurement_basis": basis, "range_scope": scope},
            "source": "ecosticker", "source_ref": "x",
            "verification_status": "PROVISIONAL"}


def _card(subjects, fields):
    registry = SpecRegistry.load()
    engine = BattleCardEngine(registry)
    keep = deepcopy(registry.profiles)
    registry.profiles["test"] = fields
    try:
        return engine._build(subjects, profile_id="test", mode="TEST")
    finally:
        registry.profiles = keep


def test_a_plug_in_hybrid_does_not_lose_a_race_it_was_not_in():
    """150 km of electric range is not a worse version of 500 km of range."""
    card = _card([
        _subject("bev", "BEV", [_range(500, "FULL")]),
        _subject("phev", "PHEV", [_range(150, "ELECTRIC_ONLY")]),
    ], ["ev.rated_range_km"])
    rows = [r for r in card["rows"] if r["field_key"] == "ev.rated_range_km"]
    assert len(rows) == 2, "the two quantities must not share a row"
    assert all(not row["leaders"] for row in rows)
    assert {row["comparison_status"] for row in rows} == {"CONTEXT_NOT_SHARED"}


def test_two_bevs_are_still_ranked_on_range():
    card = _card([
        _subject("a", "BEV", [_range(500, "FULL")]),
        _subject("b", "BEV", [_range(410, "FULL")]),
    ], ["ev.rated_range_km"])
    row = card["rows"][0]
    assert (row["comparison_status"], row["leaders"]) == ("COMPARABLE", ["a"])


def test_a_ranked_field_is_not_crowned_across_powertrains():
    """A plug-in's smaller battery is not a smaller version of the same thing."""
    def battery(value):
        return {"field_key": "battery.gross_capacity_kwh", "value_state": "KNOWN",
                "value": value, "unit": "kWh", "qualifiers": {},
                "source": "oem", "source_ref": "x",
                "verification_status": "VERIFIED"}
    card = _card([_subject("bev", "BEV", [battery(82)]),
                  _subject("phev", "PHEV", [battery(18)])],
                 ["battery.gross_capacity_kwh"])
    row = card["rows"][0]
    assert row["comparison_status"] == "NOT_COMPARABLE_ACROSS_POWERTRAIN"
    assert row["leaders"] == []
    # Both numbers are still shown; refusing to rank is not refusing to report.
    assert {c["value"] for c in row["cells"].values()} == {82, 18}


def test_zero_tailpipe_co2_does_not_beat_a_hybrid():
    """A BEV emits nothing at the tailpipe by definition, not by merit."""
    def co2(value):
        return {"field_key": "emissions.co2_g_km", "value_state": "KNOWN",
                "value": value, "unit": "g/km",
                "qualifiers": {"measurement_basis": "ECO_STICKER_DECLARED"},
                "source": "ecosticker", "source_ref": "x",
                "verification_status": "PROVISIONAL"}
    card = _card([_subject("bev", "BEV", [co2(0)]),
                  _subject("phev", "PHEV", [co2(10)])], ["emissions.co2_g_km"])
    row = card["rows"][0]
    assert (row["comparison_status"], row["leaders"]) == (
        "NOT_COMPARABLE_ACROSS_POWERTRAIN", [])


def test_a_car_without_an_engine_is_not_missing_research():
    card = _card([
        _subject("bev", "BEV", []),
        _subject("phev", "PHEV", [{
            "field_key": "engine.displacement_cc", "value_state": "KNOWN",
            "value": 1498, "unit": "cc", "qualifiers": {}, "source": "ecosticker",
            "source_ref": "x", "verification_status": "PROVISIONAL"}]),
    ], ["engine.displacement_cc"])
    row = card["rows"][0]
    assert row["comparison_status"] == "NOT_APPLICABLE_TO_OTHERS"
    assert row["cells"]["bev"]["value_state"] == "NOT_APPLICABLE"


def test_one_battery_chemistry_is_written_one_way():
    from vehreg.comparable_specs import battery_chemistry_family, transmission_family
    for raw in ("LFP", "LiFePO4", "Lithium iron phosphate/graphite",
                "lithium-phosphate (LFP)", "Lithium Iron Phosphate (LFP)"):
        assert battery_chemistry_family(raw) == "LFP", raw
    assert battery_chemistry_family("NCM/Graphite") == "NMC"
    assert battery_chemistry_family("Li-Ion (NCA)") == "NCA"
    assert battery_chemistry_family("Lithium-ion") == "LI_ION_UNSPECIFIED"
    assert battery_chemistry_family("-") is None
    # CVT rows also say "automatic"; the more specific answer has to win.
    assert transmission_family("เกียร์อัตโนมัติ ประเภท CVT") == "CVT"
    assert transmission_family("เกียร์อัตโนมัติ") == "AUTOMATIC"
    assert transmission_family("เกียร์ธรรมดา") == "MANUAL"
    assert transmission_family("-") is None


# ---------------------------------------------------------------------------
# Eligibility is not the same question as what is published today.
# ---------------------------------------------------------------------------

def test_the_pilot_is_what_has_a_representative_and_nothing_else():
    cohort = ComparableCohort.load()
    self_check = set(cohort.model_ids) & set(cohort.representative_source_ids)
    assert set(cohort.pilot_model_ids) == self_check
    assert len(cohort.pilot_model_ids) == 20
    assert set(cohort.pilot_model_ids) | set(cohort.expansion_backlog) \
        == set(cohort.model_ids)


def test_the_backlog_does_not_shrink_the_segment():
    """Eleven models are eligible and unpublished. Both facts stay true."""
    cohort = ComparableCohort.load()
    assert len(cohort.expansion_backlog) == 11
    assert len(cohort.model_ids) == 31
    assert cohort.validate(Catalog.load()) == []


def test_a_suggested_representative_is_not_a_chosen_one():
    cohort = ComparableCohort.load()
    assert set(cohort.expansion_candidates) <= set(cohort.expansion_backlog)
    assert not set(cohort.expansion_candidates) & set(cohort.representative_source_ids)
    store = ECOCandidateSpecStore.load()
    published = {r["source_id"] for r in store.list(representatives_only=True)}
    assert not published & set(cohort.expansion_candidates.values())


def test_every_suggestion_points_at_a_real_row_for_that_model():
    store = ECOCandidateSpecStore.load()
    for model_id, source_id in ComparableCohort.load().expansion_candidates.items():
        assert store.get(source_id)["model_id"] == model_id, model_id


def test_the_volvo_xc40_has_no_suggestion_because_none_matches_the_car():
    """Its ECO rows are older Recharge BEV/PHEV; the current car is a mild hybrid."""
    cohort = ComparableCohort.load()
    assert "volvo.xc40" in cohort.expansion_backlog
    assert "volvo.xc40" not in cohort.expansion_candidates


# ---------------------------------------------------------------------------
# Bulk source import may materialise a deterministic grade, but never unsourced.
# ---------------------------------------------------------------------------

ECO_IMPORT_REASON = "bulk import from TDR EcoSticker"


def creation_revision(trim_id):
    """The canonical revision that first put this trim into its model, or None.

    Read from the append-only revision log (canonical_state/revisions.jsonl), so the
    answer is who created the grade and under what batch reason, not a guess from
    the trim's own fields. A model bundle's `after` lists full trim ids; its `before`
    is the raw model record with generation-local ids.
    """
    model_id = trim_id.split(".trim.")[0].rsplit(".", 1)[0]
    local_id = trim_id.split(".trim.", 1)[1]
    path = DATA_DIR / "2026" / "canonical_state" / "revisions.jsonl"

    def after_ids(bundle):
        return {t.get("id") for t in bundle.get("trims", [])} if isinstance(bundle, dict) else set()

    def before_ids(record):
        if not isinstance(record, dict):
            return set()
        return {f"{model_id}.{g.get('id')}.trim.{t.get('id')}"
                for g in record.get("generations", []) for t in g.get("trims", [])}

    with path.open(encoding="utf-8") as lines:
        for line in lines:
            if f'"{model_id}"' not in line or local_id not in line:
                continue  # cheap filter: only the few lines that name this grade are parsed
            row = json.loads(line)
            if row.get("operation") != "UPSERT_MODEL_BUNDLE" or row.get("entity_id") != model_id:
                continue
            if trim_id in after_ids(row.get("after")) and trim_id not in before_ids(row.get("before")):
                return row
    return None


def test_pilot_trims_materialised_by_eco_are_source_backed():
    """A deterministic bulk import may create identity; provenance is mandatory.

    The candidate-store workflow above remains provisional. The newer source
    importer is a separate path: when every existing grade in a model/powertrain
    has already been accounted for, an unmatched exact ECO grade may be created.
    Such a row must carry the filing UUID that justified that creation.

    A grade the owner added through an approved ADMIN batch (for example the REPAIR-02b
    current-retail set, which created GEELY EX5 MAX+) is not an ECO creation: its
    provenance is that batch, traceable in the revision log, and it has no ECO filing
    to cite. Every pilot grade must therefore either carry ECO refs or be traceable to
    a non-ECO creation; an ECO-created grade without refs, or one with no trace at all,
    still fails.
    """
    catalog = Catalog.load(year=2026)
    pilot = set(ComparableCohort.load().pilot_model_ids)
    promoted = [trim for trim in catalog.trims.values()
                if catalog.model_for_trim(trim.id).id in pilot]
    assert promoted
    for trim in promoted:
        if trim.source_refs.get("eco", ()):
            continue
        created = creation_revision(trim.id)
        assert created is not None, f"{trim.id}: pilot trim has no ECO provenance and no traceable creation"
        assert not str(created.get("reason", "")).startswith(ECO_IMPORT_REASON), (
            f"{trim.id}: bulk-created pilot trim lacks ECO provenance")
        assert created.get("actor"), f"{trim.id}: creation revision names no actor"


def test_the_creation_trace_separates_admin_grades_from_eco_grades():
    """Regression for the provenance guard: GEELY EX5 MAX+ is owner-created, MAX is ECO."""
    admin = creation_revision("geely.geely_ex5.gen1.trim.max_plus")
    assert admin is not None and not admin["reason"].startswith(ECO_IMPORT_REASON)
    assert admin["actor"] == "smgkikikiki-cloud"
    assert "ev-retail-repair-lot-02" in admin["reason"]
    eco = creation_revision("geely.geely_ex5.gen1.trim.max_bev")
    assert eco is not None and eco["reason"].startswith(ECO_IMPORT_REASON)
    assert creation_revision("geely.geely_ex5.gen1.trim.no_such_grade") is None


def test_the_gap_has_an_address_rather_than_being_a_silence():
    from vehreg.comparable_specs import load_oem_sources
    sources = load_oem_sources()
    pilot = set(ComparableCohort.load().pilot_model_ids)
    assert set(sources) == pilot
    for model_id, source in sources.items():
        assert source["official_url"].startswith("https://"), model_id
        assert source["polling"] in ("ALLOWED", "REFUSED"), model_id
        assert source["evidence_note"], model_id
    # Two brands refuse automated agents outright; that is a fact about them,
    # not a gap we can close by trying harder.
    refused = {m for m, s in sources.items() if s["polling"] == "REFUSED"}
    assert refused == {"mazda.cx30", "jaecoo.jaecoo_6t_ev", "jaecoo.jaecoo_7"}


def test_eco_prices_never_reach_the_price_ledger():
    from vehreg.product import ProductMaster
    from vehreg.pricing import PriceType
    master = ProductMaster.load()
    pilot = set(ComparableCohort.load().pilot_model_ids)
    for record in master.prices.records:
        if record.price_type is not PriceType.ECO_STICKER_PRICE:
            continue
        model_id = master.catalog.model_for_trim(record.trim_id).id
        assert model_id not in pilot, f"{record.trim_id}: ECO price on a pilot model"
    for trim_id in {r.trim_id for r in master.prices.records}:
        current = master.prices.current_list_price(trim_id)
        if current is not None:
            assert current.price_type is PriceType.LIST_PRICE


# --------------------------------------------------------------------------
# Phase 6 -- fitment expansion: the schema exists, no value has been invented
# --------------------------------------------------------------------------

FITMENT_FIELDS = (
    "fitment.wheel_rim_width_front_in", "fitment.wheel_rim_width_rear_in",
    "fitment.wheel_pcd", "fitment.wheel_offset_mm",
    "fitment.tyre_load_index_front", "fitment.tyre_load_index_rear",
    "fitment.tyre_speed_rating_front", "fitment.tyre_speed_rating_rear",
    "fitment.battery_12v_group_size", "fitment.battery_12v_capacity_ah",
)


def test_the_fitment_fields_are_registered_and_grouped_with_the_rest_of_chassis():
    registry = SpecRegistry.load()
    for key in FITMENT_FIELDS:
        assert key in registry.fields, key
        assert registry.fields[key].group == "chassis", key
    assert registry.profiles["c_crossover_fitment"] == list(FITMENT_FIELDS)
    assert registry.validate() == []


def test_a_rim_width_or_offset_field_is_a_number_with_a_unit():
    registry = SpecRegistry.load()
    for key in ("fitment.wheel_rim_width_front_in", "fitment.wheel_rim_width_rear_in",
                "fitment.wheel_offset_mm", "fitment.tyre_load_index_front",
                "fitment.tyre_load_index_rear", "fitment.battery_12v_capacity_ah"):
        definition = registry.fields[key]
        assert definition.value_type == "NUMBER", key
        assert definition.canonical_unit, key
        assert definition.validate_value(ValueState.KNOWN, 42, definition.canonical_unit) == []
        assert definition.validate_value(ValueState.KNOWN, -1, definition.canonical_unit), key


def test_pcd_and_battery_group_are_free_form_codes_not_numbers():
    """"5x114.3" and "55D23L" are not measurements; a NUMBER field would refuse them."""
    registry = SpecRegistry.load()
    for key in ("fitment.wheel_pcd", "fitment.battery_12v_group_size"):
        definition = registry.fields[key]
        assert definition.value_type == "TEXT", key
        assert definition.validate_value(ValueState.KNOWN, "5x114.3", "") == []


REFUSED, UNREVIEWED, EVIDENCED = "REFUSED", "UNREVIEWED", "EVIDENCED"


def fitment_status(fact_row):
    """How far a fitment fact may be trusted. Provenance decides; who imported it does not.

    * REFUSED     -- not shaped like an owner/admin entry (`admin:<trim>:<field>`): some other
                     writer produced a fitment value. No evidence source in this pipeline has
                     ever reported one, so it is invented.
    * UNREVIEWED  -- an admin entry with no recorded source. The Vehicle Specs workbook is a
                     deliberately source-free editor (docs/vehicle-spec-excel-import), so
                     arriving through it proves nothing about the value, whatever the import
                     stamped on it (`verification_status: VERIFIED` is infrastructure, not a
                     review). It is reviewable, never accepted as correct.
    * EVIDENCED   -- carries both a `source` and an http(s) `source_ref` to check it against.
    """
    key = fact_row.get("field_key")
    if fact_row.get("fact_id") != f"admin:{fact_row.get('trim_id')}:{key}":
        return REFUSED
    ref = str(fact_row.get("source_ref") or "")
    if fact_row.get("source") and ref.startswith(("https://", "http://")):
        return EVIDENCED
    return UNREVIEWED


def committed_fitment_facts():
    """(path, fact_row) for every fitment fact in every committed ledger."""
    found = []
    for path in (DATA_DIR / "2026" / "product" / "comparable_specs").rglob("*.json"):
        if path.name in ("registry.json", "profiles.json", "oem_sources.json"):
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for fact_row in payload.get("facts", []):
            if fact_row.get("field_key") in FITMENT_FIELDS:
                found.append((path, fact_row))
    return found


def test_no_fitment_value_has_been_invented_for_any_pilot_trim():
    """The schema exists; nothing in this code may invent a value for it.

    Phase 6 was asked for as a fitment database, not a set of numbers this code
    made up to fill the new columns. No evidence source in this pipeline (ECO, OEM,
    candidate store, importers) has ever reported a PCD, an offset, a load index, a
    speed rating or a 12V battery group -- only a tyre size string -- so no ledger
    may hold a machine-derived fact against these keys.

    Owner/admin entries from the source-free Vehicle Specs workbook are not invented by
    this code, but they are not evidence either: they are reported here as UNREVIEWED
    (a warning naming each one) so the gap stays visible until a source-backed change
    supplies `source` and `source_ref`. An unreviewed value is never treated as confirmed.
    """
    unreviewed = []
    for path, fact_row in committed_fitment_facts():
        status = fitment_status(fact_row)
        assert status != REFUSED, f"{path}: invented a value for {fact_row.get('field_key')}"
        if status == UNREVIEWED:
            unreviewed.append(f"{fact_row['fact_id']} = {fact_row.get('value')!r}")
    if unreviewed:
        warnings.warn(
            f"{len(unreviewed)} source-free admin fitment value(s) are UNREVIEWED, not confirmed: "
            + "; ".join(sorted(unreviewed)), stacklevel=1)


def test_an_admin_workbook_import_alone_does_not_establish_a_fitment_value():
    """Regression: arriving through the admin import, even stamped VERIFIED, is not evidence."""
    trim = "example.model.gen1.trim.any_grade"
    entry = {"fact_id": f"admin:{trim}:fitment.wheel_pcd", "trim_id": trim,
             "field_key": "fitment.wheel_pcd", "value_state": "KNOWN", "value": "5x100",
             "verification_status": "VERIFIED", "observed_at": "2026-09-30"}
    assert fitment_status(entry) == UNREVIEWED
    # An import that records a source but no checkable reference, or the reverse, is still not evidence.
    assert fitment_status({**entry, "source": "vehicle-spec-excel"}) == UNREVIEWED
    assert fitment_status({**entry, "source_ref": "https://example.test/spec"}) == UNREVIEWED
    assert fitment_status({**entry, "source_ref": "vehicle-spec-excel"}) == UNREVIEWED
    # Only a value that can be checked against a source is EVIDENCED.
    sourced = {**entry, "source": "oem_official_website", "source_ref": "https://example.test/spec"}
    assert fitment_status(sourced) == EVIDENCED


def test_a_machine_written_fitment_fact_is_still_refused_as_invented():
    """The guard did not stop looking: anything not shaped like an admin entry is invented."""
    trim = "example.model.gen1.trim.any_grade"
    entry = {"fact_id": f"admin:{trim}:fitment.wheel_pcd", "trim_id": trim, "field_key": "fitment.wheel_pcd"}
    assert fitment_status({**entry, "fact_id": f"eco:{trim}:fitment.wheel_pcd"}) == REFUSED
    assert fitment_status({**entry, "fact_id": "test.some.fact"}) == REFUSED
    assert fitment_status({**entry, "fact_id": f"admin:{trim}:fitment.wheel_offset_mm"}) == REFUSED
    assert fitment_status({**entry, "trim_id": "example.other.gen1.trim.grade"}) == REFUSED
    # A fake source on a machine-shaped fact does not rescue it.
    assert fitment_status({**entry, "fact_id": f"eco:{trim}:fitment.wheel_pcd", "source": "x",
                           "source_ref": "https://example.test/spec"}) == REFUSED


def test_unreviewed_fitment_values_are_listed_and_never_counted_as_confirmed():
    """Whatever the committed data holds, nothing source-free is ever EVIDENCED."""
    for _path, fact_row in committed_fitment_facts():
        if not (fact_row.get("source") and str(fact_row.get("source_ref") or "").startswith(("http://", "https://"))):
            assert fitment_status(fact_row) != EVIDENCED
