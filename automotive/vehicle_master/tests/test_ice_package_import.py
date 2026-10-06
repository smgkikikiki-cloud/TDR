"""Market Track M2: the Ice Full Package CLI.

--check (offline, structural + reconciliation) and --apply (transactional
staged commit via a fake RPC layer that models the real migration_v62
commit/readback semantics closely enough to prove the *importer's* logic,
not Postgres's own transaction guarantee -- that guarantee itself is proven
separately, against real Postgres, in
tests/test_ice_market_panels_migration_v62.py.
"""

from __future__ import annotations

import hashlib
import inspect
import io
import itertools
import json
import zipfile
from pathlib import Path

import pytest

from tools import ice_package_import as cli
from vehreg import ice_package

_unique = itertools.count()

TRIAL_NAME = "TDR_FULL_2569-09_v1_M6.0.zip"
CHANGELOG_HEADER = (
    "change_id,date,level,entity,key,before,after,reason,impact_units,status,confirmed_by,released_in\n")

FAKE_VALIDATOR_OK = b"""
import sys
print("OK", sys.argv[1:])
sys.exit(0)
"""

FAKE_VALIDATOR_FAIL = b"""
import sys
print("simulated failure", file=sys.stderr)
sys.exit(1)
"""


def _manifest(panel_id: str, version: int, files: dict[str, bytes]) -> bytes:
    return json.dumps({
        "panel_id": panel_id, "version": version,
        "period_from": "2564-01", "period_to": "2569-08",
        "files": {name: {"md5": hashlib.md5(data).hexdigest(), "bytes": len(data)} for name, data in files.items()},
        "qc_passed": True, "confirmed_by": ["Owner A", "Owner B"],
    }).encode("utf-8")


def _panel_zip_bytes(panel_id: str, rows_csv: dict[str, str], *, tamper: bool = False) -> bytes:
    data_files = {name: content.encode("utf-8") for name, content in rows_csv.items()}
    all_files = {**data_files, "panel.json": json.dumps({
        "panel_id": panel_id, "version": 1,
        "access": {"view": ["free", "pro", "enterprise"], "info": ["pro"], "csv": ["enterprise"]},
        "free_scope": "latest_period",
    }).encode("utf-8")}
    # manifest.json's declared md5s are computed from the ORIGINAL bytes; a tamper
    # rewrites what actually goes into the zip afterwards, so the two disagree --
    # the real-world "corrupted in transit" shape, not just trailing junk that a
    # lenient zip reader would ignore.
    manifest = _manifest(panel_id, 1, all_files)
    if tamper:
        first_data_file = next(iter(data_files))
        all_files = {**all_files, first_data_file: all_files[first_data_file] + b"TAMPERED"}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in {**all_files, "manifest.json": manifest}.items():
            zf.writestr(name, data)
    return buf.getvalue()


# reg_province/reg_trend/reg_powertrain are mutually reconciled on purpose:
# reg_province's total (20) == reg_trend's total (10+6+4); reg_powertrain
# carries one row per reg_trend model_group_id with a matching reg_est, so
# the "valid package" fixture actually passes the real reconciliation gate
# now wired into check()/apply(), not just a lenient stand-in.
_PANEL_CSV_ROWS: dict[str, dict[str, str]] = {
    "reg_province": {"data/reg_province.csv": (
        "period,province,reg_type,brand,fuel_group,reg_count\n"
        "2569-08,x,รย.1,TOY,ICE,20\n")},
    "reg_trend": {"data/reg_trend.csv": (
        "period,province,reg_type,brand,model_group_id,model_name,reg_count\n"
        "2569-08,x,รย.1,TOY,toy.a,A,10\n"
        "2569-08,x,รย.1,TOY,toy.b,B,6\n"
        "2569-08,x,รย.1,TOY,toy.c,C,4\n")},
    "reg_powertrain": {"data/reg_powertrain.csv": (
        "period,province,reg_type,brand,model_group_id,model_name,fuel_group,reg_est,reg_min,reg_max,certainty\n"
        "2569-08,x,รย.1,TOY,toy.a,A,ICE,10,,,exact\n"
        "2569-08,x,รย.1,TOY,toy.b,B,ICE,6,,,exact\n"
        "2569-08,x,รย.1,TOY,toy.c,C,ICE,4,,,exact\n")},
    "rim_province": {
        "data/rim_province.csv": "period,province,reg_type,brand,rim_bucket,reg_est\n2569-08,x,รย.1,TOY,16,10\n",
        "data/coverage.csv": "period,province,reg_type,brand,reg_total,reg_tyre_known\n2569-08,x,รย.1,TOY,10,9\n",
    },
    "tyre_province": {
        "data/tyre_province.csv": "period,province,reg_type,brand,tyre_size,rim_inch,reg_est\n2569-08,x,รย.1,TOY,205/55R16,16,10\n",
        "data/coverage.csv": "period,province,reg_type,brand,reg_total,reg_tyre_known\n2569-08,x,รย.1,TOY,10,9\n",
    },
    "dims": {
        "dims/brand.csv": "brand\nTOY\n",
        "dims/province.csv": "province\nx\n",
        "dims/reg_type.csv": "reg_type\nรย.1\n",
        "dims/fuel.csv": "fuel_dlt,fuel_group\nน้ำมันเบนซิน,ICE\n",
        "dims/tyre.csv": "tyre_size,rim_inch\n205/55R16,16\n",
        "dims/model_group.csv": (
            "model_group_id,model_name,brand,reg_total_all\n"
            "toy.a,A,TOY,10\ntoy.b,B,TOY,6\ntoy.c,C,TOY,4\n"),
    },
}


