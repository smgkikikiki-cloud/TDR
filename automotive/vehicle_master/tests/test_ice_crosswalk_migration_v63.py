"""Market Track M3: the crosswalk/alias/redirect tables and RPCs (migration_v63)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.pg_cluster import apply_production_schema, pg  # noqa: F401

NEW_TABLES = ("ice_model_crosswalk", "ice_model_group_redirects", "ice_brand_aliases", "ice_known_model_groups")

ROOT = Path(__file__).resolve().parents[3]
MIGRATION_PATH = ROOT / "supabase" / "migration_v63_ice_model_crosswalk.sql"

UPSERT_SQL = (
    "select public.ice_crosswalk_upsert_match({model_group_id!r}, {canonical_model_id}, "
    "{match_method!r}, {score}, {status!r}, {master_version!r}, {fingerprint}, {reason!r})"
)


def _upsert(db, *, model_group_id, canonical_model_id=None, match_method="SERIES",
            score=0.99, status="AUTO", master_version="M5", fingerprint=None, reason="r"):
    sql = UPSERT_SQL.format(
        model_group_id=model_group_id,
        canonical_model_id="null" if canonical_model_id is None else repr(canonical_model_id),
        match_method=match_method, score="null" if score is None else score, status=status,
        master_version=master_version, fingerprint="null" if fingerprint is None else repr(fingerprint),
        reason=reason)
    return db.scalar(f"{sql}::text")


@pytest.fixture
def db(pg):
    apply_production_schema(pg, through=63)
    return pg


def _seed_vehicle_model(db, canonical_id: str, brand_id: str = "toyota") -> None:
    """Seed a minimal vehicle_brands/vehicle_models row pair that satisfies
    migration_v59's engine-rule constraints (vm_rule_model_identity/_validate/
    _segment). canonical_id must already be a valid child id of brand_id --
    e.g. 'toyota.model_a' (lowercase, underscore-separated, dot-joined; the
    vehicle_models slug grammar rejects hyphens)."""
    payload = (
        '{"id": "%s", "brand_id": "%s", "name_en": "%s", "body_type": "SEDAN", '
        '"cab_type": "NOT_APPLICABLE", "registration_type": "RY1", '
        '"market_scope": "CORE", "retail_status": "UNVERIFIED"}'
    ) % (canonical_id, brand_id, canonical_id)
    db.sql(
        f"insert into public.vehicle_brands "
        f"(canonical_id, slug, name_en, payload, served_as_of, seed_release_id) "
        f"values ('{brand_id}', '{brand_id}', 'Toyota', '{{}}'::jsonb, current_date, 'seed') "
        f"on conflict (canonical_id) do nothing;"
        f"insert into public.vehicle_models "
        f"(canonical_id, brand_id, slug, name_en, status, body_type, payload, served_as_of, seed_release_id) "
        f"values ('{canonical_id}', '{brand_id}', '{canonical_id}', '{canonical_id}', 'UNVERIFIED', 'SEDAN', "
        f"'{payload}'::jsonb, current_date, 'seed') on conflict (canonical_id) do nothing;")


def _insert_crosswalk_row(db, *, model_group_id, canonical_model_id=None, match_method="SERIES",
                           score=0.99, status="AUTO", master_version="M4", fingerprint=None, reason="r") -> None:
    canonical_sql = "null" if canonical_model_id is None else f"'{canonical_model_id}'"
    fingerprint_sql = "null" if fingerprint is None else f"'{fingerprint}'"
    db.sql(
        "insert into public.ice_model_crosswalk "
        "(model_group_id, canonical_model_id, match_method, score, status, master_version, "
        "decision_fingerprint, reason) values "
        f"('{model_group_id}', {canonical_sql}, '{match_method}', {score}, '{status}', "
        f"'{master_version}', {fingerprint_sql}, '{reason}');")


# ---------------------------------------------------------------------------
# Replay / privacy
# ---------------------------------------------------------------------------

def test_v63_replays_and_is_idempotent(db):
    ok, err = db.try_sql(MIGRATION_PATH.read_text(encoding="utf-8"))
    assert ok, err


@pytest.mark.parametrize("table", NEW_TABLES)
def test_every_new_table_is_private_to_service_role(db, table: str):
    assert db.scalar(f"select has_table_privilege('service_role','public.{table}','SELECT')") == "t"
    assert db.scalar(f"select has_table_privilege('service_role','public.{table}','INSERT')") == "t"
    for role in ("anon", "authenticated"):
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert db.scalar(
                f"select has_table_privilege('{role}','public.{table}','{privilege}')") == "f", (table, role, privilege)


def test_the_two_rpcs_are_service_role_only(db):
    for fn in (
        "ice_crosswalk_upsert_match(text,text,text,numeric,text,text,text,text)",
        "ice_crosswalk_apply_id_change(text,text,text,text,text)",
    ):
        assert db.scalar(f"select has_function_privilege('service_role','public.{fn}','EXECUTE')") == "t"
        for role in ("anon", "authenticated"):
            assert db.scalar(f"select has_function_privilege('{role}','public.{fn}','EXECUTE')") == "f"


def test_brand_alias_seed_rows_are_present(db):
    assert db.scalar(
        "select alias_group from public.ice_brand_aliases where brand = 'Deepal'") == "deepal_changan"
    assert db.scalar(
        "select alias_group from public.ice_brand_aliases where brand = 'Changan'") == "deepal_changan"
    assert db.scalar(
        "select alias_group from public.ice_brand_aliases where brand = 'MG Maxus'") == "maxus_mifa"
    assert db.scalar(
        "select alias_group from public.ice_brand_aliases where brand = 'MAXUS'") == "maxus_mifa"


# ---------------------------------------------------------------------------
# Cardinality (§14.2: many TDR models -> one Ice group; one TDR model -> at
# most one active Ice group)
# ---------------------------------------------------------------------------

def test_multiple_canonical_models_may_map_to_one_ice_group(db):
    _seed_vehicle_model(db, "toyota.model_a")
    _seed_vehicle_model(db, "toyota.model_b")
    _insert_crosswalk_row(db, model_group_id="group-1", canonical_model_id="toyota.model_a")
    ok, err = db.try_sql(
        "insert into public.ice_model_crosswalk "
        "(model_group_id, canonical_model_id, match_method, score, status, master_version) "
        "values ('group-1', 'toyota.model_b', 'SERIES', 0.99, 'AUTO', 'M5');")
    assert ok, err
    assert db.scalar("select count(*) from public.ice_model_crosswalk where model_group_id = 'group-1'") == "2"


def test_one_canonical_model_cannot_actively_map_to_two_ice_groups(db):
    _seed_vehicle_model(db, "toyota.model_a")
    _insert_crosswalk_row(db, model_group_id="group-1", canonical_model_id="toyota.model_a", status="AUTO")
    ok, err = db.try_sql(
        "insert into public.ice_model_crosswalk "
        "(model_group_id, canonical_model_id, match_method, score, status, master_version) "
        "values ('group-2', 'toyota.model_a', 'SERIES', 0.99, 'AUTO', 'M5');")
    assert not ok
    assert "duplicate key" in err or "violates unique constraint" in err


def test_a_proposed_row_for_an_already_active_canonical_model_elsewhere_is_still_allowed(db):
    # PROPOSED/REJECTED rows mentioning an elsewhere-active canonical model are not
    # restricted by the active-canonical unique index (only AUTO/APPROVED are) --
    # a candidate can be proposed for review without the constraint blocking the write.
    _seed_vehicle_model(db, "toyota.model_a")
    _insert_crosswalk_row(db, model_group_id="group-1", canonical_model_id="toyota.model_a", status="AUTO")
    ok, err = db.try_sql(
        "insert into public.ice_model_crosswalk "
        "(model_group_id, canonical_model_id, match_method, score, status, master_version) "
        "values ('group-2', 'toyota.model_a', 'NAME', 0.5, 'PROPOSED', 'M5');")
    assert ok, err


def test_only_one_no_candidate_row_per_model_group(db):
    _insert_crosswalk_row(db, model_group_id="group-1", canonical_model_id=None, status="PROPOSED")
    ok, err = db.try_sql(
        "insert into public.ice_model_crosswalk "
        "(model_group_id, canonical_model_id, match_method, score, status, master_version) "
        "values ('group-1', null, 'NAME', 0.1, 'PROPOSED', 'M5');")
    assert not ok
    assert "duplicate key" in err or "violates unique constraint" in err


# ---------------------------------------------------------------------------
# ice_crosswalk_upsert_match
# ---------------------------------------------------------------------------

def test_upsert_match_inserts_a_fresh_row(db):
    _seed_vehicle_model(db, "toyota.model_a")
    result = _upsert(db, model_group_id="group-1", canonical_model_id="toyota.model_a")
    assert '"applied": true' in result or '"applied":true' in result
    assert db.scalar(
        "select status from public.ice_model_crosswalk "
        "where model_group_id = 'group-1' and canonical_model_id = 'toyota.model_a'") == "AUTO"


def test_upsert_match_updates_an_existing_proposed_row(db):
    _seed_vehicle_model(db, "toyota.model_a")
    _upsert(db, model_group_id="group-1", canonical_model_id="toyota.model_a", status="PROPOSED", score=0.5)
    _upsert(db, model_group_id="group-1", canonical_model_id="toyota.model_a", status="AUTO", score=0.99)
    assert db.scalar(
        "select status from public.ice_model_crosswalk "
        "where model_group_id = 'group-1' and canonical_model_id = 'toyota.model_a'") == "AUTO"
    assert db.scalar("select count(*) from public.ice_model_crosswalk where model_group_id = 'group-1'") == "1"


def test_upsert_match_never_overwrites_an_approved_row(db):
    _seed_vehicle_model(db, "toyota.model_a")
    _insert_crosswalk_row(
        db, model_group_id="group-1", canonical_model_id="toyota.model_a", status="APPROVED", match_method="ADMIN")
    result = _upsert(db, model_group_id="group-1", canonical_model_id="toyota.model_a", status="AUTO", score=0.99)
    assert "protected_admin_row" in result
    assert db.scalar(
        "select status from public.ice_model_crosswalk "
        "where model_group_id = 'group-1' and canonical_model_id = 'toyota.model_a'") == "APPROVED"


def test_upsert_match_never_overwrites_an_admin_set_row_regardless_of_status(db):
    _seed_vehicle_model(db, "toyota.model_a")
    _insert_crosswalk_row(
        db, model_group_id="group-1", canonical_model_id="toyota.model_a", status="REJECTED", match_method="ADMIN")
    result = _upsert(db, model_group_id="group-1", canonical_model_id="toyota.model_a", status="AUTO", score=0.99)
    assert "protected_admin_row" in result
    assert db.scalar(
        "select status from public.ice_model_crosswalk "
        "where model_group_id = 'group-1' and canonical_model_id = 'toyota.model_a'") == "REJECTED"


def test_upsert_match_reports_a_conflict_without_raising_when_canonical_is_active_elsewhere(db):
    _seed_vehicle_model(db, "toyota.model_a")
    _insert_crosswalk_row(db, model_group_id="group-1", canonical_model_id="toyota.model_a", status="AUTO")
    result = _upsert(db, model_group_id="group-2", canonical_model_id="toyota.model_a", status="AUTO", score=0.99)
    assert "canonical_model_already_active_elsewhere" in result
    assert db.scalar(
        "select count(*) from public.ice_model_crosswalk where model_group_id = 'group-2'") == "0"


def test_upsert_match_supports_the_no_candidate_null_row(db):
    result = _upsert(db, model_group_id="group-1", canonical_model_id=None, status="PROPOSED",
                      match_method="NAME", score=0.1)
    assert '"applied": true' in result or '"applied":true' in result
    assert db.scalar(
        "select canonical_model_id is null from public.ice_model_crosswalk "
        "where model_group_id = 'group-1'") == "t"


# ---------------------------------------------------------------------------
# ice_crosswalk_apply_id_change (SKILL.md §3, VEHICLE_DB_V3.md §14.2 "5.")
# ---------------------------------------------------------------------------

APPLY_ID_CHANGE_SQL = (
    "select public.ice_crosswalk_apply_id_change({old!r}, {new!r}, {type!r}, {master_version!r}, {reason})"
)


def _apply_id_change(db, *, old, new, change_type, master_version="M5", reason=None):
    sql = APPLY_ID_CHANGE_SQL.format(
        old=old, new=new, type=change_type, master_version=master_version,
        reason="null" if reason is None else repr(reason))
    return db.scalar(f"{sql}::text")


def test_rename_moves_every_row_and_leaves_no_orphan(db):
    _seed_vehicle_model(db, "toyota.model_a")
    _insert_crosswalk_row(db, model_group_id="old-id", canonical_model_id="toyota.model_a", status="AUTO")
    _insert_crosswalk_row(db, model_group_id="old-id", canonical_model_id=None, status="PROPOSED")

    result = _apply_id_change(db, old="old-id", new="new-id", change_type="เปลี่ยนรหัส")
    assert '"moved": 2' in result or '"moved":2' in result

    assert db.scalar("select count(*) from public.ice_model_crosswalk where model_group_id = 'old-id'") == "0"
    assert db.scalar("select count(*) from public.ice_model_crosswalk where model_group_id = 'new-id'") == "2"
    assert db.scalar(
        "select new_model_group_id from public.ice_model_group_redirects where old_model_group_id = 'old-id'"
    ) == "new-id"


def test_merge_moves_rows_and_drops_a_colliding_duplicate_without_raising(db):
    _seed_vehicle_model(db, "toyota.model_a")
    _seed_vehicle_model(db, "toyota.model_b")
    # new-id already has model-a mapped (e.g. from the other merging old id).
    _insert_crosswalk_row(db, model_group_id="new-id", canonical_model_id="toyota.model_a", status="AUTO")
    _insert_crosswalk_row(db, model_group_id="old-id", canonical_model_id="toyota.model_a", status="PROPOSED")
    _insert_crosswalk_row(db, model_group_id="old-id", canonical_model_id="toyota.model_b", status="AUTO")

    result = _apply_id_change(db, old="old-id", new="new-id", change_type="รวม")
    assert "conflicts" in result

    assert db.scalar("select count(*) from public.ice_model_crosswalk where model_group_id = 'old-id'") == "0"
    rows = db.scalar("select count(*) from public.ice_model_crosswalk where model_group_id = 'new-id'")
    assert rows == "2"  # model-a (kept as-is, the merge duplicate dropped) + model-b (moved)


def test_split_creates_a_structure_proposal_and_leaves_the_old_mapping_untouched(db):
    _seed_vehicle_model(db, "toyota.model_a")
    _insert_crosswalk_row(db, model_group_id="old-id", canonical_model_id="toyota.model_a", status="AUTO")

    result = _apply_id_change(db, old="old-id", new="new-id", change_type="แยก")
    assert '"structure_proposals": 1' in result or '"structure_proposals":1' in result

    # The old mapping is untouched.
    assert db.scalar(
        "select status from public.ice_model_crosswalk "
        "where model_group_id = 'old-id' and canonical_model_id = 'toyota.model_a'") == "AUTO"
    # A new STRUCTURE proposal exists under the new id, pending human review.
    assert db.scalar(
        "select status from public.ice_model_crosswalk "
        "where model_group_id = 'new-id' and canonical_model_id = 'toyota.model_a'") == "PROPOSED"
    assert db.scalar(
        "select match_method from public.ice_model_crosswalk "
        "where model_group_id = 'new-id' and canonical_model_id = 'toyota.model_a'") == "ADMIN"
    # No redirect is recorded for a split -- the old id is not retired.
    assert db.scalar(
        "select count(*) from public.ice_model_group_redirects where old_model_group_id = 'old-id'") == "0"


def test_split_never_moves_registration_units_only_crosswalk_rows(db):
    # Sanity: the function never touches ice_reg_trend/ice_reg_province/etc at all --
    # it only reads/writes ice_model_crosswalk and ice_model_group_redirects.
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    fn_start = text.index("create or replace function public.ice_crosswalk_apply_id_change")
    fn_body = text[fn_start:text.index("$$;", fn_start)]
    for forbidden in ("ice_reg_", "ice_dims_", "ice_rim_", "ice_tyre_"):
        assert forbidden not in fn_body


def test_apply_id_change_rejects_an_unknown_type(db):
    ok, err = db.try_sql(
        "select public.ice_crosswalk_apply_id_change('old-id', 'new-id', 'bogus', 'M5', null);")
    assert not ok
    assert "invalid id_changes type" in err


# ---------------------------------------------------------------------------
# Scope guardrail
# ---------------------------------------------------------------------------

def test_migration_touches_nothing_outside_the_crosswalk_tables_and_its_vehicle_models_fk(db):
    text = MIGRATION_PATH.read_text(encoding="utf-8").lower()
    code = "\n".join(line.split("--", 1)[0] for line in text.splitlines())
    forbidden = (
        "vehicle_trims", "vehicle_facts", "current_vehicle", "current_market_trims",
        "current_price_ledger", "canonical_input_batches", "canonical_vehicle_releases",
        "ice_reg_", "ice_dims_", "ice_rim_", "ice_tyre_",
    )
    for token in forbidden:
        assert token not in code, token
    # The one intentional, read-only reference into Vehicle Master.
    assert "references public.vehicle_models" in code
