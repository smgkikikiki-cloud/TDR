"""migration_v59 (Vehicle DB v3 Phase 0 step 4) against a real Postgres.

The master is built the way production's was: a canonical data tree, the
release ReleaseBuilder makes from it, published and activated, then seeded
through the v57 seed functions; v58 switches serving; v59 is applied last.

Every expected accept/reject below comes from running the Python engine on
the same input (PriceLedger.validate, Campaign.validate, SpecLedger,
Model/Variant/MarketTrim.validate, ECOStickerSpec.validate +
validate_against_catalog, the sidecar writers). The database must agree.
"""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import date
import hashlib
import json
from pathlib import Path

import pytest

from tests.pg_cluster import SUPABASE, apply_production_schema, pg  # noqa: F401
from tests.test_vehicle_master_tables_migration_v57 import _publish, _rpc
from tdr_bridge.lifecycle import apply_retail_lifecycle
from tdr_bridge.release import ReleaseBuilder, _price_row
from tools import vehicle_master_seed as seed
from tools.engine_rule_corpus import (
    CAMPAIGNS, REGISTRY_DIR, SEED_PRICES, T_BASE, T_PLUS, T_TOP, TRIMS, YEAR, _prices, _tree, _write,
)
from vehreg import taxonomy
from vehreg.catalog import Catalog
from vehreg.comparable_specs import SpecFact, SpecLedger, SpecRegistry, ValueState, VerificationStatus, _is_price_field
from vehreg.current_retail import replace_current_retail_set
from vehreg.entities import MarketTrim, Model, Variant
from vehreg.homologation import ECOStickerSpec, ECOStickerSpecStore
from vehreg.pricing import Campaign, PriceLedger, PriceRecord, PriceType, _parse_campaign
from vehreg.retail_lifecycle_review import upsert_trim_lifecycle_disposition

V59 = SUPABASE / "migration_v59_vehicle_engine_rules.sql"
AS_OF = "2026-10-01"
MODEL_ID = "acme.a"
NUMBER_FIELD = "vehicle.length_mm"


# ---------------------------------------------------------------------------
# Fixture: a real tree -> release -> publish -> seed -> v58 -> v59
# ---------------------------------------------------------------------------

def _build_tree(root: Path) -> None:
    trims = [dict(t) for t in TRIMS]
    trims[2].update({"source_refs": {"ecosticker": ["eco-1"]}, "seats": 5, "tire_front": "215/55R17",
                     "length_mm": 4500, "wheelbase_mm": 2700})
    _tree(root, trims=trims, second_generation=True)
    _prices(root, SEED_PRICES)
    _write(root / str(YEAR) / "market" / "campaigns" / "acme.json", CAMPAIGNS)
    for name in ("registry.json", "profiles.json"):
        _write(root / str(YEAR) / "product" / "comparable_specs" / name,
               json.loads((REGISTRY_DIR / name).read_text(encoding="utf-8")))
    _write(root / str(YEAR) / "product" / "comparable_specs" / "facts" / "seed.json", {"schema_version": 1, "facts": [
        {"fact_id": "oem:len1", "trim_id": T_BASE, "field_key": NUMBER_FIELD, "value_state": "KNOWN",
         "value": 4500, "unit": "mm", "observed_at": "2026-01-01", "source": "oem",
         "source_ref": "https://example.test/spec"},
        {"fact_id": "admin:" + T_PLUS + ":" + NUMBER_FIELD, "trim_id": T_PLUS, "field_key": NUMBER_FIELD,
         "value_state": "KNOWN", "value": 4510, "unit": "mm", "observed_at": "2026-02-01"},
    ]})
    _write(root / str(YEAR) / "product" / "specs" / "ecosticker" / "eco.json", {"specs": [
        {"trim_id": T_TOP, "source_ref": "eco-1", "powertrain": "ICE", "seats": 5, "tire_size": "215/55 R17",
         "declared_total_weight_kg": 1700}]})
    _write(root / str(YEAR) / "market" / "trims" / "current_retail.json", {"schema_version": 1, "models": [
        {"model_id": MODEL_ID, "trim_ids": [T_BASE, T_TOP], "reviewer": "Owner", "reviewed_at": "2026-09-01"}]})
    _write(root / str(YEAR) / "market" / "retail_lifecycle" / "trim_review.json", {"schema_version": 1, "decisions": [
        {"trim_id": T_PLUS, "status": "HISTORICAL", "reviewer": "Owner", "reviewed_at": "2026-09-01",
         "source_ref": "https://example.test/d", "notes": ""}]})


def _release(root: Path) -> dict:
    built = ReleaseBuilder({"brands": [], "models": []}, data_dir=root, year=YEAR).build(
        as_of=date.fromisoformat(AS_OF))
    release = apply_retail_lifecycle(built, data_dir=root, year=YEAR)
    release["historical_model_state"] = {"catalog_years": [YEAR], "model_year_baselines": [], "monthly_changes": []}
    return release


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "data"
    _build_tree(root)
    return root


@pytest.fixture
def seeded(pg, tree):
    """Production's order: v58 schema, release published, master seeded."""
    pg.sql("alter role service_role bypassrls;")
    apply_production_schema(pg, through=58)
    release = _release(tree)
    _publish(pg, release)
    sections = seed.build_supplemental(tree, YEAR, registry_path=None)
    seed.apply(sections, release_id=release["release_id"], as_of=AS_OF, rpc=_rpc(pg), log=lambda _: None)
    ok, err = pg.try_sql(SUPABASE.joinpath("migration_v58_vehicle_serving_parity.sql").read_text(encoding="utf-8"))
    assert ok, err
    return pg


@pytest.fixture
def db(seeded):
    ok, err = seeded.try_sql(V59.read_text(encoding="utf-8"))
    assert ok, err
    return seeded


def _write_ok(db, sql: str) -> tuple[bool, str]:
    """One transaction, so deferred rules run at its commit, as a write would."""
    return db.try_sql(f"begin; {sql}; commit;")


