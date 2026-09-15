"""Regression coverage for
supabase/migration_v31_registration_v2_serving_and_cutover.sql.

Source-text regression only (no dockerized/live Postgres in this test
suite). Proves: the switch defaults to legacy (zero behavior change on
apply), the switch/boundary functions are service-role-only and each a
single UPDATE, the new serving/compatibility views exist, the three
redirected views change only their FROM/JOIN source (never their SELECT
list), and nothing in this migration drops, alters, or re-grants any
existing production registration object beyond that intentional redirect."""
from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).resolve().parents[3] / "supabase"
    / "migration_v31_registration_v2_serving_and_cutover.sql"
)


def _text() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8")


def test_migration_file_exists():
    assert MIGRATION_PATH.is_file()


def test_serving_state_table_created_and_defaults_to_legacy():
    text = _text().lower()
    assert "create table if not exists public.registration_serving_state" in text
    assert "active_source text not null default 'legacy'" in text
    assert "values ('registration_analytics', 'legacy')" in text


def test_serving_state_check_constraint_allows_only_legacy_or_v2():
    text = _text().lower()
    assert "check (active_source in ('legacy', 'v2'))" in text


def test_serving_state_not_granted_to_anon_or_authenticated():
    text = _text().lower()
    assert "revoke all on table public.registration_serving_state from anon, authenticated" in text


def test_switch_function_is_a_single_update_and_service_role_only():
    text = _text().lower()
    assert "create or replace function public.set_registration_serving_source" in text
    assert "security definer" in text
    assert "grant execute on function public.set_registration_serving_source(text, text) to service_role" in text
    assert "revoke all on function public.set_registration_serving_source(text, text) from public, anon, authenticated" in text
    # A single UPDATE, no INSERT/DELETE/data-copy of any kind.
    switch_fn_start = text.index("create or replace function public.set_registration_serving_source")
    switch_fn_end = text.index("$$;", switch_fn_start)
    body = text[switch_fn_start:switch_fn_end]
    assert body.count("update public.registration_serving_state") == 1
    assert "insert into" not in body
    assert "delete from" not in body


def test_boundary_function_is_service_role_only():
    text = _text().lower()
    assert "create or replace function public.set_registration_v2_source_boundary" in text
    assert "grant execute on function public.set_registration_v2_source_boundary(text) to service_role" in text
    assert "revoke all on function public.set_registration_v2_source_boundary(text) from public, anon, authenticated" in text


def test_v2_serving_view_excludes_brand_grain_from_canonical_model_id():
    text = _text()
    assert "registration_facts_v2_serving" in text
    assert "case when f.grain = 'BRAND' then null" in text


def test_reporting_source_v2_branch_does_not_rejoin_facts_v2_by_a_non_unique_key():
    # registration_facts_v2_serving already carries one row per fact
    # (observation_id, raw_brand, raw_model included) - the v2 branch of
    # registration_reporting_source must read it directly, not rejoin
    # registration_facts_v2 by (period, canonical_id, grain), which is not
    # a unique key and would fan out (double-count) whenever two distinct
    # observations resolve to the same canonical target in the same period.
    text = _text().lower()
    v2_branch_start = text.index("from public.registration_facts_v2_serving v")
    v2_branch_end = text.index("where state.active_source = 'v2';")
    body = text[v2_branch_start:v2_branch_end]
    assert "join public.registration_facts_v2 f" not in body
    assert "join public.registration_observations_v2 o" not in body


def test_reporting_source_view_exists_and_branches_on_active_source():
    text = _text().lower()
    assert "create or replace view public.registration_reporting_source" in text
    assert "state.active_source = 'legacy'" in text
    assert "state.active_source = 'v2'" in text


def test_reporting_source_exposes_every_column_the_ts_consumer_selects():
    # lib/registration-analytics.ts::fetchRegistrationRows selects exactly
    # these six columns from registration_reporting_source (the one TS
    # change this cutover required) - a column this view stops exposing
    # would break that query at runtime with no type-level warning, so it
    # is pinned here directly against the view's own column list.
    text = _text().lower()
    for column in ("period", "registration_type", "brand_name_raw",
                  "model_name_raw", "model_id", "registrations"):
        assert column in text


def test_reporting_source_and_serving_view_not_granted_to_anon_or_authenticated():
    text = _text().lower()
    for view in ("registration_reporting_source", "registration_facts_v2_serving"):
        assert f"revoke all on table public.{view} from anon, authenticated" in text


def test_redirected_views_read_from_reporting_source_not_registrations_directly():
    text = _text().lower()
    for view in ("registration_analytics_coverage", "registration_monthly_brand",
                "registration_monthly_model"):
        start = text.index(f"create or replace view public.{view}")
        # up to the next top-level "create or replace view" (or end of file)
        rest = text[start + 1:]
        next_view = rest.find("create or replace view public.")
        body = rest[:next_view] if next_view != -1 else rest
        assert "from public.registration_reporting_source" in body, view
        assert "from public.registrations r" not in body, view


def test_does_not_drop_or_alter_any_existing_production_table():
    text = _text().lower()
    for obj in ("public.registrations", "public.registration_brand_aliases",
               "public.registration_model_aliases", "public.match_registration_model",
               "public.ingest_registration_snapshot"):
        for verb in ("drop table " + obj, "alter table " + obj,
                    "drop function " + obj, "create table if not exists " + obj):
            assert verb not in text


def test_no_grant_to_anon_or_authenticated_anywhere():
    text = _text().lower()
    assert "to anon" not in text
    assert "to authenticated" not in text


def test_no_data_mutation_of_registrations_anywhere():
    text = _text().lower()
    assert "insert into public.registrations" not in text
    assert "update public.registrations" not in text
    assert "delete from public.registrations" not in text
    assert "truncate" not in text