def _build_full_package(
    tmp_path: Path, *, status: str = "พร้อมส่ง", confirmed_by: list | None = None,
    panels: list[str] | None = None, validator: bytes | None = FAKE_VALIDATOR_OK,
    master_version: str = "M1", changelog_since: str | None = None,
    tamper_panel: str | None = None, panel_rows: dict[str, dict[str, str]] | None = None,
    changelog: bytes = CHANGELOG_HEADER.encode("utf-8"), id_changes: bytes | None = None, name: str | None = None,
) -> Path:
    confirmed_by = ["Owner A", "Owner B"] if confirmed_by is None else confirmed_by
    panels = list(ice_package.PANEL_IDS) if panels is None else panels
    panel_rows = _PANEL_CSV_ROWS if panel_rows is None else panel_rows

    panel_zip_bytes = {}
    for panel_id in panels:
        raw = _panel_zip_bytes(panel_id, panel_rows[panel_id], tamper=(panel_id == tamper_panel))
        panel_zip_bytes[f"panels/{panel_id}.zip"] = raw

    index = {
        "period": "2569-08", "version": 1, "master_version": master_version,
        "status": status, "confirmed_by": confirmed_by, "changelog_since": changelog_since,
        "panels": panels,
        "files": {name: {"md5": hashlib.md5(data).hexdigest()} for name, data in panel_zip_bytes.items()},
    }

    out = tmp_path / (name or f"TDR_FULL_2569-08_v1_M1_{next(_unique)}.zip")
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr("full_package.json", json.dumps(index).encode("utf-8"))
        zf.writestr("CHANGELOG.csv", changelog)
        if id_changes is not None:
            zf.writestr("id_changes.csv", id_changes)
        if validator is not None:
            zf.writestr("validate_package.py", validator)
        for name, data in panel_zip_bytes.items():
            zf.writestr(name, data)
    return out


class FakeRest:
    """Models the real staging -> commit RPC -> readback RPC flow closely
    enough to prove the importer's own call sequencing and error handling.
    The real atomicity guarantee (a failure rolls back every live table) is
    Postgres's, proven separately against a real cluster in the migration
    test -- this fake's commit handler simply checks every table is staged
    before mutating any live table, mirroring that contract without
    reimplementing a transaction.
    """

    def __init__(self):
        self.calls: list[tuple] = []
        self._imports: list[dict] = []
        self._staging: dict[str, list[dict]] = {}
        self._live: dict[str, list[dict]] = {}
        self.fail_commit = False
        self.readback_overrides: dict[str, int] = {}

    def __call__(self, method, path, payload=None, *, prefer=None):
        self.calls.append((method, path, payload, prefer))

        if method == "GET" and path.startswith("ice_package_imports"):
            return list(reversed(self._imports))[:1]

        if path == "rpc/ice_commit_staged_import":
            if self.fail_commit:
                raise RuntimeError("simulated commit failure")
            for table in cli.TABLES:
                if not self._staging.get(table):
                    raise RuntimeError(f"staging table {table}_staging is empty")
            counts = {}
            for table in cli.TABLES:
                self._live[table] = list(self._staging[table])
                self._staging[table] = []
                counts[table] = len(self._live[table])
            self._imports.append(payload)
            return {"tables": counts, "period": payload["p_period"], "master_version": payload["p_master_version"]}

        if path == "rpc/ice_live_table_counts":
            counts = {table: len(rows) for table, rows in self._live.items()}
            counts.update(self.readback_overrides)
            return counts

        base = path.split("?", 1)[0]
        if base.endswith("_staging"):
            table = base[: -len("_staging")]
            if method == "DELETE":
                self._staging[table] = []
            elif method == "POST":
                self._staging.setdefault(table, []).extend(payload)
            return None

        return None