def _lit(value) -> str:
    if value is None:
        return "null"
    return "'" + json.dumps(value, ensure_ascii=False).replace("'", "''") + "'::jsonb"


def _text(value) -> str:
    return "null" if value is None else "'" + str(value).replace("'", "''") + "'"


# ---------------------------------------------------------------------------
# Applying v59
# ---------------------------------------------------------------------------

def _serving(db) -> dict[str, list[list[str]]]:
    return {view: db.rows(f"select to_jsonb(v)::text from public.{view} v order by 1") for view in (
        "current_vehicle_brands", "current_vehicle_models", "current_vehicle_generations",
        "current_market_trims", "current_price_ledger", "current_spec_facts")}


def test_v59_applies_to_a_seeded_master_without_changing_serving(seeded):
    before = _serving(seeded)
    assert all(before.values())
    ok, err = seeded.try_sql(V59.read_text(encoding="utf-8"))
    assert ok, err
    assert _serving(seeded) == before
    assert seeded.scalar("select count(*) from vehicle_engine_rules_check()") == "0"
    assert seeded.scalar("select count(*) from vehicle_serving_parity_check() where not ok") == "0"
    assert seeded.scalar("select count(*) from vehicle_master_seed_check() where not ok") == "0"
    # Re-applying is a no-op.
    ok, err = seeded.try_sql(V59.read_text(encoding="utf-8"))
    assert ok, err


def test_v59_refuses_a_master_that_already_breaks_a_rule(seeded):
    seeded.sql(f"""alter table vehicle_price_ledger disable trigger user;
      insert into vehicle_price_ledger (record_id, trim_id, amount_thb, price_type, effective_from, observed_at,
        source, source_ref, in_release, payload, seed_release_id)
      select 'conflict', trim_id, amount_thb + 1, price_type, effective_from, observed_at, source, source_ref, true,
             payload || jsonb_build_object('record_id', 'conflict', 'amount_thb', amount_thb + 1), seed_release_id
        from vehicle_price_ledger where trim_id = '{T_BASE}' and price_type = 'LIST_PRICE';
      alter table vehicle_price_ledger enable trigger user;""")
    ok, err = seeded.try_sql(V59.read_text(encoding="utf-8"))
    assert not ok and "engine rules violated by existing master rows" in err and "price_conflict" in err
    assert seeded.scalar("select count(*) from pg_proc where proname = 'vehicle_engine_rules_check'") == "0"


def test_the_empty_chain_still_replays(pg):
    apply_production_schema(pg)
    assert pg.scalar("select count(*) from vehicle_engine_rules_check()") == "0"


# ---------------------------------------------------------------------------
# C. Prices: PriceLedger.validate decides, the database must agree
# ---------------------------------------------------------------------------

def _ledger(tree: Path) -> PriceLedger:
    return PriceLedger.load(tree, year=YEAR, catalog=Catalog.load(tree, YEAR))


def _python_accepts_prices(tree: Path, rows: list[dict]) -> bool:
    ledger = _ledger(tree)
    try:
        ledger.add_payload({"prices": rows})
    except Exception:
        return False
    return ledger.validate() == []


def _insert_prices_sql(rows: list[dict]) -> str:
    statements = []
    for raw in rows:
        record = PriceRecord(**{**{k: v for k, v in raw.items()}, "price_type": PriceType.parse(raw["price_type"])})
        row = json.loads(json.dumps(_price_row(record)))   # enum members -> their values, as a release row
        statements.append(
            "insert into vehicle_price_ledger (record_id, trim_id, amount_thb, price_type, effective_from, "
            "effective_to, observed_at, campaign_id, option_id, source, source_ref, source_document_id, notes, "
            "reference_price_thb, retracted_at, retraction_reason, reviewed_by, in_release, payload, seed_release_id) "
            f"values ({_text(row['record_id'])}, {_text(row['trim_id'])}, {row['amount_thb']}, {_text(row['price_type'])}, "
            f"{_text(row['effective_from'])}, {_text(row['effective_to'])}, {_text(row['observed_at'])}, "
            f"{_text(row['campaign_id'])}, {_text(row['option_id'])}, {_text(row['source'])}, {_text(row['source_ref'])}, "
            f"{_text(row['source_document_id'])}, {_text(row['notes'])}, "
            f"{'null' if row['reference_price_thb'] is None else row['reference_price_thb']}, "
            f"{_text(row['retracted_at'])}, {_text(row['retraction_reason'])}, {_text(row['reviewed_by'])}, "
            f"{'false' if row['retracted_at'] else 'true'}, {_lit(row)}, 'test')")
    return "; ".join(statements)


BASE_LIST = {"trim_id": T_BASE, "amount_thb": 919000, "price_type": "LIST_PRICE", "effective_from": "2026-11-01",
             "observed_at": "2026-10-02", "source": "oem", "source_ref": "https://example.test/n"}
