"""Regression coverage for
supabase/migration_v34_access_policy_and_quotas.sql.

Source-text regression only (no dockerized/live Postgres in this test
suite, matching this repo's existing migration-test convention -- see
test_billing_identity_migration.py). Proves: (1) tdr_customer_profiles is
extended additively against the REAL production shape (user_id,
phone_e164, stripe_customer_id, created_at, updated_at) rather than
assumed to not exist yet, with a compatibility backfill for the existing
legacy paid row that is HONEST about its provenance (activation_source =
'LEGACY_PAID', never a fabricated OTP-verified phone identity); (2) every
new table is service-role only (RLS enabled, anon/authenticated revoked);
(3) the atomic usage-consumption RPC uses an advisory-lock, not a racy
select-then-insert, to serialize concurrent identical requests; (4) the
sales-module-selection table enforces its 4-of-6 shape at the schema
level; (5) the new TDR-owned phone-verification-reservation table
(closing a Supabase phone_change ambiguity gap) enforces at-most-one-
active-reservation-per-phone at the schema level; (6) this migration never
touches any existing production table (registrations, tdr_entitlements,
etc.) and does not collide with migration_v32 (registration v2 trigger
hardening, already on main) or migration_v33 (vehicle media,
reserved/applied)."""
from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).resolve().parents[3] / "supabase"
    / "migration_v34_access_policy_and_quotas.sql"
)


def _text() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8")


def test_migration_file_exists():
    assert MIGRATION_PATH.is_file()


def test_no_v32_or_v33_filename_collision():
    supabase_dir = MIGRATION_PATH.parent
    assert not (supabase_dir / "migration_v32_access_policy_and_quotas.sql").exists()
    assert not (supabase_dir / "migration_v33_access_policy_and_quotas.sql").exists()
    # The real v32/v33 slots belong to other, already-applied migrations.
    assert (supabase_dir / "migration_v32_registration_v2_immutable_trigger_search_path_hardening.sql").exists()


def test_customer_profiles_create_table_matches_live_legacy_shape_exactly():
    # The CREATE TABLE IF NOT EXISTS branch only fires in a fresh
    # environment where the table doesn't exist yet -- it must mirror
    # production's real live shape, not the new tiered columns, otherwise
    # a fresh environment and production would diverge before the ALTERs
    # even run.
    text = _text().lower()
    start = text.index("create table if not exists public.tdr_customer_profiles")
    end = text.index(";", start)
    body = text[start:end]
    for column in ("user_id uuid primary key", "phone_e164 text", "stripe_customer_id text",
                   "created_at timestamptz not null default now()", "updated_at timestamptz not null default now()"):
        assert column in body, f"missing legacy column definition: {column}"
    # New tiered columns must NOT be in the CREATE TABLE itself -- they
    # belong only in the ADD COLUMN IF NOT EXISTS statements below, so the
    # same statements apply whether or not this CREATE actually ran.
    # ("customer_id" is deliberately excluded from this list: it's a
    # substring of the legacy "stripe_customer_id" column, which IS
    # expected in the CREATE TABLE.)
    for column in ("postcode", "is_individual", "company_name", "marketing_consent"):
        assert column not in body, f"{column} must not be in the CREATE TABLE (breaks legacy-table compatibility)"
    assert "\n  customer_id" not in body, "a bare customer_id column must not be in the CREATE TABLE"


def test_new_profile_columns_are_added_via_add_column_if_not_exists():
    text = _text().lower()
    for column, coldef in [
        ("customer_id", "add column if not exists customer_id uuid"),
        ("email", "add column if not exists email text"),
        ("postcode", "add column if not exists postcode text"),
        ("is_individual", "add column if not exists is_individual boolean not null default true"),
        ("company_name", "add column if not exists company_name text"),
        ("marketing_consent", "add column if not exists marketing_consent boolean not null default false"),
        ("marketing_consent_at", "add column if not exists marketing_consent_at timestamptz"),
        ("marketing_consent_version", "add column if not exists marketing_consent_version text"),
        ("profile_completed_at", "add column if not exists profile_completed_at timestamptz"),
        ("activation_completed_at", "add column if not exists activation_completed_at timestamptz"),
    ]:
        assert coldef in text, f"{column} must be added via ALTER TABLE ADD COLUMN IF NOT EXISTS"


def test_customer_id_foreign_key_uses_idempotent_do_block():
    text = _text().lower()
    assert "add constraint tdr_customer_profiles_customer_id_fkey" in text
    assert "exception when duplicate_object then null; end $$;" in text


def test_stripe_customer_id_is_preserved_not_dropped_or_renamed():
    text = _text().lower()
    assert "drop column" not in text
    assert "rename column" not in text
    assert "stripe_customer_id" in text
    # Preserved specifically in the legacy-shape CREATE TABLE, not
    # reinterpreted as something else.
    start = text.index("create table if not exists public.tdr_customer_profiles")
    end = text.index(";", start)
    assert "stripe_customer_id text" in text[start:end]


