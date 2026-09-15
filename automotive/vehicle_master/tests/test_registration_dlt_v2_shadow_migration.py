"""Regression coverage for supabase/migration_v29_registration_dlt_v2_shadow.sql.

No dockerized/live Postgres is available to this repository's test suite
(see docs/vehicle-platform/status/CURRENT.md's known parity gaps), so this is
a source-text regression test over the migration file itself - the same
pattern already used for other migrations
(scripts/check-admin-parity.ts, the now-superseded
tests/test_external_identity_registry_migration.py). It cannot prove the DDL
executes correctly against a live database, but it can catch someone
silently touching the existing production registration path, or granting
these shadow tables to anon/authenticated.
"""
from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).resolve().parents[3] / "supabase"
    / "migration_v29_registration_dlt_v2_shadow.sql"
)

NEW_TABLES = (
    "registration_observations_v2",
    "registration_facts_v2",
    "registration_resolution_review_v2",
)

#: Existing production registration objects this migration must never
#: mention in a DDL-altering way (a comment/prose mention is fine and
#: expected - "does not touch registrations" - only actual statements
#: against these names are checked below).
EXISTING_PRODUCTION_OBJECTS = (
    "public.registrations", "public.registration_brand_aliases",
    "public.registration_model_aliases", "public.match_registration_model",
    "public.ingest_registration_snapshot", "public.registration_monthly_model",
    "public.registration_monthly_brand", "public.registration_model_mom",
    "public.registration_analytics_coverage",
)


def _text() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8")


def test_migration_file_exists():
    assert MIGRATION_PATH.is_file()


def test_creates_exactly_the_three_shadow_tables():
    text = _text()
    for table in NEW_TABLES:
        assert f"create table if not exists public.{table}" in text, table


def test_does_not_alter_or_recreate_any_existing_production_object():
    text = _text().lower()
    for obj in EXISTING_PRODUCTION_OBJECTS:
        obj = obj.lower()
        for verb in ("alter table " + obj, "drop table " + obj,
                    "create table if not exists " + obj,
                    "create or replace function " + obj + "(",
                    "create or replace view " + obj,
                    "drop view " + obj, "drop function " + obj):
            assert verb not in text, (
                f"migration_v29 must not touch existing object via {verb!r}")


def test_does_not_grant_anything_to_anon_or_authenticated():
    # No "to anon" / "to authenticated" grant anywhere in this migration at
    # all - every new object here is service_role-only, unlike the existing
    # current_vehicle_* views this repository does expose publicly.
    text = _text().lower()
    assert "to anon" not in text
    assert "to authenticated" not in text


def test_every_new_table_revokes_from_anon_and_authenticated():
    text = _text().lower()
    for table in NEW_TABLES:
        assert (f"revoke all on table public.{table} from anon, authenticated"
               in text), table


def test_every_new_table_grants_only_to_service_role():
    text = _text().lower()
    for table in NEW_TABLES:
        assert (f"grant select, insert, update, delete on table public.{table} "
               "to service_role" in text), table


def test_every_new_table_enables_row_level_security():
    text = _text().lower()
    for table in NEW_TABLES:
        assert f"alter table public.{table} enable row level security" in text


def test_facts_table_canonical_id_column_is_text_not_uuid():
    text = _text().lower()
    # A fact must address the canonical Vehicle Master id directly as text,
    # never a legacy models.id uuid - this greps the column definition line
    # itself, not just the word "text" appearing anywhere in the file.
    assert "canonical_id       text not null" in text


def test_grain_is_constrained_to_the_three_known_values():
    text = _text()
    assert "check (grain in ('BRAND', 'MODEL', 'VARIANT'))" in text


def test_deterministic_ids_not_random_uuids():
    text = _text().lower()
    # Every primary key here is `text`, never `uuid ... default gen_random_uuid()`
    # - ids come from vehreg.registration_observation.observation_id, a pure
    # function of source identity, not a fresh random value per insert.
    assert "gen_random_uuid" not in text