PRICE_CASES = {
    "new list price": [BASE_LIST],
    "same start, different amount": [{**BASE_LIST, "effective_from": "2026-01-01"}],
    "same start, same amount": [{**BASE_LIST, "effective_from": "2026-01-01", "amount_thb": 899000}],
    "same start, different amount, retracted": [{**BASE_LIST, "effective_from": "2026-01-01",
                                                 "retracted_at": "2026-10-02", "retraction_reason": "typo"}],
    "two new rows that conflict with each other": [BASE_LIST, {**BASE_LIST, "amount_thb": 1, "source": "x"}],
    "observed-only start conflict": [{**BASE_LIST, "effective_from": None, "observed_at": "2026-03-01",
                                      "trim_id": T_PLUS, "amount_thb": 1}],
    "ended before its observed start is not active": [{**BASE_LIST, "effective_from": None, "observed_at": "2026-03-01",
                                                       "effective_to": "2026-02-01", "trim_id": T_PLUS, "amount_thb": 1}],
    "campaign scope conflict": [{**BASE_LIST, "trim_id": T_TOP, "price_type": "CAMPAIGN_PRICE", "amount_thb": 1,
                                 "effective_from": "2026-09-01", "campaign_id": "acme_q4", "option_id": "cash"}],
    "campaign without option has no scope": [{**BASE_LIST, "trim_id": T_TOP, "price_type": "CAMPAIGN_PRICE",
                                              "effective_from": "2026-09-01", "campaign_id": "acme_q4"}],
    "campaign price needs a campaign": [{**BASE_LIST, "price_type": "CAMPAIGN_PRICE"}],
    "list price in a campaign": [{**BASE_LIST, "campaign_id": "acme_q4"}],
    "option without campaign": [{**BASE_LIST, "option_id": "cash"}],
    "unknown campaign": [{**BASE_LIST, "price_type": "CAMPAIGN_PRICE", "campaign_id": "nope", "option_id": "cash"}],
    "unknown option": [{**BASE_LIST, "price_type": "FINANCE_PRICE", "campaign_id": "acme_q4", "option_id": "nope"}],
    "retracted without reason": [{**BASE_LIST, "retracted_at": "2026-10-02"}],
    "list price without any start": [{**BASE_LIST, "effective_from": None, "observed_at": None}],
    "estimated price without any start": [{**BASE_LIST, "price_type": "ESTIMATED_PRICE", "effective_from": None,
                                           "observed_at": None}],
    "ends before it starts": [{**BASE_LIST, "effective_to": "2026-10-31"}],
    "bad document id": [{**BASE_LIST, "source_document_id": "sha256:abc"}],
    "good document id": [{**BASE_LIST, "source_document_id": "sha256:" + "0" * 64}],
    "zero reference price": [{**BASE_LIST, "reference_price_thb": 0}],
    "overlay or unknown trim": [{**BASE_LIST, "trim_id": "acme.a.g1.trim.ghost"}],
}


@pytest.mark.parametrize("name", sorted(PRICE_CASES))
def test_price_rows_are_accepted_exactly_when_the_engine_accepts_them(db, tree, name):
    rows = PRICE_CASES[name]
    expected = _python_accepts_prices(tree, rows)
    try:
        sql = _insert_prices_sql(rows)
    except (TypeError, ValueError):
        pytest.fail("case must be a constructible PriceRecord")
    ok, err = _write_ok(db, sql)
    assert ok == expected, (name, expected, err)


def test_ledger_is_append_only(db):
    rid = db.scalar(f"select record_id from vehicle_price_ledger where trim_id = '{T_BASE}' and price_type = 'LIST_PRICE'")
    for sql, allowed in (
        (f"update vehicle_price_ledger set amount_thb = 1, payload = payload || '{{\"amount_thb\": 1}}' where record_id = '{rid}'", False),
        (f"update vehicle_price_ledger set source = 'x', payload = payload || '{{\"source\": \"x\"}}' where record_id = '{rid}'", False),
        (f"update vehicle_price_ledger set record_id = 'other' where record_id = '{rid}'", False),
        (f"delete from vehicle_price_ledger where record_id = '{rid}'", False),
        # close_price: effective_to + reviewed_by + notes
        (f"update vehicle_price_ledger set effective_to = '2026-10-31', reviewed_by = 'Owner', notes = 'end of MY', "
         f"payload = payload || '{{\"effective_to\": \"2026-10-31\", \"reviewed_by\": \"Owner\", \"notes\": \"end of MY\"}}' "
         f"where record_id = '{rid}'", True),
        # columns and payload must move together
        (f"update vehicle_price_ledger set effective_to = '2026-11-30' where record_id = '{rid}'", False),
        # retract (correct_price mode=retract)
        (f"update vehicle_price_ledger set retracted_at = '2026-10-02', retraction_reason = 'typo', in_release = false, "
         f"payload = payload || '{{\"retracted_at\": \"2026-10-02\", \"retraction_reason\": \"typo\"}}' "
         f"where record_id = '{rid}'", True),
        # a retraction is never undone
        (f"update vehicle_price_ledger set retracted_at = null, retraction_reason = '', in_release = true, "
         f"payload = payload || '{{\"retracted_at\": null, \"retraction_reason\": \"\"}}' where record_id = '{rid}'", False),
    ):
        ok, err = _write_ok(db, sql)
        assert ok == allowed, (sql, err)


def test_same_day_replacement_commits_as_one_write(db):
    """APPEND_PRICE's retract-and-replace: the old row is retracted and the new
    one appended in one transaction; the deferred conflict rule sees the end state."""
    rid = db.scalar(f"select record_id from vehicle_price_ledger where trim_id = '{T_BASE}' and price_type = 'LIST_PRICE'")
    new = {**BASE_LIST, "effective_from": "2026-01-01", "amount_thb": 889000}
    insert = _insert_prices_sql([new])
    retract = (f"update vehicle_price_ledger set retracted_at = '2026-01-01', retraction_reason = 'replaced', "
               f"reviewed_by = 'Owner', in_release = false, payload = payload || "
               f"'{{\"retracted_at\": \"2026-01-01\", \"retraction_reason\": \"replaced\", \"reviewed_by\": \"Owner\"}}' "
               f"where record_id = '{rid}'")
    ok, err = _write_ok(db, f"{insert}; {retract}")
    assert ok, err


# ---------------------------------------------------------------------------
# C. Campaigns: Campaign.validate decides
# ---------------------------------------------------------------------------

def _campaign_sql(campaign: Campaign) -> str:
    payload = json.loads(json.dumps(asdict(campaign), default=lambda o: o.value))
    opts = []
    for o in payload["options"]:
        opts.append(
            "insert into vehicle_promotions (campaign_id, option_id, description, valid_from, valid_to, source, "
            "option_label, option_status, closed_at, conditions, payload, seed_release_id) values ("
            f"{_text(campaign.id)}, {_text(o['id'])}, {_text(o['conditions'].get('text') or None)}, "
            f"{_text(o['starts'] or campaign.starts)}, {_text(o['ends'] or campaign.ends)}, {_text(campaign.source or None)}, "
            f"{_text(o['label'])}, {_text(o['status'])}, {_text(o['closed_at'])}, {_lit(o['conditions'])}, {_lit(o)}, 'test')")
    return (f"insert into vehicle_campaigns (campaign_id, brand_id, name, starts, ends, source, source_ref, quota_units, "
            f"payload, seed_release_id) values ({_text(campaign.id)}, {_text(campaign.brand_id)}, {_text(campaign.name)}, "
            f"{_text(campaign.starts)}, {_text(campaign.ends)}, {_text(campaign.source)}, {_text(campaign.source_ref)}, "
            f"{'null' if campaign.quota_units is None else campaign.quota_units}, {_lit(payload)}, 'test'); "
            + "; ".join(opts))


