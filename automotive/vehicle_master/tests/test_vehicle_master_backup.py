"""Phase 0 step 6: the Vehicle Master daily backup exporter."""

from __future__ import annotations

from datetime import datetime, timezone
import gzip
import inspect
import json
from pathlib import Path

import pytest

from tools import vehicle_master_backup as backup

ROOT = Path(__file__).resolve().parents[3]

EXPECTED_TABLES = [
    "vehicle_master_state",
    "vehicle_brands",
    "vehicle_models",
    "vehicle_generations",
    "vehicle_variants",
    "vehicle_trims",
    "vehicle_facts",
    "vehicle_price_ledger",
    "vehicle_campaigns",
    "vehicle_promotions",
    "vehicle_eco_evidence",
    "vehicle_current_retail_sets",
    "vehicle_trim_lifecycle_decisions",
    "vehicle_model_operational_states",
    "vehicle_legacy_identities",
]

FIXED_NOW = datetime(2026, 10, 4, 18, 30, 7, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Allowlist
# ---------------------------------------------------------------------------

def test_allowlist_matches_the_explicit_table_list():
    assert list(backup.TABLES.keys()) == EXPECTED_TABLES


def test_allowlist_excludes_registration_tables():
    for name in backup.TABLES:
        assert "registration" not in name
    assert "registrations" not in backup.TABLES


def test_allowlist_excludes_seed_run_bookkeeping():
    # vehicle_master_seed_runs is process telemetry, not state needed to
    # reconstruct the catalog -- deliberately out of the Step 6 V0 scope.
    assert "vehicle_master_seed_runs" not in backup.TABLES


def test_allowlist_excludes_legacy_change_log_for_now():
    # canonical_write_revisions carries only legacy file/release-path history
    # today (the legacy write path is closed, migration_v60); it is not yet
    # Vehicle Master audit state. Phase 1 should reconsider this once it
    # reuses the table as the master change log.
    assert "canonical_write_revisions" not in backup.TABLES


# ---------------------------------------------------------------------------
# Fake REST layer for offline tests
# ---------------------------------------------------------------------------

class FakeRest:
    """Records every call and serves canned, pageable table rows."""

    def __init__(self, tables: dict[str, list[dict]], *, page_size: int = 1000):
        self.tables = tables
        self.page_size = page_size
        self.calls: list[tuple[str, str]] = []

    def __call__(self, method: str, path: str, *args, **kwargs):
        self.calls.append((method, path))
        if method != "GET":
            raise AssertionError(f"exporter must only issue GET requests, got {method} {path}")
        table_name = path.split("?", 1)[0]
        query = path.split("?", 1)[1] if "?" in path else ""
        params = dict(part.split("=", 1) for part in query.split("&") if "=" in part)
        offset = int(params.get("offset", "0"))
        limit = int(params.get("limit", str(self.page_size)))
        rows = self.tables.get(table_name, [])
        return rows[offset:offset + limit]


def _sample_tables(shuffled: bool = False) -> dict[str, list[dict]]:
    import random

    tables: dict[str, list[dict]] = {name: [] for name in backup.TABLES}
    tables["vehicle_master_state"] = [{
        "scope": "vehicle_master",
        "seed_release_id": "vehicle-2026-deadbeef",
        "seed_as_of": "2026-10-01",
    }]
    tables["vehicle_brands"] = [
        {"canonical_id": "toyota", "name_en": "Toyota"},
        {"canonical_id": "honda", "name_en": "Honda"},
        {"canonical_id": "byd", "name_en": "BYD"},
    ]
    tables["vehicle_promotions"] = [
        {"campaign_id": "c1", "option_id": "o2", "amount_thb": 5000},
        {"campaign_id": "c1", "option_id": "o1", "amount_thb": 1000},
        {"campaign_id": "c0", "option_id": "o9", "amount_thb": 2000},
    ]
    if shuffled:
        for rows in tables.values():
            random.Random(42).shuffle(rows)
    return tables


def test_fetch_table_paginates_past_the_postgrest_row_cap():
    rows = [{"canonical_id": f"brand-{i:04d}"} for i in range(2500)]
    rest = FakeRest({"vehicle_brands": rows}, page_size=1000)
    fetched = backup.fetch_table("vehicle_brands", ("canonical_id",), rest=rest, page_size=1000)
    assert len(fetched) == 2500
    assert [row["canonical_id"] for row in fetched] == sorted(row["canonical_id"] for row in rows)
    # 3 pages (1000, 1000, 500); the last page already came back short of
    # page_size, so pagination stops there without an extra trailing request.
    assert len(rest.calls) == 3


def test_fetch_table_orders_rows_by_primary_key_regardless_of_fetch_order():
    rows = [{"canonical_id": "c"}, {"canonical_id": "a"}, {"canonical_id": "b"}]
    rest = FakeRest({"vehicle_brands": rows})
    fetched = backup.fetch_table("vehicle_brands", ("canonical_id",), rest=rest)
    assert [row["canonical_id"] for row in fetched] == ["a", "b", "c"]


def test_fetch_table_orders_rows_by_composite_primary_key():
    rows = [
        {"campaign_id": "c1", "option_id": "o2"},
        {"campaign_id": "c1", "option_id": "o1"},
        {"campaign_id": "c0", "option_id": "o9"},
    ]
    rest = FakeRest({"vehicle_promotions": rows})
    fetched = backup.fetch_table("vehicle_promotions", ("campaign_id", "option_id"), rest=rest)
    assert [(row["campaign_id"], row["option_id"]) for row in fetched] == [
        ("c0", "o9"), ("c1", "o1"), ("c1", "o2")]


# ---------------------------------------------------------------------------
# Deterministic export / checksum
# ---------------------------------------------------------------------------

def test_build_export_is_byte_identical_for_the_same_underlying_rows():
    export_a = backup.build_export(rest=FakeRest(_sample_tables(shuffled=False)), now=lambda: FIXED_NOW)
    export_b = backup.build_export(rest=FakeRest(_sample_tables(shuffled=True)), now=lambda: FIXED_NOW)
    assert backup.canonical_json_bytes(export_a) == backup.canonical_json_bytes(export_b)
    assert export_a["checksum"]["value"] == export_b["checksum"]["value"]


def test_checksum_covers_only_the_payload_and_changes_if_data_changes():
    tables = _sample_tables()
    export = backup.build_export(rest=FakeRest(tables), now=lambda: FIXED_NOW)
    recomputed = backup.sha256_hex(backup.canonical_json_bytes(export["payload"]))
    assert export["checksum"]["value"] == recomputed

    tables["vehicle_brands"].append({"canonical_id": "mg", "name_en": "MG"})
    changed = backup.build_export(rest=FakeRest(tables), now=lambda: FIXED_NOW)
    assert changed["checksum"]["value"] != export["checksum"]["value"]


def test_row_counts_in_manifest_match_the_payload_data():
    export = backup.build_export(rest=FakeRest(_sample_tables()), now=lambda: FIXED_NOW)
    payload = export["payload"]
    for name in backup.TABLES:
        assert payload["row_counts"][name] == len(payload["data"][name])


def test_vehicle_master_seed_metadata_is_surfaced_from_vehicle_master_state():
    export = backup.build_export(rest=FakeRest(_sample_tables()), now=lambda: FIXED_NOW)
    assert export["payload"]["vehicle_master_seed"] == {
        "scope": "vehicle_master",
        "seed_release_id": "vehicle-2026-deadbeef",
        "seed_as_of": "2026-10-01",
    }


def test_vehicle_master_seed_is_null_when_unseeded():
    tables = _sample_tables()
    tables["vehicle_master_state"] = []
    export = backup.build_export(rest=FakeRest(tables), now=lambda: FIXED_NOW)
    assert export["payload"]["vehicle_master_seed"] is None


def test_backup_object_path_is_immutable_and_date_partitioned():
    path = backup.backup_object_path(FIXED_NOW)
    assert path == "vehicle-master/2026-10-04/vehicle-master-20261004T183007Z.json.gz"


# ---------------------------------------------------------------------------
# Safety: read-only, fail-closed upload
# ---------------------------------------------------------------------------

def test_exporter_performs_no_db_mutations():
    rest = FakeRest(_sample_tables())
    backup.build_export(rest=rest, now=lambda: FIXED_NOW)
    assert rest.calls, "expected at least one request"
    assert all(method == "GET" for method, _ in rest.calls)


def test_fetch_table_source_never_issues_a_write_request():
    # Scoped to fetch_table/build_export, not the whole module: _storage_upload
    # legitimately POSTs the finished backup file to Storage, which is not a
    # database mutation. The REST/database path must stay GET-only.
    source = inspect.getsource(backup.fetch_table) + inspect.getsource(backup.build_export)
    for verb in ('"POST"', '"PATCH"', '"PUT"', '"DELETE"'):
        assert verb not in source, f"found a {verb} call in the table-fetching code"


def test_exporter_source_never_touches_the_legacy_release_write_path():
    source = inspect.getsource(backup)
    forbidden = (
        "canonical_input_batches", "publish_vehicle_release", "begin_vehicle_release",
        "activate_vehicle_release", "vehicle_master_seed_from_release",
        "vehicle_master_seed_supplemental", "canonical_vehicle_releases",
    )
    for token in forbidden:
        assert token not in source, token


def test_failed_export_never_uploads():
    class ExplodingRest(FakeRest):
        def __call__(self, method, path, *args, **kwargs):
            if path.startswith("vehicle_facts"):
                raise RuntimeError("simulated mid-export failure")
            return super().__call__(method, path, *args, **kwargs)

    uploaded = []

    def spy_upload(path: str, content: bytes) -> None:
        uploaded.append((path, content))

    with pytest.raises(RuntimeError, match="simulated mid-export failure"):
        backup.run(apply=True, rest=ExplodingRest(_sample_tables()), upload=spy_upload, now=lambda: FIXED_NOW)
    assert uploaded == []


def test_successful_run_uploads_exactly_once_after_checksum_succeeds():
    uploaded = []

    def spy_upload(path: str, content: bytes) -> None:
        uploaded.append((path, content))

    summary = backup.run(apply=True, rest=FakeRest(_sample_tables()), upload=spy_upload, now=lambda: FIXED_NOW)
    assert summary["uploaded"] is True
    assert len(uploaded) == 1
    uploaded_path, uploaded_bytes = uploaded[0]
    assert uploaded_path == summary["object_path"]
    assert gzip.decompress(uploaded_bytes)  # decompresses cleanly
    assert backup.sha256_hex(uploaded_bytes) == summary["gzip_sha256"]


def test_dry_run_never_uploads():
    def spy_upload(path: str, content: bytes) -> None:
        raise AssertionError("dry run must never upload")

    summary = backup.run(apply=False, rest=FakeRest(_sample_tables()), upload=spy_upload, now=lambda: FIXED_NOW)
    assert summary["uploaded"] is False


def test_run_can_write_a_local_copy_without_uploading(tmp_path):
    out = tmp_path / "vehicle-master.json.gz"
    summary = backup.run(apply=False, out=out, rest=FakeRest(_sample_tables()), now=lambda: FIXED_NOW)
    assert out.exists()
    assert summary["uploaded"] is False
    decompressed = json.loads(gzip.decompress(out.read_bytes()).decode("utf-8"))
    assert decompressed["format"] == backup.FORMAT_NAME


def test_cli_summary_never_includes_row_data(monkeypatch, capsys):
    real_run = backup.run
    monkeypatch.setattr(
        backup, "run",
        lambda **kwargs: real_run(
            apply=kwargs.get("apply", False), out=kwargs.get("out"),
            rest=FakeRest(_sample_tables()), now=lambda: FIXED_NOW))
    backup.main([])  # no --apply: dry run, no network/upload
    out = capsys.readouterr().out
    printed = json.loads(out)
    assert "data" not in printed
    assert "payload" not in printed
    assert printed["row_counts"]["vehicle_brands"] == 3


# ---------------------------------------------------------------------------
# Workflow: daily + manual, no credentials/contents printed, no legacy writer
# ---------------------------------------------------------------------------

WORKFLOW = ROOT / ".github/workflows/vehicle-master-backup.yml"


def test_workflow_is_scheduled_daily_and_manually_triggerable():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "schedule:" in text
    assert "cron:" in text
    assert "workflow_dispatch:" in text


def test_workflow_uses_existing_supabase_secret_conventions():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "secrets.SUPABASE_URL" in text
    assert "secrets.SUPABASE_SECRET_KEY" in text
    assert "secrets.SUPABASE_SERVICE_ROLE_KEY" in text


def test_workflow_does_not_reopen_any_legacy_writer():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "git push" not in text
    assert "git commit" not in text
    assert "canonical_input_batches" not in text
    assert "publish_vehicle_release" not in text
    assert "contents: read" in text


def _preflight_script() -> str:
    """The exact shell embedded in the workflow's 'Preflight' step."""
    import yaml

    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["backup"]["steps"]
    preflight = next(step for step in steps if step.get("name") == "Preflight")
    assert "if" not in preflight, (
        "the backup/upload step must not be gated behind preflight's own success -- "
        "missing credentials should fail the job, not quietly skip the rest of it")
    return preflight["run"]


def _run_preflight(tmp_path: Path, **supabase_env: str) -> "subprocess.CompletedProcess[str]":
    import subprocess

    # GitHub Actions' `env:` block always defines SUPABASE_URL/SUPABASE_SECRET_KEY/
    # SUPABASE_SERVICE_ROLE_KEY (empty string when the secret is unset) -- it never
    # leaves them literally unset. Mirror that exactly, since the script runs under
    # `set -u` and an actually-unset var (as opposed to an empty one) is a different,
    # unrelated failure mode.
    env = {
        "PATH": "/usr/bin:/bin",
        "SUPABASE_URL": "",
        "SUPABASE_SECRET_KEY": "",
        "SUPABASE_SERVICE_ROLE_KEY": "",
        **supabase_env,
    }
    script_path = tmp_path / "preflight.sh"
    script_path.write_text(_preflight_script(), encoding="utf-8")
    return subprocess.run(["bash", str(script_path)], env=env, capture_output=True, text=True)


def test_missing_credentials_fail_the_preflight_step_loudly(tmp_path):
    result = _run_preflight(tmp_path)  # nothing set beyond the always-present empty defaults
    assert result.returncode != 0, (
        "missing credentials must fail the workflow (Step 6: 'backup failure must fail "
        "the workflow loudly'), not exit 0 and skip the backup")
    assert "::error::" in result.stdout + result.stderr


def test_url_without_either_key_still_fails_the_preflight_step(tmp_path):
    result = _run_preflight(tmp_path, SUPABASE_URL="https://example.supabase.co")
    assert result.returncode != 0


def test_present_credentials_pass_the_preflight_step(tmp_path):
    result = _run_preflight(
        tmp_path,
        SUPABASE_URL="https://example.supabase.co",
        SUPABASE_SECRET_KEY="sb_secret_test_value",
    )
    assert result.returncode == 0, result.stderr


def test_present_credentials_via_legacy_service_role_key_also_pass(tmp_path):
    result = _run_preflight(
        tmp_path,
        SUPABASE_URL="https://example.supabase.co",
        SUPABASE_SERVICE_ROLE_KEY="eyJ-legacy-jwt-test-value",
    )
    assert result.returncode == 0, result.stderr


def test_preflight_never_pauses_with_a_warning_instead_of_failing():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "::warning::" not in text
    assert "ready=false" not in text
    assert "ready == 'true'" not in text