def test_company_required_unless_individual_is_enforced_at_schema_level():
    text = _text().lower()
    assert "tdr_customer_profiles_company_required_unless_individual" in text
    assert "is_individual or (company_name is not null" in text


def test_marketing_consent_is_auditable_at_schema_level():
    text = _text().lower()
    assert "tdr_customer_profiles_consent_is_auditable" in text
    assert "not marketing_consent or (marketing_consent_at is not null and marketing_consent_version is not null)" in text


def test_legacy_paid_row_compatibility_backfill_is_scoped_to_stripe_customers():
    # The grandfather backfill must only touch rows that already proved
    # themselves as trusted, revenue-bearing customers (a bound Stripe
    # customer) -- never a blanket grant to every row -- and must record
    # WHY (activation_source) alongside WHETHER (activation_completed_at).
    text = _text().lower()
    assert "where p.stripe_customer_id is not null" in text
    assert "activation_completed_at = coalesce(p.activation_completed_at, now())" in text
    assert "activation_source = coalesce(p.activation_source, 'legacy_paid')" in text


def test_activation_source_column_distinguishes_verified_from_legacy():
    text = _text().lower()
    assert "add column if not exists activation_source text" in text
    assert "tdr_customer_profiles_activation_source_known" in text
    assert "activation_source is null or activation_source in ('verified', 'legacy_paid')" in text


def test_legacy_backfill_never_fabricates_an_otp_verified_phone_identity():
    # tdr_customer_phone_identities (migration_v21) is defined as
    # Supabase-Auth-OTP-verified phone identity. The legacy-paid backfill
    # must NOT insert the old typed/billing phone into it as if Supabase
    # had confirmed it -- that would be a false provenance claim. This is
    # the actual fix for the "do not fake OTP provenance" requirement.
    text = _text().lower()
    assert "insert into public.tdr_customer_phone_identities" not in text


def test_usage_counters_and_actions_tables_scope_to_known_metrics():
    text = _text().lower()
    for table in ("tdr_usage_counters", "tdr_usage_actions"):
        assert f"create table if not exists public.{table}" in text
    assert text.count("check (metric in ('vehicle_compare','sales_query','research_full','pdf_export'))") == 2


def test_usage_actions_stores_the_used_count_for_cache_hit_reads():
    text = _text().lower()
    start = text.index("create table if not exists public.tdr_usage_actions")
    end = text.index(");", start)
    assert "used integer not null" in text[start:end]


def _consume_usage_function_body() -> str:
    text = _text().lower()
    start = text.index("create or replace function public.tdr_consume_usage")
    end = text.index("revoke all on function public.tdr_consume_usage", start)
    return text[start:end]


def test_consume_usage_rpc_serializes_concurrent_callers_with_an_advisory_lock():
    # This is the fix for the concurrency race: a naive
    # select-tdr_usage_actions-then-increment-then-insert sequence lets two
    # concurrent callers sharing one action_id both observe "not claimed"
    # and both increment. pg_advisory_xact_lock forces every caller sharing
    # the same (user, metric, action_id) to serialize.
    body = _consume_usage_function_body()
    assert "perform pg_advisory_xact_lock(hashtextextended(" in body
    # The lock must be taken BEFORE the existing-action lookup, not after.
    assert body.index("pg_advisory_xact_lock") < body.index("select a.allowed, a.used into v_existing")


def test_consume_usage_rpc_never_races_the_action_insert_with_on_conflict_do_nothing():
    # The old (unsafe) design used "on conflict (user_id, metric,
    # action_id) do nothing" on the action-row insert, which is exactly
    # what let two concurrent racers both fall through and both increment.
    # Under the advisory lock, a second racer is never still running by the
    # time the first one inserts, so this insert needs no ON CONFLICT at
    # all -- its presence would indicate the race fix regressed.
    body = _consume_usage_function_body()
    assert "on conflict (user_id, metric, action_id)" not in body
    assert "insert into public.tdr_usage_actions(user_id, metric, action_id, period_key, allowed, used)" in body


def test_consume_usage_rpc_is_a_single_atomic_statement_per_counter_branch():
    body = _consume_usage_function_body()
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
    # provincial_registration is a reserved capability, never a 7th
    # selectable sales module -- it must not appear inside the known-modules
    # CHECK constraint's array literal (a mention in an explanatory comment
    # elsewhere in the file, documenting exactly why it's excluded, is fine).
    start = text.index("constraint tdr_sales_module_selection_known_modules")
    end = text.index(");", start)
    assert "provincial_registration" not in text[start:end]


def test_product_events_table_never_grants_client_write_access():
    text = _text().lower()
    assert "create table if not exists public.tdr_product_events" in text
    assert "revoke all on table public.tdr_product_events from public, anon, authenticated" in text
    assert "grant select, insert on table public.tdr_product_events to service_role" in text