OPTION = {"id": "cash", "label": "Cash", "status": "ACTIVE", "conditions": {"text": "x"}}
CAMPAIGN = {"id": "acme_q1", "brand_id": "acme", "name": "Q1", "starts": "2027-01-01", "ends": "2027-03-31",
            "options": [OPTION]}
CAMPAIGN_CASES = {
    "valid": CAMPAIGN,
    "ends before it starts": {**CAMPAIGN, "ends": "2026-12-31"},
    "no options": {**CAMPAIGN, "options": []},
    "duplicate option": {**CAMPAIGN, "options": [OPTION, OPTION]},
    "blank option id": {**CAMPAIGN, "options": [{**OPTION, "id": ""}]},
    "sold out without closed_at": {**CAMPAIGN, "options": [{**OPTION, "status": "SOLD_OUT"}]},
    "closed_at on an active option": {**CAMPAIGN, "options": [{**OPTION, "closed_at": "2027-02-01"}]},
    "sold out with closed_at": {**CAMPAIGN, "options": [{**OPTION, "status": "SOLD_OUT", "closed_at": "2027-02-01"}]},
    "option ends before it starts": {**CAMPAIGN, "options": [{**OPTION, "starts": "2027-02-01", "ends": "2027-01-15"}]},
    "booking window inverted": {**CAMPAIGN, "options": [{**OPTION, "conditions": {"booking_from": "2027-02-01",
                                                                                  "booking_to": "2027-01-01"}}]},
    "option restates the campaign quota": {**CAMPAIGN, "quota_units": 100,
                                           "options": [{**OPTION, "conditions": {"quota_units": 10}}]},
    "campaign quota alone": {**CAMPAIGN, "quota_units": 100},
}


@pytest.mark.parametrize("name", sorted(CAMPAIGN_CASES))
def test_campaigns_are_accepted_exactly_when_the_engine_accepts_them(db, name):
    campaign = _parse_campaign(CAMPAIGN_CASES[name], "<test>")
    expected = campaign.validate() == []
    ok, err = _write_ok(db, _campaign_sql(campaign))
    assert ok == expected, (name, campaign.validate(), err)


def test_campaign_options_and_promotions_stay_one_set(db):
    ok, err = _write_ok(db, "delete from vehicle_promotions where campaign_id = 'acme_q4' and option_id = 'loan'")
    assert not ok and "campaign_options" in err


# ---------------------------------------------------------------------------
# D. Spec facts: SpecLedger decides
# ---------------------------------------------------------------------------

def _fact_sql(fact: dict) -> str:
    return ("insert into vehicle_facts (fact_id, trim_id, field_key, value_state, value, unit, qualifiers, "
            "effective_from, effective_to, observed_at, claim_ids, verification_status, source, source_ref, "
            "source_locator, served_in_release, payload, seed_release_id) values ("
            f"{_text(fact['fact_id'])}, {_text(fact['trim_id'])}, {_text(fact['field_key'])}, {_text(fact['value_state'])}, "
            f"{_lit(fact['value'])}, {_text(fact['unit'])}, {_lit(fact['qualifiers'])}, {_text(fact['effective_from'])}, "
            f"{_text(fact['effective_to'])}, {_text(fact['observed_at'])}, {_lit(fact['claim_ids'])}, "
            f"{_text(fact['verification_status'])}, {_text(fact['source'])}, {_text(fact['source_ref'])}, "
            f"{_text(fact['source_locator'])}, false, {_lit(fact)}, 'test')")


def _python_accepts_fact(tree: Path, fact: dict) -> bool:
    if _is_price_field(fact["field_key"], fact["unit"]):
        return False   # SpecLedger.add_payload refuses before anything else
    ledger = SpecLedger.load(tree, YEAR, catalog=Catalog.load(tree, YEAR))
    spec = SpecFact(**{**fact, "value_state": ValueState(fact["value_state"]),
                       "verification_status": VerificationStatus(fact["verification_status"]),
                       "claim_ids": tuple(fact["claim_ids"])})
    if ledger._validate_fact(spec):
        return False
    existing = ledger._by_id.get(spec.fact_id)
    if existing is not None and existing != spec:
        return False
    ledger.facts.append(spec)
    return ledger.validate() == []


FACT = {"fact_id": "oem:new", "trim_id": T_TOP, "field_key": NUMBER_FIELD, "value_state": "KNOWN", "value": 4500,
        "unit": "mm", "qualifiers": {}, "effective_from": None, "effective_to": None, "observed_at": "2026-03-01",
        "claim_ids": [], "verification_status": "VERIFIED", "source": "oem", "source_ref": "https://example.test/s",
        "source_locator": ""}
