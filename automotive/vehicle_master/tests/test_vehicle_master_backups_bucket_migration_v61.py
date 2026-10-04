"""Phase 0 step 6: the private vehicle-master-backups Storage bucket."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.pg_cluster import SUPABASE, apply_production_schema, pg  # noqa: F401

V61 = SUPABASE / "migration_v61_vehicle_master_backups_bucket.sql"
ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def db(pg):
    apply_production_schema(pg, through=61)
    return pg


def test_v61_replays_and_is_idempotent(db):
    ok, err = db.try_sql(V61.read_text(encoding="utf-8"))
    assert ok, err


def test_bucket_exists_and_is_private(db):
    assert db.scalar(
        "select public from storage.buckets where id = 'vehicle-master-backups'"
    ) == "f"


def test_bucket_has_a_size_limit_and_restricted_mime_types(db):
    assert db.scalar(
        "select (file_size_limit is not null) from storage.buckets "
        "where id = 'vehicle-master-backups'"
    ) == "t"
    assert db.scalar(
        "select (allowed_mime_types is not null) from storage.buckets "
        "where id = 'vehicle-master-backups'"
    ) == "t"


def _sql_statements_only(text: str) -> str:
    """Strip '--' line comments so prose in comments can't fool a code check."""
    return "\n".join(line.split("--", 1)[0] for line in text.splitlines()).lower()


def test_migration_grants_nothing_to_browser_roles():
    code = _sql_statements_only(V61.read_text(encoding="utf-8"))
    assert "anon" not in code
    assert "authenticated" not in code
    assert "grant" not in code
    assert "public = true" not in code
    assert "public, true" not in code


def test_migration_touches_only_storage_buckets():
    code = _sql_statements_only(V61.read_text(encoding="utf-8"))
    # Phase 0 step 6 must not reopen the closed legacy write path (step 5) or
    # touch any vehicle_* master table -- this migration only inserts one row
    # describing the backup bucket.
    forbidden = (
        "vehicle_brands", "vehicle_models", "vehicle_trims", "vehicle_facts",
        "vehicle_price_ledger", "canonical_input_batches", "canonical_vehicle_releases",
        "registrations", "registration_",
    )
    for token in forbidden:
        assert token not in code, token
    assert "storage.buckets" in code
