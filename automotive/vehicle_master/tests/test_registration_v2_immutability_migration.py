"""Regression coverage for
supabase/migration_v30_registration_v2_immutable_observations.sql.

Source-text regression only, the same pattern used for every other migration
in this repository (no dockerized/live Postgres in this test suite)."""
from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).resolve().parents[3] / "supabase"
    / "migration_v30_registration_v2_immutable_observations.sql"
)


def _text() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8")


def test_migration_file_exists():
    assert MIGRATION_PATH.is_file()


def test_revokes_update_and_delete_from_service_role():
    text = _text().lower()
    assert "revoke update, delete on table public.registration_observations_v2 " \
        "from service_role" in text


def test_still_grants_select_and_insert_to_service_role():
    text = _text().lower()
    assert "grant select, insert on table public.registration_observations_v2 " \
        "to service_role" in text
    # And crucially does NOT also grant update/delete back.
    assert "grant select, insert, update, delete on table public.registration_observations_v2" \
        not in text


def test_adds_a_before_update_or_delete_trigger():
    text = _text().lower()
    assert "before update or delete on public.registration_observations_v2" in text
    assert "create trigger registration_observations_v2_immutable" in text


def test_trigger_function_unconditionally_raises():
    text = _text().lower()
    assert "raise exception" in text


def test_does_not_touch_facts_or_review_table_grants():
    # Only the raw observation table's grants/trigger change -- facts/review
    # remain freely upsertable (derived data), per the module's own
    # "fact/review rows remain derived" rule. A prose mention explaining
    # that is fine and expected; only actual DDL against those tables is
    # checked here.
    text = _text().lower()
    for forbidden in ("on table public.registration_facts_v2",
                      "on table public.registration_resolution_review_v2",
                      "alter table public.registration_facts_v2",
                      "alter table public.registration_resolution_review_v2"):
        assert forbidden not in text


def test_does_not_touch_any_existing_production_object():
    text = _text().lower()
    for obj in ("public.registrations", "public.registration_brand_aliases",
               "public.registration_model_aliases", "public.match_registration_model"):
        assert obj not in text


def test_no_grant_to_anon_or_authenticated():
    text = _text().lower()
    assert "to anon" not in text
    assert "to authenticated" not in text