FACT_CASES = {
    "valid": FACT,
    "provisional": {**FACT, "verification_status": "PROVISIONAL"},
    "no observed_at": {**FACT, "observed_at": None},
    "non-admin without source": {**FACT, "source": "", "source_ref": ""},
    "admin without source": {**FACT, "fact_id": "admin:x", "source": "", "source_ref": ""},
    "admin with half a source": {**FACT, "fact_id": "admin:x", "source": "oem", "source_ref": ""},
    "unknown with a value": {**FACT, "value_state": "UNKNOWN"},
    "not available without a value": {**FACT, "value_state": "NOT_AVAILABLE", "value": None, "unit": ""},
    "known without a value": {**FACT, "value": None},
    "ends before it starts": {**FACT, "effective_from": "2026-05-01", "effective_to": "2026-04-01"},
    "price word in field": {**FACT, "field_key": "vehicle.price_thb"},
    "price word in unit": {**FACT, "unit": "THB"},
    "conflicts with a seeded fact": {**FACT, "trim_id": T_BASE, "observed_at": "2026-01-01", "value": 4600},
    "agrees with a seeded fact": {**FACT, "trim_id": T_BASE, "observed_at": "2026-01-01", "value": 4500},
    "5.0 is not 5": {**FACT, "trim_id": T_BASE, "observed_at": "2026-01-01", "value": 4500.0},
    "same value on another start": {**FACT, "trim_id": T_BASE, "observed_at": "2026-01-02", "value": 4600},
    "unknown trim": {**FACT, "trim_id": "acme.a.g1.trim.ghost"},
}


@pytest.mark.parametrize("name", sorted(FACT_CASES))
def test_facts_are_accepted_exactly_when_the_engine_accepts_them(db, tree, name):
    fact = FACT_CASES[name]
    expected = _python_accepts_fact(tree, fact)
    ok, err = _write_ok(db, _fact_sql(fact))
    assert ok == expected, (name, expected, err)


def test_facts_are_revised_in_place_never_deleted_or_renamed(db):
    fid = "admin:" + T_PLUS + ":" + NUMBER_FIELD
    revised = f"update vehicle_facts set value = '4520', payload = payload || '{{\"value\": 4520}}' where fact_id = '{fid}'"
    ok, err = _write_ok(db, revised)
    assert ok, err   # APPEND_SPEC re-states a fact under its own id (ENGINE_INVENTORY §9.8)
    ok, err = _write_ok(db, f"update vehicle_facts set fact_id = 'admin:other', payload = payload || "
                            f"'{{\"fact_id\": \"admin:other\"}}' where fact_id = '{fid}'")
    assert not ok and "immutable" in err
    ok, err = _write_ok(db, f"delete from vehicle_facts where fact_id = '{fid}'")
    assert not ok and "not deleted" in err


# ---------------------------------------------------------------------------
# B. Models, variants, trims: Model / Variant / MarketTrim.validate decide
# ---------------------------------------------------------------------------

def _model_from_payload(p: dict) -> Model:
    return Model(id=p["id"], brand_id=p["brand_id"], name_en=p["name_en"],
                 body_type=taxonomy.BodyType.parse(p["body_type"]), cab_type=taxonomy.CabType.parse(p["cab_type"]),
                 registration_type=taxonomy.RegistrationType.parse(p["registration_type"]),
                 market_scope=taxonomy.MarketScope.parse(p["market_scope"]),
                 retail_status=taxonomy.RetailStatus.parse(p["retail_status"]),
                 retail_checked_at=p.get("retail_checked_at"), retail_source=p.get("retail_source") or "",
                 incomplete=bool(p.get("incomplete")))


MODEL_CASES = {
    "pickup with a cab": {"body_type": "PICKUP", "cab_type": "DOUBLE_CAB", "registration_type": "RY1"},
    "pickup without a cab": {"body_type": "PICKUP", "cab_type": "NOT_APPLICABLE", "registration_type": "RY3"},
    "sedan with a cab": {"cab_type": "SMART_CAB"},
    "single cab registered RY1": {"body_type": "PICKUP", "cab_type": "SINGLE_SMART", "registration_type": "RY1"},
    "sedan registered RY2": {"registration_type": "RY2"},
    "van registered RY3": {"body_type": "VAN", "registration_type": "RY3"},
    "current without evidence": {"retail_source": ""},
    "unverified without evidence": {"retail_status": "UNVERIFIED", "retail_source": "", "retail_checked_at": None},
    "body not set": {"body_type": "OTHER"},
    "body not set but incomplete": {"body_type": "OTHER", "incomplete": True},
}


@pytest.mark.parametrize("name", sorted(MODEL_CASES))
def test_models_are_accepted_exactly_when_the_engine_accepts_them(db, name):
    payload = json.loads(db.scalar(f"select payload::text from vehicle_models where canonical_id = '{MODEL_ID}'"))
    payload.update(MODEL_CASES[name])
    model = _model_from_payload(payload)
    expected = model.validate() == [] and (model.incomplete or model.body_type is not taxonomy.BodyType.OTHER)
    ok, err = _write_ok(db, f"update vehicle_models set payload = {_lit(payload)}, body_type = {_text(payload['body_type'])} "
                            f"where canonical_id = '{MODEL_ID}'")
    assert ok == expected, (name, model.validate(), err)


VARIANT_CASES = {
    "BEV with engine": {"powertrain": "BEV", "engine_cc": 1500, "battery_kwh": 60},
    "ICE with battery": {"battery_kwh": 1},
    "PHEV complete": {"powertrain": "PHEV", "engine_cc": 1500, "battery_kwh": 18},
    "PHEV without battery": {"powertrain": "PHEV", "engine_cc": 1500},
    "PHEV without battery, incomplete": {"powertrain": "PHEV", "engine_cc": 1500, "incomplete": True},
    "CKD made in CN": {"origin_country": "CN"},
    "CKD made in th": {"origin_country": " th "},
    "body override": {"overrides": {"body_type": "PICKUP"}},
    "price band split": {"price_min_thb": 450000, "price_max_thb": 650000},
    "price range inverted": {"price_min_thb": 650000, "price_max_thb": 550000},
    "price outside range": {"price_min_thb": 550000, "price_max_thb": 650000, "price_thb": 700000},
    "price inside range": {"price_min_thb": 550000, "price_max_thb": 650000, "price_thb": 600000},
    "only a minimum": {"price_min_thb": 550000, "price_thb": 500000},
    "zero engine counts as none": {"powertrain": "PHEV", "engine_cc": 0, "battery_kwh": 18},
}