# ---------------------------------------------------------------------------
# --check (offline, structural)
# ---------------------------------------------------------------------------

def test_a_fully_valid_synthetic_package_has_no_problems(tmp_path):
    path = _build_full_package(tmp_path)
    assert cli.check(path, owner_declared_final=path.name) == []


def test_check_catches_empty_confirmed_by(tmp_path):
    path = _build_full_package(tmp_path, confirmed_by=[])
    problems = cli.check(path)
    assert any("confirmed_by" in p for p in problems)


def test_check_catches_wrong_status(tmp_path):
    path = _build_full_package(tmp_path, status="ร่าง")
    problems = cli.check(path)
    assert any("status" in p for p in problems)


def test_check_catches_a_missing_panel(tmp_path):
    panels = [p for p in ice_package.PANEL_IDS if p != "reg_powertrain"]
    path = _build_full_package(tmp_path, panels=panels)
    problems = cli.check(path)
    assert any("reg_powertrain" in p for p in problems)


def test_check_catches_a_tampered_panel_zip(tmp_path):
    path = _build_full_package(tmp_path, tamper_panel="dims")
    problems = cli.check(path)
    assert any("md5 mismatch" in p for p in problems)


def test_check_catches_a_missing_shipped_validator(tmp_path):
    path = _build_full_package(tmp_path, validator=None)
    problems = cli.check(path)
    assert any("validate_package.py" in p for p in problems)


def test_check_catches_the_shipped_validator_failing(tmp_path):
    path = _build_full_package(tmp_path, validator=FAKE_VALIDATOR_FAIL)
    problems = cli.check(path)
    assert any("shipped validate_package.py failed" in p for p in problems)


def test_check_catches_a_skipped_changelog_version(tmp_path):
    path = _build_full_package(tmp_path, master_version="M1", changelog_since="M9")
    problems = cli.check(path, previous_master_version="M10")
    assert any("changelog_since" in p for p in problems)


def test_check_never_uses_the_superseded_repo_validator():
    source = inspect.getsource(cli)
    assert "automotive/vehicle_master/tools/validate_package" not in source
    assert "from tools import validate_package" not in source
    assert "from tools.validate_package" not in source


# ---------------------------------------------------------------------------
# --check (offline, reconciliation -- fix #2: wired in, not just pure functions)
# ---------------------------------------------------------------------------

def test_check_catches_a_reg_province_reg_trend_mismatch_fully_offline(tmp_path):
    rows = {**_PANEL_CSV_ROWS, "reg_province": {"data/reg_province.csv": (
        "period,province,reg_type,brand,fuel_group,reg_count\n"
        "2569-08,x,รย.1,TOY,ICE,999\n")}}  # reg_trend totals 20, not 999
    path = _build_full_package(tmp_path, panel_rows=rows)
    problems = cli.check(path)
    assert any("reg_province vs reg_trend" in p for p in problems)


def test_check_catches_a_reg_powertrain_reg_trend_mismatch_fully_offline(tmp_path):
    rows = {**_PANEL_CSV_ROWS, "reg_powertrain": {"data/reg_powertrain.csv": (
        "period,province,reg_type,brand,model_group_id,model_name,fuel_group,reg_est,reg_min,reg_max,certainty\n"
        "2569-08,x,รย.1,TOY,toy.a,A,ICE,999,,,exact\n")}}  # drops toy.b/toy.c entirely, toy.a wrong too
    path = _build_full_package(tmp_path, panel_rows=rows)
    problems = cli.check(path)
    assert any("reg_powertrain vs reg_trend" in p for p in problems)


def test_a_reconciliation_failure_is_included_alongside_other_problems(tmp_path):
    # Reconciliation runs even when confirmed_by is also wrong -- check()
    # reports everything it finds, not just the first problem.
    rows = {**_PANEL_CSV_ROWS, "reg_province": {"data/reg_province.csv": (
        "period,province,reg_type,brand,fuel_group,reg_count\n"
        "2569-08,x,รย.1,TOY,ICE,999\n")}}
    path = _build_full_package(tmp_path, confirmed_by=[], panel_rows=rows)
    problems = cli.check(path)
    assert any("confirmed_by" in p for p in problems)
    assert any("reg_province vs reg_trend" in p for p in problems)


