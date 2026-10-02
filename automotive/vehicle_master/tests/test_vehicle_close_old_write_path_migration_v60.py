"""Phase 0 step 5: the legacy file/release write path is closed."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.pg_cluster import SUPABASE, apply_production_schema, pg  # noqa: F401

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
    ".github/workflows/source-import.yml",
    ".github/workflows/pricefeed.yml",
    ".github/workflows/vehicle-release.yml",
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