@pytest.mark.parametrize("name", sorted(VARIANT_CASES))
def test_variants_are_accepted_exactly_when_the_engine_accepts_them(db, name):
    vid = "acme.a.g1.base"
    payload = json.loads(db.scalar(f"select payload::text from vehicle_variants where canonical_id = '{vid}'"))
    payload.update(VARIANT_CASES[name])
    variant = Variant(**{**{k: v for k, v in payload.items() if k not in ("powertrain", "drivetrain", "import_type",
                                                                          "aliases")},
                         "powertrain": taxonomy.Powertrain.parse(payload["powertrain"]),
                         "drivetrain": taxonomy.Drivetrain.parse(payload["drivetrain"]),
                         "import_type": taxonomy.ImportType.parse(payload["import_type"]),
                         "aliases": tuple(payload["aliases"])})
    expected = variant.validate() == []
    ok, err = _write_ok(db, f"update vehicle_variants set payload = {_lit(payload)}, powertrain = {_text(payload['powertrain'])} "
                            f"where canonical_id = '{vid}'")
    if ok and payload["powertrain"] != "ICE":
        pytest.fail("a trim under this variant is ICE; Catalog.validate would refuse the powertrain change too")
    assert ok == expected or (not ok and "trim_variant_powertrain" in err and expected), (name, variant.validate(), err)


TRIM_CASES = {
    "zero seats": {"seats": 0},
    "fractional seats": {"seats": 5.0},
    "string length": {"length_mm": "4500"},
    "bool seats": {"seats": True},
    "negative battery": {"battery_kwh": -1},
    "fractional battery": {"battery_kwh": 1.5},
    "zero legacy price": {"price_thb": 0},
    "wheelbase at length": {"wheelbase_mm": 4500},
    "wheelbase below length": {"wheelbase_mm": 2700},
    "engine code on ICE": {"engine_code": "2NR"},
}


@pytest.mark.parametrize("name", sorted(TRIM_CASES))
def test_catalog_trims_are_accepted_exactly_when_the_engine_accepts_them(db, name):
    payload = json.loads(db.scalar(f"select catalog_payload::text from vehicle_trims where canonical_id = '{T_TOP}'"))
    payload.update(TRIM_CASES[name])
    trim = MarketTrim(**{**{k: v for k, v in payload.items() if k not in ("powertrain", "drivetrain", "aliases",
                                                                          "source_refs")},
                         "powertrain": taxonomy.Powertrain.parse(payload["powertrain"]),
                         "drivetrain": taxonomy.Drivetrain.parse(payload["drivetrain"]),
                         "aliases": tuple(payload["aliases"]),
                         "source_refs": {k: tuple(v) for k, v in payload["source_refs"].items()}})
    expected = trim.validate() == []
    ok, err = _write_ok(db, f"update vehicle_trims set catalog_payload = {_lit(payload)} where canonical_id = '{T_TOP}'")
    assert ok == expected, (name, trim.validate(), err)


def test_bev_trim_cannot_carry_an_engine(db):
    payload = json.loads(db.scalar(f"select catalog_payload::text from vehicle_trims where canonical_id = 'acme.a.g2.trim.next_hev'"))
    for change, expected in (({"powertrain": "BEV"}, True), ({"powertrain": "BEV", "engine_cc": 1}, False),
                             ({"powertrain": "BEV", "engine_code": "X"}, False)):
        trim = MarketTrim(**{**{k: v for k, v in {**payload, **change}.items()
                                if k not in ("powertrain", "drivetrain", "aliases", "source_refs")},
                             "powertrain": taxonomy.Powertrain.parse(change["powertrain"]),
                             "drivetrain": taxonomy.Drivetrain.parse(payload["drivetrain"]),
                             "aliases": (), "source_refs": {}})
        assert (trim.validate() == []) == expected
        p = {**payload, **change}
        ok, err = db.try_sql(f"begin; set constraints all immediate; "
                             f"select public._vm_market_trim_problems({_lit(p)}) = '{{}}' as ok; rollback;")
        assert ok, err
        assert db.scalar(f"select public._vm_market_trim_problems({_lit(p)}) = '{{}}'") == ("t" if expected else "f")


def test_structure_rules(db):
    for sql, rule in (
        ("delete from vehicle_variants where model_id = 'acme.a'", None),          # FK from trims refuses first
        ("update vehicle_trims set variant_id = null, payload = jsonb_set(payload, '{specs,variant_id}', 'null'), "
         "catalog_payload = jsonb_set(catalog_payload, '{variant_id}', 'null') where model_id = 'acme.a'; "
         "delete from vehicle_variants where model_id = 'acme.a'", "model_has_variant"),
        ("update vehicle_trims set powertrain = 'HEV', payload = jsonb_set(jsonb_set(payload, '{specs,powertrain}', '\"HEV\"'), "
         "'{specs,engine_cc}', '1500'), catalog_payload = jsonb_set(catalog_payload, '{powertrain}', '\"HEV\"') "
         f"where canonical_id = '{T_BASE}'", "trim_variant_powertrain"),
    ):
        ok, err = _write_ok(db, sql)
        assert not ok, sql
        if rule:
            assert rule in err, err


# ---------------------------------------------------------------------------
# A. Identity
# ---------------------------------------------------------------------------

def test_ids_never_change(db):
    for table, key, column, value in (
        ("vehicle_brands", "acme", "canonical_id", "acme2"),
        ("vehicle_models", MODEL_ID, "brand_id", "other"),
        ("vehicle_trims", T_BASE, "canonical_id", T_BASE + "_x"),
        ("vehicle_trims", T_BASE, "generation_id", "acme.a.g2"),
    ):
        keycol = "canonical_id"
        ok, err = _write_ok(db, f"update {table} set {column} = '{value}' where {keycol} = '{key}'")
        assert not ok and "immutable" in err, (table, column, err)