# ---------------------------------------------------------------------------
# --apply: staged commit (never touches a live table directly)
# ---------------------------------------------------------------------------

def test_apply_refuses_and_stages_nothing_when_check_fails(tmp_path):
    path = _build_full_package(tmp_path, confirmed_by=[])
    rest = FakeRest()
    with pytest.raises(cli.IceImportError):
        cli.apply_package(path, rest=rest, imported_by="test")
    write_calls = [c for c in rest.calls if c[0] in ("POST", "DELETE") and c[1] != "ice_package_imports"]
    assert write_calls == [], "a failed check must stage and commit nothing"
    assert rest._imports == []


def test_apply_refuses_and_stages_nothing_when_reconciliation_fails(tmp_path):
    rows = {**_PANEL_CSV_ROWS, "reg_province": {"data/reg_province.csv": (
        "period,province,reg_type,brand,fuel_group,reg_count\n"
        "2569-08,x,รย.1,TOY,ICE,999\n")}}
    path = _build_full_package(tmp_path, panel_rows=rows)
    rest = FakeRest()
    with pytest.raises(cli.IceImportError, match="reg_province vs reg_trend"):
        cli.apply_package(path, rest=rest, imported_by="test")
    write_calls = [c for c in rest.calls if c[0] in ("POST", "DELETE") and c[1] != "ice_package_imports"]
    assert write_calls == []


def test_apply_stages_every_table_before_the_single_commit_call(tmp_path):
    path = _build_full_package(tmp_path)
    rest = FakeRest()
    cli.apply_package(path, rest=rest, owner_declared_final=path.name, imported_by="tester")

    commit_index = next(i for i, c in enumerate(rest.calls) if c[1] == "rpc/ice_commit_staged_import")
    readback_index = next(i for i, c in enumerate(rest.calls) if c[1] == "rpc/ice_live_table_counts")
    assert commit_index < readback_index, "commit must happen before the readback"

    for table in cli.TABLES:
        staging_calls = [c for c in rest.calls[:commit_index] if c[1].startswith(f"{table}_staging")]
        assert staging_calls, table
        assert staging_calls[0][0] == "DELETE", table
        assert any(c[0] == "POST" for c in staging_calls[1:]), table
        # never touched directly -- only ever through staging + the one RPC
        direct_live_calls = [c for c in rest.calls if c[1] == table or c[1].startswith(f"{table}?")]
        assert direct_live_calls == [], f"{table} was written directly, bypassing the staged commit"


def test_apply_commits_the_real_row_data_through_staging_to_live(tmp_path):
    path = _build_full_package(tmp_path)
    rest = FakeRest()
    cli.apply_package(path, rest=rest, owner_declared_final=path.name, imported_by="tester")
    assert rest._live["ice_dims_brand"] == [{"brand": "TOY"}]
    assert len(rest._live["ice_reg_trend"]) == 3


def test_apply_chunks_staging_inserts_for_large_tables(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "CHUNK_SIZE", 1)
    path = _build_full_package(tmp_path)
    rest = FakeRest()
    cli.apply_package(path, rest=rest, owner_declared_final=path.name, imported_by="tester")
    inserts = [c for c in rest.calls if c[0] == "POST" and c[1] == "ice_reg_trend_staging"]
    assert len(inserts) == 3, inserts
    for payload in (c[2] for c in inserts):
        assert len(payload) == 1
    assert rest._live["ice_reg_trend"]  # still ends up live after chunked staging


def test_apply_does_not_over_chunk_when_rows_fit_in_one_page(tmp_path):
    path = _build_full_package(tmp_path)  # default CHUNK_SIZE; 3 reg_trend rows
    rest = FakeRest()
    cli.apply_package(path, rest=rest, owner_declared_final=path.name, imported_by="tester")
    inserts = [c for c in rest.calls if c[0] == "POST" and c[1] == "ice_reg_trend_staging"]
    assert len(inserts) == 1
    assert len(inserts[0][2]) == 3


