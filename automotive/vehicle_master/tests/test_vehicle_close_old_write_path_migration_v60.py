"""Phase 0 step 5: the legacy file/release write path is closed."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.pg_cluster import SUPABASE, apply_production_schema, pg  # noqa: F401
from tests.test_vehicle_engine_rules_migration_v59 import V59, seeded, tree  # noqa: F401

V60 = SUPABASE / "migration_v60_close_legacy_vehicle_write_path.sql"
ROOT = Path(__file__).resolve().parents[3]

READ_ONLY_TABLES = (
    "canonical_input_batches",
    "canonical_object_map",
    "canonical_write_commands",
    "canonical_publish_outbox",
    "canonical_vehicle_releases",
    "canonical_vehicle_state",
    "canonical_release_chunks",
    "canonical_brand_projection",
    "canonical_model_projection",
    "canonical_generation_projection",
    "canonical_market_trim_projection",
    "canonical_price_projection",
    "canonical_spec_projection",
)

CLOSED_RPCS = (
    ("publish_vehicle_release", "'{}'::jsonb"),
    ("begin_vehicle_release", "'{}'::jsonb"),
    ("stage_vehicle_release_chunk", "'x', 'brands', 0, 'x', '[]'::jsonb"),
    ("activate_vehicle_release", "'x'"),
    ("rollback_vehicle_release", "'x'"),
    ("prune_vehicle_releases", "1, interval '6 hours'"),
)

BOOTSTRAP_WRITERS = (
    "vehicle_master_seed_from_release(text,date)",
    "vehicle_master_seed_supplemental(text,date,text,jsonb)",
    "vehicle_master_finish_supplemental(text,date,jsonb)",
)

STUB_WORKFLOWS = (
    ".github/workflows/canonical-input.yml",
    ".github/workflows/enqueue-canonical-batch.yml",
    ".github/workflows/pricefeed.yml",
    ".github/workflows/vehicle-release.yml",
    ".github/workflows/retail-lineup-bootstrap-apply.yml",
    ".github/workflows/mark-canonical-batch-status.yml",
)


@pytest.fixture
def pre_v60(pg):
    pg.sql("alter role service_role bypassrls;")
    apply_production_schema(pg, through=59)
    return pg


@pytest.fixture
def db(pre_v60):
    ok, err = pre_v60.try_sql(V60.read_text(encoding="utf-8"))
    assert ok, err
    return pre_v60


def test_v60_replays_and_is_idempotent(db):
    ok, err = db.try_sql(V60.read_text(encoding="utf-8"))
    assert ok, err


def test_service_role_old_tables_are_select_only(db):
    for table in READ_ONLY_TABLES:
        assert db.scalar(f"select has_table_privilege('service_role','public.{table}','SELECT')") == "t"
        for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            assert db.scalar(
                f"select has_table_privilege('service_role','public.{table}','{privilege}')"
            ) == "f", (table, privilege)

    # Phase 1 explicitly reuses this as the DB-master change log.
    assert db.scalar(
        "select has_table_privilege('service_role','public.canonical_write_revisions','INSERT')"
    ) == "t"


def test_bootstrap_release_seed_writers_are_no_longer_executable(db):
    for signature in BOOTSTRAP_WRITERS:
        assert db.scalar(
            f"select has_function_privilege('service_role','public.{signature}','EXECUTE')"
        ) == "f", signature
    # The read-only validation helper stays available to the service role.
    assert db.scalar(
        "select has_function_privilege('service_role','public.vehicle_master_seed_check()','EXECUTE')"
    ) == "t"


@pytest.mark.parametrize("function,args", CLOSED_RPCS)
def test_old_release_rpcs_fail_loudly(db, function: str, args: str):
    ok, err = db.try_sql(f"set role service_role; select public.{function}({args}); reset role;")
    assert not ok
    assert "closed (Phase 0 step 5)" in err


def test_v60_refuses_to_strand_a_queued_batch(pre_v60):
    pre_v60.sql("""
      insert into public.canonical_input_batches
        (batch_key, source_kind, payload, payload_sha256, item_count, actor, status)
      values
        ('queued-at-cutover', 'ADMIN',
         '{"batch_id":"queued-at-cutover"}'::jsonb,
         repeat('a', 64), 1, 'test', 'QUEUED');
    """)
    ok, err = pre_v60.try_sql(V60.read_text(encoding="utf-8"))
    assert not ok
    assert "canonical_input_batches job(s) are still QUEUED/PROCESSING/STAGED" in err
    assert pre_v60.scalar(
        "select has_table_privilege('service_role','public.canonical_input_batches','INSERT')"
    ) == "t"


def test_v60_reads_vehicle_master_scope_and_refuses_release_drift(pre_v60):
    pre_v60.sql("""
      insert into public.vehicle_master_state
        (scope, seed_release_id, seed_as_of, seed_source_hash,
         seed_canonical_revision, release_counts)
      values
        ('vehicle_master', 'seed-release', date '2026-10-01',
         repeat('a', 64), 'seed-revision', '{}'::jsonb);
    """)
    ok, err = pre_v60.try_sql(V60.read_text(encoding="utf-8"))
    assert not ok
    assert (
        "Vehicle Master seed release seed-release does not match active legacy release <null>"
        in err
    )
    # The cutover gate fires before any legacy permissions are frozen.
    assert pre_v60.scalar(
        "select has_table_privilege('service_role','public.canonical_input_batches','INSERT')"
    ) == "t"


def test_legacy_writer_workflows_are_fail_fast_stubs():
    for relative in STUB_WORKFLOWS:
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "Legacy Vehicle DB write path is closed" in text, relative
        assert "schedule:" not in text, relative
        assert "git push" not in text, relative
        assert "tdr_bridge.publish" not in text, relative
        assert "canonical_input_worker.py pull" not in text, relative


def test_source_import_keeps_only_registration_ingest():
    """DLT registration uploads are out of scope for the cutover and keep
    importing; the workflow can no longer write vehreg/data or publish."""
    text = (ROOT / ".github/workflows/source-import.yml").read_text(encoding="utf-8")
    assert "import_worker.py run --limit 5 --registration-only" in text
    assert "contents: read" in text and "contents: write" not in text
    for forbidden in ("git push", "git commit", "publish_canonical", "tdr_bridge.publish",
                      "retail_lineup_compile_worker", "mark-committed", "finalize"):
        assert forbidden not in text, forbidden


_REGISTRATION_PRIVILEGES = """
  select 'table', c.relname, r.rolname, p.privilege,
         has_table_privilege(r.rolname, c.oid, p.privilege)
    from pg_class c join pg_namespace n on n.oid = c.relnamespace and n.nspname = 'public'
    cross join (values ('service_role'), ('authenticated'), ('anon')) r(rolname)
    cross join (values ('SELECT'), ('INSERT'), ('UPDATE'), ('DELETE')) p(privilege)
   where c.relkind in ('r', 'v') and (c.relname like 'registration%' or c.relname like 'import_run%')
  union all
  select 'function', p.oid::regprocedure::text, r.rolname, 'EXECUTE',
         has_function_privilege(r.rolname, p.oid, 'EXECUTE')
    from pg_proc p join pg_namespace n on n.oid = p.pronamespace and n.nspname = 'public'
    cross join (values ('service_role'), ('authenticated'), ('anon')) r(rolname)
   where p.proname like '%registration%'
   order by 1, 2, 3, 4
