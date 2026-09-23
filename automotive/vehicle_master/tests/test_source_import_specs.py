"""The 8 required regression behaviors for ECO comparable-spec/price wiring
in vehreg/source_import.py + tools/import_source.py, consolidated with (and
replacing) vehreg/ecosticker_import.py's own duplicate command-building.

Every test drives the real pipeline: real ecosticker_export.normalize_row,
the real production comparable-spec registry (copied verbatim, not a
stand-in -- unit and powertrain applicability are exactly what decides which
of a row's values survive), the real resolve_rows/commands_from_outcomes/
spec_commands_from_outcomes/price_commands_from_outcomes, and a real
CanonicalInputPipeline.apply() read back with Catalog.load()/SpecLedger.load().
Nothing here is a source-grep.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from vehreg.catalog import Catalog
from vehreg.comparable_specs import SpecLedger, SpecRegistry
from vehreg.ecosticker_import import plan_row
from vehreg.input_pipeline import CanonicalInputPipeline
from vehreg.source_import import (
    ExistingTrim, SourceRow, batches_from_commands, commands_from_outcomes,
    price_commands_from_outcomes, resolve_rows, resolved_trim_id,
    spec_commands_from_outcomes,
)

YEAR = 2026
REAL_REGISTRY = (Path(__file__).resolve().parents[1] / "vehreg" / "data" / str(YEAR)
                 / "product" / "comparable_specs" / "registry.json")


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """One brand, one single-generation model with one existing ICE trim --
    enough to exercise MATCHED (existing trim) and CREATED (new trim) rows
    against the real registry."""
    data = tmp_path / "data"
    _write(data / str(YEAR) / "models" / "acme.json", {
        "brand": {"id": "acme", "name_en": "Acme", "name_th": "",
                  "brand_segment": "MASS", "oem_group": "UNKNOWN",
                  "brand_origin": "TH", "trim_detail": False, "aliases": []},
        "models": [{
            "id": "runner", "name_en": "Runner", "name_th": "", "nameplate": "",
            "body_type": "SEDAN", "cab_type": "NOT_APPLICABLE",
            "registration_type": "", "market_scope": "CORE", "aliases": [],
            "generations": [{
                "code": "gen1", "segment": "B", "seats": 5,
                "launched": "2025-01-01", "ended": None,
                "variants": [{"id": "v1", "name": "Runner 1.5 ICE", "powertrain": "ICE",
                    "drivetrain": "FWD", "engine_cc": 1496, "battery_kwh": None,
                    "price_thb": None, "price_min_thb": None, "price_max_thb": None,
                    "import_type": "CKD", "origin_country": "TH", "price_note": "",
                    "aliases": []}],
                "trims": [{"id": "premium", "name": "Premium", "powertrain": "ICE",
                           "aliases": [], "source_refs": {}}],
            }],
        }],
    })
    target = data / str(YEAR) / "product" / "comparable_specs" / "registry.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(REAL_REGISTRY, target)
    return data


@pytest.fixture
def catalog(tree: Path) -> Catalog:
    return Catalog.load(tree, YEAR)


@pytest.fixture
def registry(tree: Path) -> SpecRegistry:
    return SpecRegistry.load(tree, YEAR)


MODEL = "acme.runner"
GEN = "acme.runner.gen1"
EXISTING_TRIM = f"{GEN}.trim.premium"


def eco_row(model: str, **overrides) -> dict:
    base = {
        "id": "3283e6a6-999d-4964-91d2-064f22b13369",
        "brand": "ACME", "model": model, "cartype_name": "ICE",
        "car_style": "รถยนต์นั่ง 4 ประตู (Sedan)", "company_name": "Acme Co",
        "model_year": "2026", "factory": "Acme Plant",
        "recomend_retail_price_new": "899000", "tax_rate_new": "0.15",
        "engine_name": "แก๊สโซลีน", "fuel_name": "เชื้อเพลิงผสม (เบนซิน-E20)",
        "gear_name": "เกียร์อัตโนมัติ", "capacity_cylinder": "1496.0",
        "car_seats": "5", "car_length": "4500", "car_width": "1780",
        "car_height": "1460", "total_weight": "1600", "wheel_size": "205/55R16",
        "emissions_CO2": "120", "energy_combined_rate": "5.2",
        "std_tis": "1", "car_equip_safety": "ABS; ESC/VSA/VSC",
        "approve_date": "2026-06-01T09:00:00+07:00",
    }
    base.update(overrides)
    return base


def build(raw_rows: list[dict], catalog: Catalog, registry: SpecRegistry):
    """The exact tools/import_source.py pipeline, called directly on dicts
    instead of a CSV file -- import_source.source_rows() itself has no
    behaviour of its own beyond calling plan_row() and copying its output
    into SourceRow, which is what this reproduces without needing a pandas
    round trip."""
    rows = []
    exceptions = []
    dropped: dict[str, int] = {}
    for raw in raw_rows:
        plan = plan_row(raw, catalog, registry)
        for key in plan.dropped:
            dropped[key] = dropped.get(key, 0) + 1
        if plan.status == "UNRESOLVED" or not plan.model_id:
            exceptions.append(plan)
            continue
        rows.append(SourceRow(
            source_id=plan.source_id, source_kind="ECO",
            model_id=plan.model_id, generation_id=plan.generation_id or "",
            powertrain=plan.vehicle.powertrain or "", trim_name=plan.trim_name or "",
            values=dict(plan.vehicle.specs), specs=dict(plan.specs),
            qualifiers=dict(plan.vehicle.qualifiers), observed_at=plan.vehicle.approved_at,
            source_ref=plan.vehicle.source_url, price_thb=plan.vehicle.price_thb,
        ))

    trims = [ExistingTrim(canonical_id=t.id, model_id=model_id, generation_id=t.generation_id,
                          name=t.name, powertrain=t.powertrain.value,
                          columns={"source_refs": {k: list(v) for k, v in (t.source_refs or {}).items()}},
                          source_ids=tuple(str(v) for vs in (t.source_refs or {}).values() for v in vs))
            for model_id in catalog.models for t in catalog.trims_of(model_id)]
    generation_codes = {g.id: g.code for model_id in catalog.models
                        for g in catalog.generations_of(model_id) if g.code}
    outcomes = resolve_rows(rows, trims, known_generations=generation_codes)
    model_commands, stranded = commands_from_outcomes(
        outcomes, generation_codes=generation_codes,
        existing_by_trim={t.canonical_id: t for t in trims})
    # existing_facts is deliberately empty here: this helper always plans
    # against a catalogue with nothing written yet. Tests that need to prove
    # idempotency/re-dating (7a, 7b) load the real facts off disk themselves
    # after an apply() and call spec_commands_from_outcomes() a second time
    # directly, rather than through this helper.
    spec_commands = spec_commands_from_outcomes(outcomes, registry=registry, existing_facts={})
    price_commands, suppressed = price_commands_from_outcomes(outcomes, price_type="ECO_STICKER_PRICE")
    return {
        "outcomes": outcomes, "exceptions": exceptions, "dropped": dropped,
        "model_commands": model_commands, "spec_commands": spec_commands,
        "price_commands": price_commands, "suppressed": suppressed,
        "commands": model_commands + spec_commands + price_commands,
    }


def apply(data: Path, commands: list[dict], *, prefix: str):
    batches = batches_from_commands(
        commands, year=YEAR, source_kind="ECO", source_ref="eco-book.xlsx",
        batch_prefix=prefix, submitted_at="2026-09-21T00:00:00+00:00")
    for batch in batches:
        result = CanonicalInputPipeline(data).apply(batch)
        assert result.status == "APPLIED", result
    return batches


# ---------------------------------------------------------------------------
# 1. ECO range -> APPEND_SPEC
# ---------------------------------------------------------------------------

def test_1_eco_range_becomes_an_append_spec_fact(tree, catalog, registry):
    plan = build([eco_row("Runner Long Range", cartype_name="BEV", engine_name="ไฟฟ้า",
                          capacity_cylinder="-", fuel_name="-", driving_range="550")],
                catalog, registry)
    facts = [c for c in plan["spec_commands"] if c["payload"]["field_key"] == "ev.rated_range_km"]
    assert len(facts) == 1
    fact = facts[0]["payload"]
    assert fact["value"] == 550.0
    assert fact["unit"] == "km"
    assert fact["qualifiers"] == {"measurement_basis": "ECO_STICKER_TH"}
    assert fact["observed_at"] == "2026-06-01"
    assert fact["source"] == "ecosticker"
    assert fact["source_ref"].endswith("3283e6a6-999d-4964-91d2-064f22b13369")

    apply(tree, plan["commands"], prefix="eco-1")
    ledger = SpecLedger.load(tree, YEAR, registry=registry,
                             catalog=Catalog.load(tree, YEAR))
    trim_id = resolved_trim_id(plan["outcomes"][0])
    saved = [f for f in ledger.facts if f.trim_id == trim_id and f.field_key == "ev.rated_range_km"]
    assert len(saved) == 1 and saved[0].value == 550.0


# ---------------------------------------------------------------------------
# 2. CO2 / fuel consumption -> correct unit + qualifier
# ---------------------------------------------------------------------------

def test_2_co2_and_fuel_consumption_carry_the_registry_unit_and_basis_qualifier(
        tree, catalog, registry):
    plan = build([eco_row("Runner Premium")], catalog, registry)  # matches the existing ICE trim
    by_key = {c["payload"]["field_key"]: c["payload"] for c in plan["spec_commands"]}

    co2 = by_key["emissions.co2_g_km"]
    assert co2["value"] == 120.0
    assert co2["unit"] == "g/km"
    assert co2["qualifiers"] == {"measurement_basis": "ECO_STICKER_TH"}

    consumption = by_key["efficiency.fuel_consumption_l_100km"]
    assert consumption["value"] == 5.2
    assert consumption["unit"] == "L/100km"
    assert consumption["qualifiers"] == {"measurement_basis": "ECO_STICKER_TH"}

    apply(tree, plan["commands"], prefix="eco-2")
    assert Catalog.load(tree, YEAR).validate() == []


# ---------------------------------------------------------------------------
# 3. Gross battery -> battery.gross_capacity_kwh, never MarketTrim.battery_kwh
# ---------------------------------------------------------------------------

def test_3_gross_battery_capacity_is_a_fact_not_a_market_trim_column(tree, catalog, registry):
    plan = build([eco_row("Runner EV", cartype_name="BEV", engine_name="ไฟฟ้า",
                          capacity_cylinder="-", fuel_name="-",
                          battery_capacity="169", nominal_voltage="326.4")],
                catalog, registry)
    trim_row = [c for c in plan["model_commands"]
               if c["operation"] == "UPSERT_MODEL_BUNDLE"][0]["payload"]["trims"][0]
    assert "battery_kwh" not in trim_row

    field_keys = {c["payload"]["field_key"] for c in plan["spec_commands"]}
    assert "battery.gross_capacity_kwh" in field_keys

    apply(tree, plan["commands"], prefix="eco-3")
    catalog_after = Catalog.load(tree, YEAR)
    trim_id = resolved_trim_id(plan["outcomes"][0])
    assert catalog_after.trims[trim_id].battery_kwh is None


# ---------------------------------------------------------------------------
# 4. ICE starter battery chemistry is filtered, not written or fabricated
# ---------------------------------------------------------------------------

def test_4_ice_starter_battery_chemistry_is_dropped_not_written(tree, catalog, registry):
    plan = build([eco_row("Runner Premium", battery_type="Lead Acid")], catalog, registry)
    field_keys = {c["payload"]["field_key"] for c in plan["spec_commands"]}
    assert "battery.chemistry" not in field_keys
    assert plan["dropped"].get("battery.chemistry") == 1


# ---------------------------------------------------------------------------
# 5. Safety flags: True only, never a fabricated False
# ---------------------------------------------------------------------------

def test_5_safety_flags_are_written_true_only_never_false(tree, catalog, registry):
    plan = build([eco_row("Runner Premium")], catalog, registry)  # "ABS; ESC/VSA/VSC"
    by_key = {c["payload"]["field_key"]: c["payload"]["value"] for c in plan["spec_commands"]
              if c["payload"]["field_key"].startswith("safety.")}
    assert by_key.get("safety.abs") is True
    assert by_key.get("safety.esc") is True
    # AEB was never mentioned in the source text -- absent, not False.
    assert "safety.aeb" not in by_key
    assert all(value is True for value in by_key.values())

    apply(tree, plan["commands"], prefix="eco-5")
    assert Catalog.load(tree, YEAR).validate() == []


# ---------------------------------------------------------------------------
# 6. A CREATED trim: UPSERT_MODEL_BUNDLE first, then its APPEND_SPEC facts
#    resolve to the exact trim id the writer actually creates.
# ---------------------------------------------------------------------------

def test_6_created_trim_upserts_first_then_its_facts_resolve_to_the_real_id(
        tree, catalog, registry):
    plan = build([eco_row("Runner Long Range", cartype_name="BEV", engine_name="ไฟฟ้า",
                          capacity_cylinder="-", fuel_name="-", driving_range="480")],
                catalog, registry)
    outcome = plan["outcomes"][0]
    assert outcome.status == "CREATED"
    predicted_id = resolved_trim_id(outcome)

    # Ordering: every model command precedes every spec command in the
    # concatenated list tools/import_source.py actually submits.
    combined = plan["commands"]
    upsert_index = next(i for i, c in enumerate(combined) if c["operation"] == "UPSERT_MODEL_BUNDLE")
    spec_indices = [i for i, c in enumerate(combined) if c["operation"] == "APPEND_SPEC"]
    assert spec_indices and all(i > upsert_index for i in spec_indices)
    assert all(c["payload"]["trim_id"] == predicted_id for c in plan["spec_commands"])

    apply(tree, combined, prefix="eco-6")
    catalog_after = Catalog.load(tree, YEAR)
    assert predicted_id in catalog_after.trims
    ledger = SpecLedger.load(tree, YEAR, registry=registry, catalog=catalog_after)
    assert any(f.trim_id == predicted_id and f.field_key == "ev.rated_range_km" for f in ledger.facts)


# ---------------------------------------------------------------------------
# 7. Re-import: no duplicate facts, and two different dated records for the
#    same trim+field do not collide (the reason fact_id is source-scoped).
# ---------------------------------------------------------------------------

def test_7a_reimporting_the_same_record_produces_no_new_spec_commands(tree, catalog, registry):
    row = eco_row("Runner Premium")
    first = build([row], catalog, registry)
    apply(tree, first["commands"], prefix="eco-7a-1")

    catalog_after = Catalog.load(tree, YEAR)
    ledger = SpecLedger.load(tree, YEAR, registry=registry, catalog=catalog_after)
    existing_facts = {
        f.fact_id: {"value_state": f.value_state.value, "value": f.value, "unit": f.unit,
                    "qualifiers": f.qualifiers, "observed_at": f.observed_at}
        for f in ledger.facts
    }

    second = build([row], catalog_after, registry)
    replay_spec_commands = spec_commands_from_outcomes(
        second["outcomes"], registry=registry, existing_facts=existing_facts)
    assert replay_spec_commands == []


def test_7b_a_later_differently_dated_record_is_a_new_fact_not_an_overwrite(tree, catalog, registry):
    """The exact case a trim+field-keyed fact_id (or the writer's own
    admin:<trim_id>:<field_key> fallback) would get wrong: two distinct ECO
    records, different source uuids, different approval dates, different
    values, describing the same trim and the same field."""
    first_row = eco_row("Runner Premium", id="11111111-1111-1111-1111-111111111111",
                        approve_date="2026-01-10T09:00:00+07:00", emissions_CO2="120")
    second_row = eco_row("Runner Premium", id="22222222-2222-2222-2222-222222222222",
                         approve_date="2026-07-15T09:00:00+07:00", emissions_CO2="118")

    first = build([first_row], catalog, registry)
    apply(tree, first["commands"], prefix="eco-7b-1")

    catalog_after = Catalog.load(tree, YEAR)
    ledger = SpecLedger.load(tree, YEAR, registry=registry, catalog=catalog_after)
    existing_facts = {
        f.fact_id: {"value_state": f.value_state.value, "value": f.value, "unit": f.unit,
                    "qualifiers": f.qualifiers, "observed_at": f.observed_at}
        for f in ledger.facts
    }
    second = build([second_row], catalog_after, registry)
    second_spec_commands = spec_commands_from_outcomes(
        second["outcomes"], registry=registry, existing_facts=existing_facts)
    co2_commands = [c for c in second_spec_commands if c["payload"]["field_key"] == "emissions.co2_g_km"]
    assert len(co2_commands) == 1, "the later, differently-dated record must still produce a fact"
    assert co2_commands[0]["payload"]["fact_id"] != first["spec_commands"][
        [c["payload"]["field_key"] for c in first["spec_commands"]].index("emissions.co2_g_km")
    ]["payload"]["fact_id"]

    apply(tree, second_spec_commands, prefix="eco-7b-2")
    final_ledger = SpecLedger.load(tree, YEAR, registry=registry, catalog=Catalog.load(tree, YEAR))
    trim_id = resolved_trim_id(first["outcomes"][0])
    co2_facts = sorted(
        (f for f in final_ledger.facts if f.trim_id == trim_id and f.field_key == "emissions.co2_g_km"),
        key=lambda f: f.observed_at)
    # Both observations survive as two distinct, correctly dated facts.
    assert [f.value for f in co2_facts] == [120.0, 118.0]
    assert [f.observed_at for f in co2_facts] == ["2026-01-10", "2026-07-15"]


# ---------------------------------------------------------------------------
# 8. An inapplicable/registry-unknown value is dropped and reported, and
#    never fails the rest of the import.
# ---------------------------------------------------------------------------

def test_8_an_inapplicable_value_is_dropped_and_the_rest_of_the_import_still_applies(
        tree, catalog, registry):
    good_row = eco_row("Runner Long Range", id="aaaaaaaa-0000-0000-0000-000000000000",
                       cartype_name="BEV", engine_name="ไฟฟ้า",
                       capacity_cylinder="-", fuel_name="-", driving_range="500")
    bad_row = eco_row("Runner Premium", id="bbbbbbbb-0000-0000-0000-000000000000",
                      battery_type="Lead Acid")  # battery.chemistry inapplicable to ICE
    unresolvable_row = eco_row("Completely Unknown Nameplate XYZ",
                               id="cccccccc-0000-0000-0000-000000000000")

    plan = build([good_row, bad_row, unresolvable_row], catalog, registry)

    assert plan["dropped"].get("battery.chemistry") == 1
    assert len(plan["exceptions"]) == 1  # the unresolvable row, reported, not guessed at
    field_keys = {c["payload"]["field_key"] for c in plan["spec_commands"]}
    assert "ev.rated_range_km" in field_keys  # the good row's fact still made it through
    assert "battery.chemistry" not in field_keys

    batches = apply(tree, plan["commands"], prefix="eco-8")
    assert batches  # at least one batch actually applied
    assert Catalog.load(tree, YEAR).validate() == []


# ---------------------------------------------------------------------------
# 9. A row with no stated approval date still gets facts, dated by the run
#    -- the fallback the retired commands_for's own `observed_at` parameter
#    gave (test_a_row_with_no_approval_date_falls_back_to_the_run), now
#    carried by spec_commands_from_outcomes'/price_commands_from_outcomes'
#    own `submitted_at` argument instead.
# ---------------------------------------------------------------------------

def test_9_a_row_with_no_approval_date_falls_back_to_the_runs_own_date(tree, catalog, registry):
    row = eco_row("Runner Long Range", cartype_name="BEV", engine_name="ไฟฟ้า",
                  capacity_cylinder="-", fuel_name="-", driving_range="550",
                  approve_date="", recomend_retail_price_new="950000")
    plan = build([row], catalog, registry)
    # No run date threaded in: a row with no stated approval date produces
    # nothing, rather than a fact/price dated by nothing at all.
    assert plan["spec_commands"] == [] and plan["price_commands"] == []

    spec_commands = spec_commands_from_outcomes(
        plan["outcomes"], registry=registry, existing_facts={}, submitted_at="2026-09-18")
    price_commands, _ = price_commands_from_outcomes(
        plan["outcomes"], price_type="ECO_STICKER_PRICE", submitted_at="2026-09-18")
    assert spec_commands and price_commands
    assert all(c["payload"]["observed_at"] == "2026-09-18" for c in spec_commands)
    assert all(c["payload"]["observed_at"] == "2026-09-18" for c in price_commands)


# ---------------------------------------------------------------------------
# 10. What an ECO price observation claims, what it never claims, and how
#     its history survives the real pipeline -- ported from the retired
#     vehreg/ecosticker_import.py::commands_for's own price coverage, now
#     against price_commands_from_outcomes/PriceLedger directly.
# ---------------------------------------------------------------------------

def test_10a_the_price_is_dated_by_the_rows_own_approval_date(tree, catalog, registry):
    plan = build([eco_row("Runner Premium", approve_date="2023-04-11T09:00:00+07:00",
                          recomend_retail_price_new="899000")], catalog, registry)
    assert len(plan["price_commands"]) == 1
    price = plan["price_commands"][0]["payload"]
    assert price["amount_thb"] == 899000
    # Dated 2023, not today -- an ECO record can be years old.
    assert price["observed_at"] == "2023-04-11"


def test_10b_the_price_never_claims_to_be_a_current_list_price(tree, catalog, registry):
    """ECO_STICKER_PRICE, not LIST_PRICE, and no effective_from.

    PriceLedger.current_list_amount() resolves the LIST_PRICE stream only,
    so a homologation figure cannot surface as this week's MSRP. And an ECO
    record establishes only what was stated on a day, never that the price
    took force then and held -- effective_from would be a claim the source
    never makes.
    """
    from vehreg.pricing import PriceLedger, PriceType

    plan = build([eco_row("Runner Premium", recomend_retail_price_new="899000")],
                catalog, registry)
    price = plan["price_commands"][0]["payload"]
    assert price["price_type"] == "ECO_STICKER_PRICE"
    assert price["source"] == "ecosticker"
    assert price["source_ref"].startswith("https://car.ecosticker.go.th/")
    assert "effective_from" not in price

    apply(tree, plan["commands"], prefix="eco-10b")
    final = Catalog.load(tree, YEAR)
    trim_id = resolved_trim_id(plan["outcomes"][0])
    ledger = PriceLedger.load(tree, year=YEAR, catalog=final)
    records = ledger.records_for(trim_id)
    assert [r.amount_thb for r in records] == [899000]
    assert records[0].price_type is PriceType.ECO_STICKER_PRICE
    assert ledger.current_list_amount(trim_id) is None


def test_10c_no_stated_price_produces_no_price_command(tree, catalog, registry):
    for blank in ("", "-", "0"):
        plan = build([eco_row("Runner Premium", recomend_retail_price_new=blank)],
                    catalog, registry)
        assert plan["price_commands"] == []


def test_10d_the_same_record_filed_twice_is_one_price_observation(tree, catalog, registry):
    plan = build([
        eco_row("Runner Premium", id="aaaaaaaa-0000-0000-0000-000000000001",
               approve_date="2024-01-10T09:00:00+07:00", recomend_retail_price_new="899000"),
        eco_row("Runner Premium", id="aaaaaaaa-0000-0000-0000-000000000002",
               approve_date="2024-01-10T09:00:00+07:00", recomend_retail_price_new="899000"),
    ], catalog, registry)
    assert len(plan["price_commands"]) == 1
    assert len(plan["suppressed"]) == 1

    apply(tree, plan["commands"], prefix="eco-10d")
    final = Catalog.load(tree, YEAR)
    trim_id = resolved_trim_id(plan["outcomes"][0])
    from vehreg.pricing import PriceLedger
    records = PriceLedger.load(tree, year=YEAR, catalog=final).records_for(trim_id)
    assert len(records) == 1


def test_10e_two_differently_dated_price_records_both_survive_as_history(tree, catalog, registry):
    """Unlike the retired plan_import()'s spec dedup, a trim's price history
    was never deduplicated across records -- each dated approval is its own
    observation, which price_commands_from_outcomes still gives every row,
    not just the first one to resolve to a given trim."""
    plan = build([
        eco_row("Runner Premium", id="aaaaaaaa-0000-0000-0000-000000000001",
               approve_date="2024-01-10T09:00:00+07:00", recomend_retail_price_new="899000"),
        eco_row("Runner Premium", id="aaaaaaaa-0000-0000-0000-000000000002",
               approve_date="2026-02-20T09:00:00+07:00", recomend_retail_price_new="949000"),
    ], catalog, registry)
    assert len(plan["price_commands"]) == 2
    assert plan["suppressed"] == []

    apply(tree, plan["commands"], prefix="eco-10e")
    final = Catalog.load(tree, YEAR)
    trim_id = resolved_trim_id(plan["outcomes"][0])
    from vehreg.pricing import PriceLedger
    records = sorted(PriceLedger.load(tree, year=YEAR, catalog=final).records_for(trim_id),
                     key=lambda r: r.amount_thb)
    assert [r.amount_thb for r in records] == [899000, 949000]