def test_apply_passes_the_import_metadata_into_the_commit_rpc(tmp_path):
    path = _build_full_package(tmp_path, master_version="M7")
    rest = FakeRest()
    cli.apply_package(path, rest=rest, owner_declared_final=path.name, imported_by="tester")
    commit_calls = [c for c in rest.calls if c[1] == "rpc/ice_commit_staged_import"]
    assert len(commit_calls) == 1
    payload = commit_calls[0][2]
    assert payload["p_master_version"] == "M7"
    assert payload["p_period"] == "2569-08"
    assert payload["p_imported_by"] == "tester"


def test_a_commit_rpc_failure_propagates_as_a_clean_error_and_never_calls_the_version_log(tmp_path, monkeypatch):
    path = _build_full_package(tmp_path)
    rest = FakeRest()
    rest.fail_commit = True
    called = []
    monkeypatch.setattr(cli, "update_package_version_log", lambda *a, **k: called.append(True))
    with pytest.raises(cli.IceImportError, match="simulated commit failure"):
        cli.apply_package(path, rest=rest, owner_declared_final=path.name, imported_by="tester", repo_root=path.parent)
    assert called == [], "a failed commit must never advance the version log"
    assert rest._imports == []


def test_a_readback_mismatch_is_reported_loudly_after_commit(tmp_path, monkeypatch):
    path = _build_full_package(tmp_path)
    rest = FakeRest()
    rest.readback_overrides = {"ice_dims_brand": 999}
    called = []
    monkeypatch.setattr(cli, "update_package_version_log", lambda *a, **k: called.append(True))
    with pytest.raises(cli.IceImportError, match="READBACK MISMATCH"):
        cli.apply_package(path, rest=rest, owner_declared_final=path.name, imported_by="tester", repo_root=path.parent)
    # The commit itself already happened (this is a post-commit check) --
    # but the version log must still never advance on top of a flagged mismatch.
    assert len(rest._imports) == 1
    assert called == []


def test_apply_passes_the_last_recorded_master_version_into_the_changelog_check(tmp_path):
    path = _build_full_package(tmp_path, changelog_since="M3")
    rest = FakeRest()
    rest._imports.append({"master_version": "M3"})
    cli.apply_package(path, rest=rest, owner_declared_final=path.name, imported_by="tester")  # M3 matches -> ok

    path2 = _build_full_package(tmp_path, changelog_since="M3", master_version="M4")
    rest2 = FakeRest()
    rest2._imports.append({"master_version": "M9"})  # a version was skipped
    with pytest.raises(cli.IceImportError, match="changelog_since"):
        cli.apply_package(path2, rest=rest2, owner_declared_final=path2.name, imported_by="tester")


# ---------------------------------------------------------------------------
# Package-versioning workflow (fix #3)
# ---------------------------------------------------------------------------

def test_package_folder_name_never_double_prefixes_m():
    # Whether the real master_version already includes "M" is itself part of
    # the unverified outer-schema assumption -- both conventions must be
    # representable without a "v1_MM5"-style double prefix.
    assert cli.package_folder_name({"version": 1, "master_version": "M5"}) == "v1_M5"
    assert cli.package_folder_name({"version": 1, "master_version": "5"}) == "v1_M5"


def test_successful_apply_writes_the_package_version_log(tmp_path):
    path = _build_full_package(tmp_path, master_version="M5")
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    rest = FakeRest()
    cli.apply_package(path, rest=rest, owner_declared_final=path.name, imported_by="tester", repo_root=repo_root)

    packages_dir = repo_root / cli.PACKAGES_DIR_NAME
    folder = packages_dir / "2569-08" / "v1_M5"
    assert folder.is_dir()
    assert (folder / path.name).exists()

    latest = json.loads((packages_dir / "ล่าสุด.json").read_text(encoding="utf-8"))
    assert latest["period"] == "2569-08"
    assert latest["master_version"] == "M5"
    assert latest["folder"] == "2569-08/v1_M5"

    history_raw = (packages_dir / "ประวัติการนำเข้า.csv").read_bytes()
    assert history_raw.startswith(b"\xef\xbb\xbf"), "history file must start with a UTF-8 BOM"
    assert history_raw.count(b"\xef\xbb\xbf") == 1, "the BOM must appear exactly once"


def test_failed_apply_never_touches_the_package_version_log(tmp_path):
    path = _build_full_package(tmp_path, confirmed_by=[])
    repo_root = tmp_path / "repo2"
    repo_root.mkdir()
    rest = FakeRest()
    with pytest.raises(cli.IceImportError):
        cli.apply_package(path, rest=rest, owner_declared_final=path.name, imported_by="tester", repo_root=repo_root)
    assert not (repo_root / cli.PACKAGES_DIR_NAME).exists()