@pytest.mark.parametrize("brand_id, accepted", [
    ("newbrand", True), ("new_brand_2", True), ("โตโยตา", True), ("โตโยต้า", False),
    ("NewBrand", False), ("new-brand", False), ("new.brand", False), ("new__brand", False), ("_new", False),
    ("new_", False), ("โต๊ะ", False), ("", False),
])
def test_brand_ids_have_the_slug_shape(db, brand_id, accepted):
    payload = {"id": brand_id, "name_en": "New", "name_th": "", "brand_segment": "MASS", "oem_group": "X",
               "brand_origin": "CN", "trim_detail": False, "aliases": [], "overrides": {}}
    ok, err = _write_ok(db, f"insert into vehicle_brands (canonical_id, slug, name_en, payload, served_as_of, seed_release_id) "
                            f"values ({_text(brand_id)}, {_text('slug-' + brand_id)}, 'New', {_lit(payload)}, '{AS_OF}', 'test')")
    assert ok == accepted, err
    if accepted:
        # Every shape-valid id here is also what vehreg.normalize.slug returns for it.
        from vehreg.normalize import slug
        assert slug(brand_id) == brand_id


def test_slug_shape_is_a_superset_of_slug_output(db):
    """The database checks the shape of an id segment, not that slug() would
    produce it: a corporate noise word is shape-valid but slug() drops it.
    Deriving ids stays in Python (one implementation, ENGINE_INVENTORY §2)."""
    from vehreg.normalize import slug
    assert slug("dual_motor") == "dual"
    assert db.scalar("select public._vm_slug_segment('dual_motor')") == "t"


def test_overlay_trims_follow_the_overlay_rules(db):
    good = {"id": "acme.a.g1.trim.sport_ice", "generation_id": "acme.a.g1", "name": "Sport", "powertrain": "ICE",
            "variant_id": None, "aliases": ["S"], "source_refs": {"oem": ["x"]}}
    base = ("insert into vehicle_trims (canonical_id, model_id, generation_id, variant_id, name, powertrain, status, "
            "payload, source_refs, served_as_of, seed_release_id) values ({id}, 'acme.a', 'acme.a.g1', null, {name}, "
            "{pt}, 'UNVERIFIED', {payload}, {refs}, '" + AS_OF + "', 'test')")

    def insert(specs: dict) -> tuple[bool, str]:
        payload = {"model_id": "acme.a", "specs": specs}
        return _write_ok(db, base.format(id=_text(specs["id"]), name=_text(specs["name"]), pt=_text(specs["powertrain"]),
                                         payload=_lit(payload), refs=_lit(specs["source_refs"])))

    assert insert(good)[0]
    assert not insert({**good, "id": "acme.a.g1.trim.Sport"})[0]
    assert not insert({**good, "id": "acme.a.g1.trim.sport2_ice", "powertrain": "UNKNOWN"})[0]
    assert not insert({**good, "id": "acme.a.g1.trim.sport3_ice", "source_refs": {}})[0]
    assert not insert({**good, "id": "acme.a.g1.trim.sport4_ice", "source_refs": {"oem": []}})[0]
    # An overlay trim cannot carry prices, facts, ECO evidence or decisions.
    ok, err = _write_ok(db, _insert_prices_sql([{**BASE_LIST, "trim_id": good["id"]}]))
    assert not ok and "price_on_catalog_trim" in err


# ---------------------------------------------------------------------------
# E. ECO evidence: ECOStickerSpec.validate + validate_against_catalog decide
# ---------------------------------------------------------------------------

ECO_CASES = {
    "as seeded": {},
    "seats disagree": {"seats": 7},
    "tyre disagrees": {"tire_size": "205/60 R16"},
    "powertrain disagrees": {"powertrain": "HEV"},
    "unknown powertrain": {"powertrain": "UNKNOWN"},
    "source not attached": {"source_ref": "eco-2"},
    "zero weight": {"declared_total_weight_kg": 0},
    "negative range": {"rated_range_km": -1},
    "price key": {"recommended_price_thb": 1},
}


@pytest.mark.parametrize("name", sorted(ECO_CASES))
def test_eco_evidence_is_accepted_exactly_when_the_engine_accepts_it(db, tree, name):
    payload = json.loads(db.scalar(f"select payload::text from vehicle_eco_evidence where trim_id = '{T_TOP}'"))
    payload.update(ECO_CASES[name])
    if any("price" in k for k in payload):
        expected = False   # ECOStickerSpecStore.add_payload refuses price keys
    else:
        spec = ECOStickerSpec(**{**payload, "powertrain": taxonomy.Powertrain.parse(payload["powertrain"])})
        store = ECOStickerSpecStore(YEAR, catalog=Catalog.load(tree, YEAR))
        store.records[T_TOP] = spec
        expected = spec.validate() == [] and store.validate_against_catalog() == []
    ok, err = _write_ok(db, f"update vehicle_eco_evidence set payload = {_lit(payload)}, source_ref = "
                            f"{_text(payload['source_ref'])} where trim_id = '{T_TOP}'")
    assert ok == expected, (name, err)


# ---------------------------------------------------------------------------
# F. Current-retail sets and lifecycle decisions: the sidecar writers decide
# ---------------------------------------------------------------------------

def _python_set(tree: Path, trim_ids: list[str], **kw) -> bool:
    try:
        replace_current_retail_set(data_dir=tree, year=YEAR, model_id=MODEL_ID, trim_ids=trim_ids,
                                   reviewer=kw.get("reviewer", "Owner"), reviewed_at="2026-10-02",
                                   source_ref=kw.get("source_ref", ""), write=False)
        return True
    except Exception:
        return False


