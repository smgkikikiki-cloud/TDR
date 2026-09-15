"""Regression coverage for supabase/migration_v28_external_identity_registry_operational.sql.

There is no dockerized/live Postgres available to this repository's test
suite (see docs/vehicle-platform/status/CURRENT.md's known parity gaps), so
this is a source-text regression test over the migration file itself —
the same pattern scripts/check-admin-parity.ts already uses for other
migrations. It cannot prove the DDL executes correctly against a live
database, but it can catch someone silently reverting, weakening, or
touching more than intended in this specific migration.
"""
from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).resolve().parents[3] / "supabase" / "migration_v28_external_identity_registry_operational.sql"
)
ORIGINAL_CONSTRAINT_PATH = (
    Path(__file__).resolve().parents[3] / "supabase" / "migration_v12_canonical_write_pipeline.sql"
)


def _migration_text() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8")


def test_migration_file_exists():
    assert MIGRATION_PATH.is_file()


def test_migration_drops_the_global_verified_target_index():
    text = _migration_text()
    assert "drop index if exists canonical_object_map_verified_target_uq" in text


def test_migration_does_not_touch_any_table_data():
    text = _migration_text().lower()
    for forbidden in ("insert into", "update ", "delete from", "truncate"):
        assert forbidden not in text, f"migration_v28 must not touch row data (found {forbidden!r})"


def test_migration_does_not_touch_the_source_key_uniqueness_constraint():
    text = _migration_text().lower()
    # The source-key constraint lives in migration_v12 and must remain
    # untouched by v28 — v28 may only DROP the one named global target
    # index; it must contain no constraint-altering DDL at all (a mention
    # of the constraint's name in an explanatory SQL comment is fine and
    # expected — only actual DDL keywords are checked here).
    for forbidden in ("add constraint", "drop constraint", "create table", "alter table"):
        assert forbidden not in text, f"migration_v28 must not contain {forbidden!r}"


def test_migration_v12_still_defines_the_source_key_uniqueness_constraint_unchanged():
    # Confirms migration_v28 is additive/subtractive only for the target
    # index, not a rewrite of migration_v12's own source-key constraint.
    text = ORIGINAL_CONSTRAINT_PATH.read_text(encoding="utf-8")
    assert "unique (source_table, source_id, canonical_entity_type)" in text
    assert (
        "check ((status = 'verified' and canonical_id is not null and verified_at is not null)\n"
        "      or status <> 'verified')" in text
    )


def test_migration_preserves_the_per_row_correctness_check_by_not_touching_it():
    text = _migration_text().lower()
    assert "check ((status" not in text, (
        "migration_v28 must not redefine canonical_object_map's per-row "
        "verified/canonical_id/verified_at correctness check — only drop the "
        "global target index"
    )