def test_update_package_version_log_appends_a_second_import_without_a_second_bom(tmp_path):
    repo_root = tmp_path / "repo3"
    repo_root.mkdir()
    path1 = _build_full_package(tmp_path, master_version="M1")
    path2 = _build_full_package(tmp_path, master_version="M2")

    index1 = cli.load_package(path1).index
    index2 = cli.load_package(path2).index
    cli.update_package_version_log(repo_root, index1, path1, imported_by="a")
    cli.update_package_version_log(repo_root, index2, path2, imported_by="b")

    history_raw = (repo_root / cli.PACKAGES_DIR_NAME / "ประวัติการนำเข้า.csv").read_bytes()
    assert history_raw.count(b"\xef\xbb\xbf") == 1
    text = history_raw.decode("utf-8-sig")
    data_lines = [line for line in text.splitlines() if line]
    assert len(data_lines) == 3  # header + 2 rows

    latest = json.loads((repo_root / cli.PACKAGES_DIR_NAME / "ล่าสุด.json").read_text(encoding="utf-8"))
    assert latest["master_version"] == "M2"  # the second write is the one that stuck


# ---------------------------------------------------------------------------
# Same-period old-version archiving (fix #2, SKILL.md §6.2 step 2)
# ---------------------------------------------------------------------------

def test_a_new_version_of_the_same_period_archives_the_old_active_folder(tmp_path):
    repo_root = tmp_path / "repo_archive"
    repo_root.mkdir()
    path_v1 = _build_full_package(tmp_path, master_version="1")
    path_v2 = _build_full_package(tmp_path, master_version="2")

    index_v1 = cli.load_package(path_v1).index
    index_v2 = cli.load_package(path_v2).index
    cli.update_package_version_log(repo_root, index_v1, path_v1, imported_by="a")

    packages_dir = repo_root / cli.PACKAGES_DIR_NAME
    old_active = packages_dir / "2569-08" / "v1_M1"
    assert old_active.is_dir()
    assert (old_active / path_v1.name).exists()

    cli.update_package_version_log(repo_root, index_v2, path_v2, imported_by="b")

    # The old active folder is gone from its original location...
    assert not old_active.exists()
    # ...moved (never deleted) under <period>/เวอร์ชันเก่า/<old_folder>_เก่า/,
    # with its archive content intact.
    archived = packages_dir / "2569-08" / "เวอร์ชันเก่า" / "v1_M1_เก่า"
    assert archived.is_dir()
    assert (archived / path_v1.name).exists()
    # The new version is now the active folder.
    new_active = packages_dir / "2569-08" / "v1_M2"
    assert new_active.is_dir()
    assert (new_active / path_v2.name).exists()
    latest = json.loads((packages_dir / "ล่าสุด.json").read_text(encoding="utf-8"))
    assert latest["master_version"] == "2"


def test_archiving_a_name_collision_gets_a_unique_suffix_never_an_overwrite(tmp_path):
    repo_root = tmp_path / "repo_collision"
    repo_root.mkdir()
    packages_dir = repo_root / cli.PACKAGES_DIR_NAME

    path_v1 = _build_full_package(tmp_path, master_version="1")
    path_v2 = _build_full_package(tmp_path, master_version="2")
    index_v1 = cli.load_package(path_v1).index
    index_v2 = cli.load_package(path_v2).index

    # v1 active, then superseded by v2 -> archived to v1_M1_เก่า (first archive).
    cli.update_package_version_log(repo_root, index_v1, path_v1, imported_by="a")
    cli.update_package_version_log(repo_root, index_v2, path_v2, imported_by="b")
    first_archive = packages_dir / "2569-08" / "เวอร์ชันเก่า" / "v1_M1_เก่า"
    assert (first_archive / path_v1.name).exists()

    # v1 reappears (e.g. Ice re-sends an old version) with different content,
    # distinguishable by a marker file, and becomes active again under the
    # exact same folder name "v1_M1" the first archive already used.
    reappeared_v1_dir = packages_dir / "2569-08" / "v1_M1"
    reappeared_v1_dir.mkdir(parents=True)
    (reappeared_v1_dir / "MARKER_SECOND_V1.txt").write_text("second", encoding="utf-8")

    # Now a real v3 supersedes both the still-active v2 folder AND the
    # reappeared "v1_M1" -- archiving "v1_M1" a second time must NOT
    # overwrite the first archive; it must get a unique suffix instead.
    path_v3 = _build_full_package(tmp_path, master_version="3")
    index_v3 = cli.load_package(path_v3).index
    cli.update_package_version_log(repo_root, index_v3, path_v3, imported_by="c")

    old_versions_dir = packages_dir / "2569-08" / "เวอร์ชันเก่า"
    # The original first archive is untouched -- still v1's real content,
    # never clobbered by the reappeared marker.
    assert (first_archive / path_v1.name).exists()
    assert not (first_archive / "MARKER_SECOND_V1.txt").exists()
    # The reappeared, colliding "v1_M1" landed at a distinct, suffixed path.
    second_archive = old_versions_dir / "v1_M1_เก่า_2"
    assert second_archive.is_dir()
    assert (second_archive / "MARKER_SECOND_V1.txt").exists()
    # v2's own (unrelated) folder is archived too, under its own name -- no
    # collision there, so no suffix needed.
    assert (old_versions_dir / "v1_M2_เก่า").is_dir()
    # Exactly these three archived folders exist; nothing was overwritten.
    archived_names = sorted(p.name for p in old_versions_dir.iterdir())
    assert archived_names == ["v1_M1_เก่า", "v1_M1_เก่า_2", "v1_M2_เก่า"]


