"""Read-only guardrails for the unnumbered scoped SQL design candidate."""
from pathlib import Path
import re


SQL = (Path(__file__).parents[3] / "docs/market-track/ICE_SCOPED_CROSSWALK_V2_SQL_DRAFT.sql").read_text()


def test_schema_key_supports_many_groups_per_target_and_scoped_pickups():
    assert re.search(r"primary key\s*\(\s*model_group_id\s*,\s*reg_type_scope\s*\)", SQL, re.I)
    assert "canonical_model_id text references public.vehicle_models (canonical_id)" in SQL
    assert "reg_type_scope ~ '^รย\\.[0-9]+$'" in SQL
    assert not re.search(r"unique\s*\(\s*canonical_model_id\s*\)", SQL, re.I)


def test_status_and_source_provenance_contract_is_enforced_in_the_draft():
    assert "status in ('APPROVED', 'EXCLUDED', 'PENDING')" in SQL
    assert "pending_target_id text" in SQL
    assert "(status = 'APPROVED' and canonical_model_id is not null and pending_target_id is null)" in SQL
    assert "(status = 'EXCLUDED' and canonical_model_id is null and pending_target_id is null)" in SQL
    for immutable_field in ("model_group_id", "reg_type_scope", "master_version",
                            "decision_ref", "source_sha256", "created_at"):
        assert f"new.{immutable_field} is distinct from old.{immutable_field}" in SQL
    assert "before update on public.ice_model_crosswalk_scoped" in SQL


def test_draft_is_unversioned_and_service_role_has_no_write_permission():
    assert "DESIGN CANDIDATE ONLY. DO NOT APPLY." in SQL
    assert "revoke all on public.ice_model_crosswalk_scoped from public, anon, authenticated" in SQL
    assert "revoke insert, update, delete on public.ice_model_crosswalk_scoped from service_role" in SQL
    assert "grant select on public.ice_model_crosswalk_scoped to service_role" in SQL
    assert not re.search(r"migration_v\d+", SQL, re.I)
    assert "ice_model_crosswalk" not in SQL.replace("ice_model_crosswalk_scoped", "")