@pytest.mark.parametrize("name, trim_ids, extra", [
    ("members of the model", [T_BASE, T_TOP], {}),
    ("a HISTORICAL-decided trim", [T_BASE, T_PLUS], {}),
    ("a trim of another generation of the model", [T_BASE, "acme.a.g2.trim.next_hev"], {}),
    ("unknown trim", [T_BASE, "acme.a.g1.trim.ghost"], {}),
    ("agent reviewer", [T_BASE], {"reviewer": "agent-proposed"}),
    ("ftp evidence", [T_BASE], {"source_ref": "ftp://x"}),
])
def test_current_retail_sets_are_accepted_exactly_when_the_engine_accepts_them(db, tree, name, trim_ids, extra):
    expected = _python_set(tree, trim_ids, **extra)
    payload = {"model_id": MODEL_ID, "trim_ids": sorted(trim_ids), "reviewer": extra.get("reviewer", "Owner"),
               "reviewed_at": "2026-10-02", "source_ref": extra.get("source_ref", ""), "notes": ""}
    ok, err = _write_ok(db, "update vehicle_current_retail_sets set "
                            f"trim_ids = array{json.dumps(sorted(trim_ids)).replace(chr(34), chr(39))}::text[], "
                            f"reviewer = {_text(payload['reviewer'])}, reviewed_at = '2026-10-02', "
                            f"source_ref = {_text(payload['source_ref'])}, payload = {_lit(payload)} "
                            f"where model_id = '{MODEL_ID}'")
    assert ok == expected, (name, expected, err)


def _decision_sql(trim_id: str, status: str, reviewer: str = "Owner") -> str:
    payload = {"trim_id": trim_id, "status": status, "reviewer": reviewer, "reviewed_at": "2026-10-02",
               "source_ref": "https://example.test/x", "notes": ""}
    return ("insert into vehicle_trim_lifecycle_decisions (trim_id, status, reviewer, reviewed_at, source_ref, notes, "
            f"payload, seed_release_id) values ({_text(trim_id)}, {_text(status)}, {_text(reviewer)}, '2026-10-02', "
            f"'https://example.test/x', '', {_lit(payload)}, 'test')")


def _python_decision(tree: Path, trim_id: str) -> bool:
    try:
        upsert_trim_lifecycle_disposition(data_dir=tree, year=YEAR, trim_id=trim_id, action="historical",
                                          reviewer="Owner", reviewed_at="2026-10-02",
                                          source_ref="https://example.test/x", write=False)
        return True
    except Exception:
        return False


def test_member_historical_decision_follows_the_engine(db, tree):
    # Parent CURRENT: the engine records it (the approved set keeps the trim CURRENT).
    assert _python_decision(tree, T_BASE) is True
    ok, err = _write_ok(db, _decision_sql(T_BASE, "HISTORICAL"))
    assert ok, err
    db.sql(f"delete from vehicle_trim_lifecycle_decisions where trim_id = '{T_BASE}'")

    # Parent not CURRENT: the engine refuses it for a member ...
    models = tree / str(YEAR) / "models" / "acme.json"
    payload = json.loads(models.read_text(encoding="utf-8"))
    payload["models"][0]["retail_status"] = "UNVERIFIED"
    models.write_text(json.dumps(payload), encoding="utf-8")
    assert _python_decision(tree, T_BASE) is False
    db.sql("update vehicle_models set payload = payload || '{\"retail_status\": \"UNVERIFIED\"}' "
           f"where canonical_id = '{MODEL_ID}'")
    ok, err = _write_ok(db, _decision_sql(T_BASE, "HISTORICAL"))
    assert not ok and "contradictory historical disposition" in err
    # ... and still accepts it for a non-member, as the engine does.
    db.sql(f"delete from vehicle_trim_lifecycle_decisions where trim_id = '{T_PLUS}'")
    assert _python_decision(tree, T_PLUS) is True
    ok, err = _write_ok(db, _decision_sql(T_PLUS, "HISTORICAL"))
    assert ok, err


def test_reopen_then_approve_in_one_write(db):
    """A batch may reopen a HISTORICAL decision and add the trim to the set together."""
    payload = {"model_id": MODEL_ID, "trim_ids": sorted([T_BASE, T_PLUS, T_TOP]), "reviewer": "Owner",
               "reviewed_at": "2026-10-02", "source_ref": "", "notes": ""}
    add = (f"update vehicle_current_retail_sets set trim_ids = array['{T_BASE}','{T_PLUS}','{T_TOP}']::text[], "
           f"reviewed_at = '2026-10-02', payload = {_lit(payload)} where model_id = '{MODEL_ID}'")
    ok, err = _write_ok(db, add)
    assert not ok and "unreopened HUMAN historical disposition" in err
    ok, err = _write_ok(db, f"delete from vehicle_trim_lifecycle_decisions where trim_id = '{T_PLUS}'; {add}")
    assert ok, err


def test_decisions_need_a_named_human(db):
    ok, err = _write_ok(db, _decision_sql(T_TOP, "CURRENT", reviewer="system"))
    assert not ok and "vm_rule_trim_lifecycle_row" in err


def test_a_member_trim_cannot_be_deleted(db):
    ok, err = _write_ok(db, f"delete from vehicle_trims where canonical_id = '{T_TOP}'")
    assert not ok


# ---------------------------------------------------------------------------
# Nobody bypasses the rules: service_role and browser roles alike
# ---------------------------------------------------------------------------

def test_service_role_cannot_bypass_the_rules(db):
    rid = db.scalar(f"select record_id from vehicle_price_ledger where trim_id = '{T_BASE}' and price_type = 'LIST_PRICE'")
    ok, err = db.try_sql(f"set role service_role; begin; delete from vehicle_price_ledger where record_id = '{rid}'; commit;")
    assert not ok and "append-only" in err
    ok, err = db.try_sql("set role service_role; begin; " + _fact_sql({**FACT, "observed_at": None}) + "; commit;")
    assert not ok and "vm_rule_fact_validate" in err
    ok, err = db.try_sql("set role service_role; begin; " + _insert_prices_sql(PRICE_CASES["same start, different amount"])
                         + "; commit;")
    assert not ok and "conflicting LIST_PRICE" in err


def test_browser_roles_still_cannot_write_and_the_check_is_private(db):
    for role in ("anon", "authenticated"):
        ok, err = db.try_sql(f"set role {role}; " + _insert_prices_sql([BASE_LIST]) + ";")
        assert not ok and "permission denied" in err
        ok, err = db.try_sql(f"set role {role}; select * from vehicle_engine_rules_check();")
        assert not ok and "permission denied" in err