def test_the_very_first_import_of_a_period_has_nothing_to_archive(tmp_path):
    repo_root = tmp_path / "repo_first"
    repo_root.mkdir()
    path = _build_full_package(tmp_path, master_version="1")
    index = cli.load_package(path).index
    cli.update_package_version_log(repo_root, index, path, imported_by="a")  # must not raise
    old_versions_dir = repo_root / cli.PACKAGES_DIR_NAME / "2569-08" / "เวอร์ชันเก่า"
    assert not old_versions_dir.exists()


def test_main_refuses_apply_without_repo_root_and_touches_nothing(tmp_path, monkeypatch, capsys):
    # A real --apply must never be allowed to silently skip the versioning
    # state: the CLI itself enforces --repo-root, before check()/staging/
    # commit ever runs -- not just apply_package()'s own optional parameter,
    # which other programmatic callers may still use directly (see below).
    path = _build_full_package(tmp_path)
    called = []
    monkeypatch.setattr(cli, "apply_package", lambda *a, **k: called.append(True))
    code = cli.main(["--apply", str(path), "--imported-by", "tester"])
    assert code == 1
    assert called == [], "apply_package must never run without --repo-root"
    assert "--repo-root is required" in capsys.readouterr().out


def test_apply_package_itself_still_allows_an_optional_repo_root_for_other_callers(tmp_path):
    # apply_package() (not the CLI) may still be used programmatically without
    # a repo_root -- e.g. by a future caller that persists the version log
    # somewhere other than a git checkout. Only tools.ice_package_import.main
    # enforces --repo-root for a real --apply.
    path = _build_full_package(tmp_path)
    rest = FakeRest()
    cli.apply_package(path, rest=rest, owner_declared_final=path.name, imported_by="tester")  # no repo_root; does not raise
    assert not (tmp_path / cli.PACKAGES_DIR_NAME).exists()


# ---------------------------------------------------------------------------
# Guardrail: the outer schema assumption is isolated and marked unverified
# ---------------------------------------------------------------------------

def test_the_outer_package_schema_is_explicitly_marked_unverified():
    assert ice_package.OUTER_PACKAGE_SCHEMA_VERIFIED_AGAINST_REAL_FILE is False, (
        "this must only ever be flipped to True deliberately, the first time a real "
        "full_package.json has actually been inspected -- see vehreg/ice_package.py's "
        "module docstring")


# ---------------------------------------------------------------------------
# Market Track R1: structurally valid is not the same as production-authorized
# ---------------------------------------------------------------------------

def test_a_structurally_valid_package_without_a_declaration_is_refused_as_authority(tmp_path):
    path = _build_full_package(tmp_path)
    structural, authority, _ = cli.check_split(path)
    assert structural == []
    assert any("no owner declaration" in p for p in authority)