def test_every_new_or_extended_table_has_rls_enabled_and_no_anon_authenticated_grant():
    text = _text().lower()
    tables = [
        "tdr_customer_profiles",
        "tdr_usage_counters",
        "tdr_usage_actions",
        "tdr_sales_module_selection",
        "tdr_product_events",
        "tdr_phone_verification_attempts",
    ]
    for table in tables:
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
            assert verb not in text, f"migration_v34 must not touch {obj} ({verb})"


def test_verified_phone_uniqueness_relies_on_the_existing_v21_constraint():
    # migration_v34 deliberately does not duplicate a verified-phone column
    # onto tdr_customer_profiles -- tdr_customer_phone_identities
    # (migration_v21) is kept as the single source of truth for "verified
    # phone", and that table already enforces uniqueness across every row
    # it contains (every row in it is, by construction, OTP-confirmed).
    v21_path = MIGRATION_PATH.parent / "migration_v21_billing.sql"
    v21_text = v21_path.read_text(encoding="utf-8").lower()
    assert "phone_e164 text not null unique" in v21_text


def test_does_not_touch_tdr_customer_phone_identities_schema_or_data():
    # migration_v34 only ever READS tdr_customer_phone_identities (to
    # check for cross-account phone reuse) -- it must not ALTER/DROP its
    # schema, and (per the "no fake OTP provenance" fix) must not
    # INSERT/UPDATE/DELETE its rows either.
    text = _text().lower()
    for verb in ("alter table public.tdr_customer_phone_identities",
                 "drop table public.tdr_customer_phone_identities",
                 "insert into public.tdr_customer_phone_identities",
                 "update public.tdr_customer_phone_identities",
                 "delete from public.tdr_customer_phone_identities"):
        assert verb not in text, f"migration_v34 must not do: {verb}"


def test_phone_verification_attempts_table_scopes_to_known_statuses():
    text = _text().lower()
    assert "create table if not exists public.tdr_phone_verification_attempts" in text
    start = text.index("create table if not exists public.tdr_phone_verification_attempts")
    end = text.index(");", start)
    body = text[start:end]
    assert "status text not null default 'pending'" in body
    assert "check (status in ('pending','confirmed','expired','cancelled'))" in body
    assert "user_id uuid not null references auth.users(id)" in body
    assert "customer_id uuid not null references public.tdr_customers(id)" in body
    assert "phone_e164 text not null check (phone_e164 ~ '^\\+[1-9][0-9]{7,14}$')" in body


def test_phone_verification_attempts_enforces_one_active_reservation_per_phone():
    # The database-level backstop for "prevent two active reservations
    # from legitimately claiming the same phone" -- a partial unique index
    # scoped to PENDING/CONFIRMED, not a full-table unique constraint (a
    # phone can be freely re-reserved once its prior attempt is
    # EXPIRED/CANCELLED).
    text = _text().lower()
    assert "tdr_phone_verification_attempts_active_phone_uq" in text
    start = text.index("tdr_phone_verification_attempts_active_phone_uq")
    end = text.index(";", start)
    body = text[start:end]
    assert "on public.tdr_phone_verification_attempts(phone_e164)" in body
    assert "where status in ('pending', 'confirmed')" in body


def test_phone_verification_attempts_is_service_role_only():
    text = _text().lower()
    assert "alter table public.tdr_phone_verification_attempts enable row level security" in text
    assert "revoke all on table public.tdr_phone_verification_attempts from public, anon, authenticated" in text
    assert "grant select, insert, update, delete on table public.tdr_phone_verification_attempts to service_role" in text


def test_expire_stale_phone_verification_attempts_function_is_scoped_and_locked_down():
    text = _text().lower()
    assert "create or replace function public.tdr_expire_stale_phone_verification_attempts" in text
    start = text.index("create or replace function public.tdr_expire_stale_phone_verification_attempts")
    end = text.index("$$;", start)
    body = text[start:end]
    assert "status = 'pending' and expires_at < now()" in body
    assert "set status = 'expired'" in body
    assert (
        "revoke all on function public.tdr_expire_stale_phone_verification_attempts() "
        "from public, anon, authenticated"
    ) in text
    assert (
        "grant execute on function public.tdr_expire_stale_phone_verification_attempts() "
        "to service_role"
    ) in text


def test_does_not_write_to_auth_users_directly():
    # auth.users is Supabase-managed schema. This migration (and its
    # documented operational note about stale phone_change) must never
    # attempt to write to it directly.
    text = _text().lower()
    assert "update auth.users" not in text
    assert "alter table auth.users" not in text
    assert "insert into auth.users" not in text
    assert "delete from auth.users" not in text


def test_no_grant_to_anon_or_authenticated_anywhere():
    text = _text().lower()
    assert "to anon" not in text
    assert "to authenticated" not in text