"""


def test_registration_paths_are_untouched_by_v60(pre_v60):
    before = pre_v60.rows(_REGISTRATION_PRIVILEGES)
    assert len(before) > 50
    ok, err = pre_v60.try_sql(V60.read_text(encoding="utf-8"))
    assert ok, err
    assert pre_v60.rows(_REGISTRATION_PRIVILEGES) == before
    for signature in ("tdr_replace_registration_period(text,text,jsonb,uuid,text)",
                      "ingest_registration_snapshot(text,date,text)"):
        assert pre_v60.scalar(
            f"select has_function_privilege('service_role','public.{signature}','EXECUTE')") == "t", signature
    # The DLT importer's write call still runs end to end as service_role.
    row = ('[{"registration_type": "RY1", "brand_name_raw": "TOYOTA", "model_name_raw": "YARIS ATIV", '
           '"registrations": 42, "mapping_method": "unmapped"}]')
    ok, err = pre_v60.try_sql("set role service_role; "
                              f"select public.tdr_replace_registration_period('2026-08', 'RY1', '{row}'::jsonb); reset role;")
    assert ok, err
    assert pre_v60.scalar("select sum(registrations) from registrations where period = '2026-08-01'") == "42"


def test_the_non_definer_projection_writer_is_closed_by_privileges(db):
    # apply_vehicle_serving_projection is not SECURITY DEFINER, so the table
    # privileges revoked above are what stop it.
    assert db.scalar("select prosecdef from pg_proc where proname = 'apply_vehicle_serving_projection'") == "f"
    assert db.scalar(
        "select has_table_privilege('service_role','public.canonical_object_map','INSERT')") == "f"


def test_v60_applies_cleanly_on_a_seeded_master(seeded):
    """Production's order: seeded master, v58 serving, v59 rules, then v60."""
    ok, err = seeded.try_sql(V59.read_text(encoding="utf-8"))
    assert ok, err
    views = ("current_vehicle_brands", "current_vehicle_models", "current_vehicle_generations",
             "current_market_trims", "current_price_ledger", "current_spec_facts")
    before = {view: seeded.rows(f"select to_jsonb(v)::text from public.{view} v order by 1") for view in views}
    active = seeded.scalar("select active_release_id from canonical_vehicle_state")
    ok, err = seeded.try_sql(V60.read_text(encoding="utf-8"))
    assert ok, err
    assert {view: seeded.rows(f"select to_jsonb(v)::text from public.{view} v order by 1") for view in views} == before
    assert seeded.scalar("select count(*) from vehicle_master_seed_check() where not ok") == "0"
    assert seeded.scalar("select count(*) from vehicle_serving_parity_check() where not ok") == "0"
    assert seeded.scalar("select count(*) from vehicle_engine_rules_check()") == "0"
    ok, err = seeded.try_sql(f"set role service_role; select public.activate_vehicle_release('{active}');")
    assert not ok and "closed (Phase 0 step 5)" in err
    ok, err = seeded.try_sql("set role service_role; update canonical_vehicle_state set activated_at = now();")
    assert not ok and "permission denied" in err