def test_the_trial_package_is_refused_for_production_by_the_outer_gate_not_by_its_name(tmp_path):
    # Same shape as the owner's M6.0 trial: six panels, status "พร้อมส่ง", two sign-offs,
    # a released crosswalk change and no id_changes.csv. Refused by the release rules alone.
    released_crosswalk = (CHANGELOG_HEADER + "C1,2569-09,Major,crosswalk,k,a,b,r,1,ออกเวอร์ชัน,Ice,6.0\n").encode("utf-8")
    path = _build_full_package(tmp_path, name=TRIAL_NAME, changelog=released_crosswalk)
    structural, authority, releases = cli.check_split(path, owner_declared_final=TRIAL_NAME)
    assert structural == []
    assert any("id_changes.csv" in p for p in authority)
    assert len(releases) == 6
    assert not any("trial" in p for p in authority), "trial authority must never be inferred from the filename"


def test_a_proposed_changelog_row_blocks_authority_but_not_structure(tmp_path):
    path = _build_full_package(
        tmp_path, changelog=(CHANGELOG_HEADER + "C1,2569-09,Major,crosswalk,k,a,b,r,1,เสนอ,Ice,\n").encode("utf-8"))
    structural, authority, _ = cli.check_split(path, owner_declared_final=path.name)
    assert structural == []
    assert any("เสนอ" in p for p in authority)


def test_a_released_crosswalk_change_without_id_changes_csv_refuses_the_release(tmp_path):
    released_crosswalk = (CHANGELOG_HEADER + "C1,2569-09,Major,crosswalk,k,a,b,r,1,ออกเวอร์ชัน,Ice,6.0\n").encode("utf-8")
    path = _build_full_package(tmp_path, changelog=released_crosswalk)
    structural, authority, _ = cli.check_split(path, owner_declared_final=path.name)
    assert structural == []
    assert any("identity change" in p and "id_changes.csv is absent" in p for p in authority)


def test_a_missing_id_changes_csv_for_a_retired_model_group_blocks_authority(tmp_path):
    path = _build_full_package(tmp_path)
    structural, authority, _ = cli.check_split(
        path, owner_declared_final=path.name, previous_model_group_ids={"toy.a", "toy.retired"})
    assert structural == []
    assert any("previously imported" in p and "toy.retired" in p for p in authority)


def test_an_id_changes_csv_that_covers_the_retired_group_clears_that_refusal(tmp_path):
    id_changes = (
        "old_model_group_id,new_model_group_id,reg_moved_all_periods,share_of_old_pct,type\n"
        "toy.retired,toy.a,1,100,เปลี่ยนรหัส\n").encode("utf-8")
    path = _build_full_package(tmp_path, id_changes=id_changes)
    structural, authority, _ = cli.check_split(
        path, owner_declared_final=path.name, previous_model_group_ids={"toy.a", "toy.retired"})
    assert structural == [] and authority == []


def test_apply_commits_the_panel_release_metadata_with_the_import(tmp_path):
    path = _build_full_package(tmp_path)
    rest = FakeRest()
    cli.apply_package(path, rest=rest, owner_declared_final=path.name, imported_by="tester")
    commit = [c for c in rest.calls if c[1] == "rpc/ice_commit_staged_import"][0][2]
    releases = commit["p_panels"]
    assert [r["panel_id"] for r in releases] == list(ice_package.PANEL_IDS)
    for release in releases:
        assert release["period_from"] == "2564-01"
        assert release["period_to"] == "2569-08"
        assert release["access"] == {"view": ["free", "pro", "enterprise"], "info": ["pro"], "csv": ["enterprise"]}
        assert release["free_scope"] == "latest_period"
        assert release["confirmed_by"] == ["Owner A", "Owner B"]


def test_apply_refuses_a_package_with_no_owner_declaration_and_stages_nothing(tmp_path):
    path = _build_full_package(tmp_path)
    rest = FakeRest()
    with pytest.raises(cli.IceImportError, match="no owner declaration"):
        cli.apply_package(path, rest=rest, imported_by="tester")
    assert not [c for c in rest.calls if c[1].endswith("_staging") or c[1].startswith("rpc/")]


def test_cli_check_reports_structural_and_authority_separately(tmp_path, capsys):
    path = _build_full_package(tmp_path)
    code = cli.main(["--check", str(path)])
    out = capsys.readouterr().out
    assert code == 1
    assert '"structurally_valid": true' in out
    assert '"production_authorized": false' in out
    assert "no owner declaration" in out


def test_cli_check_passes_only_when_structure_and_authority_are_both_clean(tmp_path, capsys):
    path = _build_full_package(tmp_path)
    code = cli.main(["--check", str(path), "--owner-declared-final", path.name])
    out = capsys.readouterr().out
    assert code == 0
    assert '"production_authorized": true' in out and '"valid": true' in out
