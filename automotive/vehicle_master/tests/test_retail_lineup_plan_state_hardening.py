from pathlib import Path


def test_chunk5_audit_identity_can_only_change_on_owned_transition():
    root = Path(__file__).resolve().parents[3]
    sql = (root / "supabase" / "migration_v54_retail_lineup_plan_state_hardening.sql").read_text(
        encoding="utf-8")

    assert "RETAIL_LINEUP_STATE_UPDATE_REQUIRES_TRANSITION" in sql
    assert "RETAIL_LINEUP_APPROVAL_AUDIT_IMMUTABLE" in sql
    assert "RETAIL_LINEUP_COMMIT_AUDIT_IMMUTABLE" in sql
    assert "RETAIL_LINEUP_RELEASE_AUDIT_IMMUTABLE" in sql
    assert "new.applied_commit_sha is distinct from old.applied_commit_sha" in sql
    assert "new.release_id is distinct from old.release_id" in sql
    assert "approved_at = now()" in sql
    assert "status in ('PREVIEW_READY','FAILED')" in sql
    assert "plan_hash = p_expected_plan_hash" in sql
    assert "baseline_hash = p_expected_baseline_hash" in sql
