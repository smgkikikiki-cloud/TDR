"""migration_v57 (Vehicle DB v3 Phase 0 step 2) against a real Postgres.

The master tables are seeded from one pinned release: serving identity/state
row-for-row from its projections, plus the master state the release does not
carry (variants, retracted prices, campaigns/options, unserved fact history,
ECO evidence, HUMAN sidecars, legacy ids) through the same
``tools.vehicle_master_seed.apply`` the CLI uses. These tests pin that the
seed is exact, idempotent, refuses a wrong pin or drifted content, that the
check reports parity and preserved state, and that nothing existing --
serving views, browser access -- changes.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from tests.pg_cluster import apply_production_schema, pg  # noqa: F401
from tdr_bridge.publish import RELEASE_SECTIONS
from tools import vehicle_master_seed as seed

RID = "vehicle-2026-aaaaaaaaaaaaaaaa"
RID_NEXT = "vehicle-2026-bbbbbbbbbbbbbbbb"
AS_OF = "2026-10-01"

BRAND = "toyota"
MODEL = "toyota.camry"
GEN = "toyota.camry.axvh70"
VARIANT = "toyota.camry.axvh70.2_5_hev"
TRIM = "toyota.camry.axvh70.trim.premium_hev"      # base-catalog trim
OVERLAY = "toyota.camry.axvh70.trim.sport_hev"     # overlay-only trim

ECO = {"trim_id": TRIM, "source_ref": "eco-1", "powertrain": "HEV", "seats": 5}
LIST_ROW = {"record_id": "a" * 24, "trim_id": TRIM, "amount_thb": 1_469_000,
            "price_type": "LIST_PRICE", "effective_from": "2026-01-01", "effective_to": None,
            "observed_at": "2026-01-01", "source": "admin", "source_ref": "", "source_document_id": "",
            "notes": "", "campaign_id": None, "option_id": None, "reference_price_thb": None,
            "retracted_at": None, "retraction_reason": "", "reviewed_by": ""}
RETRACTED_ROW = {**LIST_ROW, "record_id": "b" * 24, "amount_thb": 1_499_000,
                 "retracted_at": "2026-02-01", "retraction_reason": "typo", "reviewed_by": "Owner"}
SERVED_FACT = {"trim_id": TRIM, "fact_id": "admin:" + TRIM + ":vehicle.seats",
               "field_key": "vehicle.seats", "value_state": "KNOWN", "value": 5, "unit": "",
               "qualifiers": {}, "effective_from": None, "effective_to": None,
               "observed_at": "2026-01-01", "claim_ids": [], "verification_status": "VERIFIED",
               "source": "", "source_ref": "", "source_locator": ""}
PROVISIONAL_FACT = {**SERVED_FACT, "fact_id": "oem:" + TRIM + ":vehicle.seats",
                    "value": 7, "verification_status": "PROVISIONAL",
                    "source": "oem", "source_ref": "https://example.test/spec"}


def _release(rid: str = RID) -> dict:
    return {
        "schema_version": 1, "release_id": rid, "canonical_revision": f"sha-{rid}",
        "source_hash": rid.rsplit("-", 1)[-1], "as_of": AS_OF, "year": 2026,
        "historical_model_state": {"catalog_years": [2026], "model_year_baselines": [],
                                   "monthly_changes": []},
        "brands": [{"canonical_id": BRAND, "slug": "toyota", "name_en": "Toyota",
                    "name_th": "โตโยต้า", "origin_country": "JP", "payload": {"id": BRAND}}],
        "models": [{"canonical_id": MODEL, "brand_id": BRAND, "slug": "toyota-camry",
                    "name_en": "Camry", "generation_id": GEN, "status": "CURRENT",
                    "segment": "D", "body_type": "SEDAN", "retail_price_min": 1469000,
                    "retail_price_max": 1469000, "payload": {"id": MODEL, "powertrains": ["HEV"]}}],
        "generations": [{"canonical_id": GEN, "model_id": MODEL, "code": "AXVH70",
                         "segment": "D", "launched": "2024-01-01", "ended": None,
                         "payload": {"id": GEN}}],
        "market_trims": [
            {"canonical_id": TRIM, "model_id": MODEL, "generation_id": GEN, "variant_id": VARIANT,
             "name": "Premium", "powertrain": "HEV", "status": "CURRENT",
             "payload": {"specs": {"id": TRIM}, "ecosticker_evidence": ECO,
                         "comparable_specs": [SERVED_FACT]},
             "current_list_price": LIST_ROW, "campaign_quote": {"trim_id": TRIM, "campaign_options": []},
             "price_history": [LIST_ROW], "source_refs": {"ecosticker": ["eco-1"]}},
            {"canonical_id": OVERLAY, "model_id": MODEL, "generation_id": GEN, "variant_id": None,
             "name": "Sport", "powertrain": "HEV", "status": "UNVERIFIED",
             "payload": {"specs": {"id": OVERLAY}}, "current_list_price": None,
             "campaign_quote": {}, "price_history": [], "source_refs": {"oem": ["x"]}},
        ],
        "price_ledger": [LIST_ROW],
        "spec_facts": [SERVED_FACT],
    }


def _sections() -> dict[str, list[dict]]:
    return {
        "variants": [{"canonical_id": VARIANT, "payload": {
            "id": VARIANT, "generation_id": GEN, "name": "2.5 HEV", "powertrain": "HEV",
            "import_type": "CKD", "origin_country": "TH"}}],
        "catalog_trims": [{"canonical_id": TRIM, "payload": {"id": TRIM, "name": "Premium"}}],
        "prices": [{"record_id": r["record_id"], "payload": r} for r in (LIST_ROW, RETRACTED_ROW)],
        "campaigns": [{"campaign_id": "toyota.camry.2026q4", "payload": {
            "id": "toyota.camry.2026q4", "brand_id": BRAND, "name": "Q4", "starts": "2026-10-01",
            "ends": "2026-12-31", "source": "admin", "source_ref": "", "quota_units": None,
            "gifts": "", "notes": "",
            "options": [{"id": "default", "label": "", "starts": None, "ends": None,
                         "status": "ACTIVE", "closed_at": None, "notes": "",
                         "conditions": {"text": "booking in Oct", "booking_from": None,
                                        "booking_to": None, "delivery_by": None,
                                        "quota_units": None, "finance_required": None}}]}}],
        "facts": [{"fact_id": f["fact_id"], "payload": f} for f in (SERVED_FACT, PROVISIONAL_FACT)],
        "eco_evidence": [{"trim_id": TRIM, "payload": ECO}],
        "current_retail_sets": [{"model_id": MODEL, "payload": {
            "model_id": MODEL, "trim_ids": [TRIM], "reviewer": "Owner",
            "reviewed_at": "2026-09-27", "source_ref": "", "notes": ""}}],
        "trim_lifecycle_decisions": [{"trim_id": OVERLAY, "payload": {
            "trim_id": OVERLAY, "status": "HISTORICAL", "reviewer": "Owner",
            "reviewed_at": "2026-09-26", "source_ref": "https://example.test", "notes": ""}}],
        "model_operational_states": [],
        "legacy_identities": [{"payload": {
            "namespace": "legacy_tdr", "external_entity_type": "model",
            "external_id": "e1a0b9fd-2d57-477d-b13f-1647d36d0298",
            "canonical_entity_type": "model", "canonical_id": MODEL, "state": "active",
            "authority_basis": "explicit_review", "verified_at": "2026-09-09T06:06:07+00:00",
            "verified_by": "reviewer", "evidence": {}}}],
    }


def _lit(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, (dict, list)):
        return "'" + json.dumps(value, ensure_ascii=False).replace("'", "''") + "'::jsonb"
    return "'" + str(value).replace("'", "''") + "'"


def _rpc(db):
    def call(name: str, params: dict):
        args = ", ".join(f"{key} => {_lit(value)}" for key, value in params.items())
        result = db._psql(["-t", "-A"], f"select to_jsonb(public.{name}({args}))::text")
        if result.returncode != 0:
            raise RuntimeError(result.stderr)
        return json.loads(result.stdout.strip() or "null")
    return call


def _publish(db, release: dict) -> None:
    counts = {s: len(release[s]) for s in RELEASE_SECTIONS}
    manifest = {k: release[k] for k in ("schema_version", "release_id", "canonical_revision",
                                        "source_hash", "as_of", "year", "historical_model_state")}
    rpc = _rpc(db)
    rpc("begin_vehicle_release", {"manifest": {**manifest, "counts": counts}})
    for section in RELEASE_SECTIONS:
        if release[section]:
            rows = release[section]
            rpc("stage_vehicle_release_chunk", {
                "p_release_id": release["release_id"], "p_section": section, "p_chunk_index": 0,
                "p_chunk_hash": hashlib.sha256(json.dumps(rows).encode()).hexdigest(),
                "p_rows": rows})
    rpc("activate_vehicle_release", {"p_release_id": release["release_id"]})


def _check(db) -> dict[tuple[str, str], tuple[str, bool]]:
    rows = db.rows("select section, check_name, actual, ok from public.vehicle_master_seed_check()")
    return {(r[0], r[1]): (r[2], r[3] == "t") for r in rows}


@pytest.fixture
def db(pg):
    apply_production_schema(pg)
    _publish(pg, _release())
    return pg


def _serving_snapshot(db) -> list[list[str]]:
    return db.rows(
        "select viewname, md5(definition) from pg_views where schemaname = 'public' "
        "and viewname in ('current_vehicle_brands','current_vehicle_models',"
        "'current_vehicle_generations','current_market_trims','current_price_ledger',"
        "'current_spec_facts') order by 1") + db.rows(
        "select (select count(*) from current_vehicle_brands), (select count(*) from current_vehicle_models),"
        " (select count(*) from current_market_trims), (select count(*) from current_price_ledger),"
        " (select count(*) from current_spec_facts),"
        " (select md5(string_agg(payload::text, '' order by canonical_id)) from current_market_trims)")


def test_seed_is_exact_and_leaves_serving_untouched(db):
    before = _serving_snapshot(db)
    seed.apply(_sections(), release_id=RID, as_of=AS_OF, rpc=_rpc(db), log=lambda _: None)

    checks = _check(db)
    failed = {key: value for key, value in checks.items() if not value[1]}
    assert failed == {}
    # Release parity in both directions, every section.
    for section in ("brands", "models", "generations", "market_trims", "price_ledger", "spec_facts"):
        assert checks[(section, "ids_missing_from_master")][0] == "0"
        assert checks[(section, "ids_not_in_release")][0] == "0"
        assert checks[(section, "served_values_differ")][0] == "0"
    # Preserved state the release does not serve.
    assert checks[("price_ledger", "retracted_rows_not_served")][0] == "1"
    assert checks[("spec_facts", "history_rows_not_served")][0] == "1"
    assert checks[("spec_facts", "provisional_rows")][0] == "1"
    assert checks[("market_trims", "overlay_origin")][0] == "1"
    assert checks[("market_trims", "catalog_origin")][0] == "1"
    assert checks[("promotions", "options")][0] == "1"
    assert checks[("variants", "rows")][0] == "1"
    assert checks[("legacy_identities", "rows")][0] == "1"

    assert db.rows(f"select in_release, retraction_reason, reviewed_by from vehicle_price_ledger "
                   f"where record_id = '{'b' * 24}'") == [["f", "typo", "Owner"]]
    assert db.rows("select description, valid_from, valid_to, option_status from vehicle_promotions") == [
        ["booking in Oct", "2026-10-01", "2026-12-31", "ACTIVE"]]
    assert db.rows(f"select served_as_of, generation_id from vehicle_models") == [[AS_OF, GEN]]
    assert db.rows("select seed_release_id, seed_as_of from vehicle_master_state") == [[RID, AS_OF]]

    assert _serving_snapshot(db) == before


def test_release_stage_is_idempotent_and_refuses_a_wrong_pin(db):
    rpc = _rpc(db)
    with pytest.raises(RuntimeError, match="not the pinned"):
        rpc("vehicle_master_seed_from_release", {"p_release_id": RID, "p_as_of": "2026-09-30"})
    with pytest.raises(RuntimeError, match="unknown release"):
        rpc("vehicle_master_seed_from_release", {"p_release_id": RID_NEXT, "p_as_of": AS_OF})
    assert db.scalar("select count(*) from vehicle_trims") == "0"

    first = rpc("vehicle_master_seed_from_release", {"p_release_id": RID, "p_as_of": AS_OF})
    again = rpc("vehicle_master_seed_from_release", {"p_release_id": RID, "p_as_of": AS_OF})
    assert first["status"] == "seeded" and again["status"] == "already_seeded"
    assert db.scalar("select count(*) from vehicle_trims") == "2"

    # Once pinned, no other release can seed over it -- even the active one.
    _publish(db, _release(RID_NEXT))
    with pytest.raises(RuntimeError, match="already seeded from"):
        rpc("vehicle_master_seed_from_release", {"p_release_id": RID_NEXT, "p_as_of": AS_OF})


def test_supplemental_refuses_drift_and_accepts_an_identical_resend(db):
    rpc = _rpc(db)
    rpc("vehicle_master_seed_from_release", {"p_release_id": RID, "p_as_of": AS_OF})
    sections = _sections()
    send = lambda name, rows: rpc("vehicle_master_seed_supplemental", {  # noqa: E731
        "p_release_id": RID, "p_as_of": AS_OF, "p_section": name, "p_rows": rows})

    unserved_live = {**LIST_ROW, "record_id": "c" * 24, "amount_thb": 1}
    with pytest.raises(RuntimeError, match="non-retracted price .* is not in the seeded release"):
        send("prices", [{"record_id": unserved_live["record_id"], "payload": unserved_live}])
    changed_fact = {**SERVED_FACT, "value": 6}
    with pytest.raises(RuntimeError, match="already exists with different content"):
        send("facts", [{"fact_id": changed_fact["fact_id"], "payload": changed_fact}])
    with pytest.raises(RuntimeError, match="is not in the seeded release"):
        send("catalog_trims", [{"canonical_id": GEN + ".trim.ghost", "payload": {}}])
    with pytest.raises(RuntimeError, match="unknown supplemental section"):
        send("options", [])

    send("prices", sections["prices"])
    send("prices", sections["prices"])  # a retried chunk is a no-op
    assert db.scalar("select count(*) from vehicle_price_ledger") == "2"

    for name in seed.SECTIONS:
        send(name, sections[name])
    expected = seed.expected_counts(sections)
    with pytest.raises(RuntimeError, match="supplemental prices has 2 rows, expected 3"):
        rpc("vehicle_master_finish_supplemental",
            {"p_release_id": RID, "p_as_of": AS_OF, "p_expected": {**expected, "prices": 3}})
    rpc("vehicle_master_finish_supplemental", {"p_release_id": RID, "p_as_of": AS_OF, "p_expected": expected})
    with pytest.raises(RuntimeError, match="already finished"):
        send("variants", sections["variants"])


def test_check_fails_when_the_master_or_the_serving_pointer_drifts(db):
    seed.apply(_sections(), release_id=RID, as_of=AS_OF, rpc=_rpc(db), log=lambda _: None)
    db.sql(f"update vehicle_trims set status = 'HISTORICAL' where canonical_id = '{TRIM}'")
    checks = _check(db)
    assert checks[("market_trims", "served_values_differ")] == ("1", False)

    _publish(db, _release(RID_NEXT))
    checks = _check(db)
    assert checks[("state", "release_still_active")] == ("0", False)


def test_check_reports_an_unseeded_master(db):
    assert _check(db) == {("state", "seeded"): ("0", False)}


def test_master_tables_and_seed_functions_are_closed_to_browser_roles(db):
    for role in ("anon", "authenticated"):
        ok, err = db.try_sql(f"set role {role}; select count(*) from public.vehicle_trims;")
        assert not ok and "permission denied" in err
        ok, err = db.try_sql(f"set role {role}; select public.vehicle_master_seed_check();")
        assert not ok and "permission denied" in err
        ok, err = db.try_sql(
            f"set role {role}; select public.vehicle_master_seed_from_release('{RID}', '{AS_OF}');")
        assert not ok and "permission denied" in err
    ok, err = db.try_sql("set role service_role; select count(*) from public.vehicle_master_seed_check();")
    assert ok, err


# ---------------------------------------------------------------------------
# Seed tool, without a database
# ---------------------------------------------------------------------------

def test_cross_check_requires_live_prices_to_equal_the_served_ledger():
    sections, release = _sections(), _release()
    seed.cross_check_release(sections, release)
    release["price_ledger"] = []
    with pytest.raises(seed.SeedError, match="1 extra, 0 missing"):
        seed.cross_check_release(sections, release)


def test_cross_check_requires_every_served_fact_in_the_fact_store():
    sections, release = _sections(), _release()
    sections["facts"] = sections["facts"][1:]
    with pytest.raises(seed.SeedError, match="1 served facts are not in the fact store"):
        seed.cross_check_release(sections, release)


def test_verify_rebuild_refuses_a_tree_that_does_not_reproduce_the_release():
    release = _release()
    seed.verify_rebuild(dict(release, counts={}), dict(release, counts={}))
    with pytest.raises(seed.SeedError, match="source_hash"):
        seed.verify_rebuild(dict(release, counts={}), dict(release, counts={}, source_hash="f" * 64))


def test_apply_sends_release_then_every_section_in_chunks_then_finish():
    calls, expected = [], {}
    sections = _sections()
    sections["facts"] = [{"fact_id": f"f{i}", "payload": {}} for i in range(seed.CHUNK_SIZE + 1)]
    seed.apply(sections, release_id=RID, as_of=AS_OF,
               rpc=lambda name, params: calls.append((name, params.get("p_section"))) or expected.update(params.get("p_expected") or {}) or {},
               log=lambda _: None)
    assert calls[0] == ("vehicle_master_seed_from_release", None)
    assert calls[-1] == ("vehicle_master_finish_supplemental", None)
    sent = [section for name, section in calls[1:-1]]
    assert sent.count("facts") == 2
    # Empty sections send nothing; finish still verifies their zero count.
    assert [s for i, s in enumerate(sent) if s not in sent[:i]] == [
        name for name in seed.SECTIONS if sections[name]]
    assert expected["model_operational_states"] == 0 and expected["facts"] == seed.CHUNK_SIZE + 1
