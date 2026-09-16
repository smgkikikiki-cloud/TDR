"""Regression coverage for
supabase/migration_v32_access_policy_and_quotas.sql.

Source-text regression only (no dockerized/live Postgres in this test
suite, matching this repo's existing migration-test convention -- see
test_billing_identity_migration.py). Proves: every new table is
service-role only (RLS enabled, anon/authenticated revoked), the atomic
usage-consumption RPC is locked down the same way as
tdr_claim_billing_webhook, the sales-module-selection table enforces its
4-of-6 shape at the schema level, and this migration never touches any
existing production table (registrations, tdr_entitlements, etc.)."""
from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).resolve().parents[3] / "supabase"
    / "migration_v32_access_policy_and_quotas.sql"
)


def _text() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8")


def test_migration_file_exists():
    assert MIGRATION_PATH.is_file()


def test_customer_profiles_table_created_with_required_fields():
    text = _text().lower()
    assert "create table if not exists public.tdr_customer_profiles" in text
    for column in ("postcode", "is_individual", "company_name",
                   "marketing_consent", "marketing_consent_at", "marketing_consent_version"):
        assert column in text


def test_company_required_unless_individual_is_enforced_at_schema_level():
    text = _text().lower()
    assert "tdr_customer_profiles_company_required_unless_individual" in text
    assert "is_individual or (company_name is not null" in text


def test_marketing_consent_is_auditable_at_schema_level():
    # A true consent flag without both a timestamp and a version string is
    # rejected by the table itself, not just by application code.
    text = _text().lower()
    assert "tdr_customer_profiles_consent_is_auditable" in text
    assert "not marketing_consent or (marketing_consent_at is not null and marketing_consent_version is not null)" in text


def test_usage_counters_and_actions_tables_scope_to_known_metrics():
    text = _text().lower()
    for table in ("tdr_usage_counters", "tdr_usage_actions"):
        assert f"create table if not exists public.{table}" in text
    assert text.count("check (metric in ('vehicle_compare','sales_query','research_full','pdf_export'))") == 2


def test_consume_usage_rpc_is_a_single_atomic_statement_per_branch():
    text = _text().lower()
    assert "create or replace function public.tdr_consume_usage" in text
    start = text.index("create or replace function public.tdr_consume_usage")
    end = text.index("revoke all on function public.tdr_consume_usage", start)
    body = text[start:end]
    # Exactly one unconditional increment (unlimited/null-limit branch) and
    # one conditional increment (limited branch), never more -- otherwise
    # concurrent callers could race between separate check-then-act steps.
    assert body.count("on conflict (user_id, metric, period_key)") == 2
    assert "where public.tdr_usage_counters.count < p_limit" in body


def test_consume_usage_rpc_is_locked_to_service_role_only():
    text = _text().lower()
    assert (
        "revoke all on function public.tdr_consume_usage(uuid, text, text, integer, text) "
        "from public, anon, authenticated"
    ) in text
    assert (
        "grant execute on function public.tdr_consume_usage(uuid, text, text, integer, text) "
        "to service_role"
    ) in text


def test_sales_module_selection_enforces_four_of_six_at_schema_level():
    text = _text().lower()
    assert "create table if not exists public.tdr_sales_module_selection" in text
    assert "check (array_length(modules, 1) between 1 and 4)" in text
    assert "'brand_share','model_share','month_on_month'," in text
    assert "'segment_share','powertrain_share','chinese_bev_rank'" in text


def test_product_events_table_never_grants_client_write_access():
    text = _text().lower()
    assert "create table if not exists public.tdr_product_events" in text
    assert "revoke all on table public.tdr_product_events from public, anon, authenticated" in text
    assert "grant select, insert on table public.tdr_product_events to service_role" in text


def test_every_new_table_has_rls_enabled_and_no_anon_authenticated_grant():
    text = _text().lower()
    new_tables = [
        "tdr_customer_profiles",
        "tdr_usage_counters",
        "tdr_usage_actions",
        "tdr_sales_module_selection",
        "tdr_product_events",
    ]
    for table in new_tables:
        assert f"alter table public.{table} enable row level security" in text
        assert f"revoke all on table public.{table} from public, anon, authenticated" in text


def test_does_not_touch_any_existing_production_table_or_view():
    text = _text().lower()
    protected_objects = [
        "public.registrations",
        "public.tdr_entitlements",
        "public.tdr_customers",
        "public.tdr_subscriptions",
        "public.registration_facts_v2",
        "public.registration_observations_v2",
        "public.registration_reporting_source",
    ]
    for obj in protected_objects:
        for verb in ("drop table " + obj, "alter table " + obj, "drop function " + obj,
                     "truncate " + obj, "delete from " + obj):
            assert verb not in text, f"migration_v32 must not touch {obj} ({verb})"


def test_no_grant_to_anon_or_authenticated_anywhere():
    text = _text().lower()
    assert "to anon" not in text
    assert "to authenticated" not in text
