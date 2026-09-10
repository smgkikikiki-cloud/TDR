from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATION = REPO_ROOT / "supabase" / "migration_v24_phone_identity_revocation.sql"


def test_unconfirmed_or_removed_phone_revokes_primary_identity() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert "new.phone is null or new.phone_confirmed_at is null" in sql
    assert "new.phone !~" in sql
    assert "set is_primary = false" in sql
    assert "revoked_at = coalesce(revoked_at, now())" in sql
    assert "where customer_id = customer_uuid and is_primary" in sql
    assert "return new;" in sql


def test_confirmed_phone_can_be_reactivated_without_public_execution() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert "verified_at = greatest" in sql
    assert "is_primary = true" in sql
    assert "revoked_at = null" in sql
    assert "security definer set search_path = public, pg_temp" in sql
    assert (
        "revoke all on function public.tdr_sync_customer_from_auth() "
        "from public, anon, authenticated"
    ) in sql
