"""Market Track M2: the Ice Full Package CLI (--check offline, --apply replace-whole-set)."""

from __future__ import annotations

import hashlib
import inspect
import io
import itertools
import json
import zipfile
from pathlib import Path

import pytest

_unique = itertools.count()

from tools import ice_package_import as cli
from vehreg import ice_package

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
        "qc_passed": True, "confirmed_by": [],
    }).encode("utf-8")


def _panel_zip_bytes(panel_id: str, rows_csv: dict[str, str], *, tamper: bool = False) -> bytes:
    data_files = {name: content.encode("utf-8") for name, content in rows_csv.items()}
    all_files = {**data_files, "panel.json": json.dumps({"panel_id": panel_id, "version": 1}).encode("utf-8")}
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


_PANEL_CSV_ROWS: dict[str, dict[str, str]] = {
    "reg_province": {"data/reg_province.csv": "period,province,reg_type,brand,fuel_group,reg_count\n2569-08,x,รย.1,TOY,ICE,10\n"},
    "reg_trend": {"data/reg_trend.csv": (
        "period,province,reg_type,brand,model_group_id,model_name,reg_count\n"
        "2569-08,x,รย.1,TOY,toy.a,A,10\n"
        "2569-08,x,รย.1,TOY,toy.b,B,6\n"
        "2569-08,x,รย.1,TOY,toy.c,C,4\n")},
    "reg_powertrain": {"data/reg_powertrain.csv": "period,province,reg_type,brand,model_group_id,model_name,fuel_group,reg_est,reg_min,reg_max,certainty\n2569-08,x,รย.1,TOY,toy.a,A,ICE,10,,exact\n"},
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
        "dims/model_group.csv": "model_group_id,model_name,brand,reg_total_all\ntoy.a,A,TOY,10\n",
    },
}


def _build_full_package(
    tmp_path: Path, *, status: str = "พร้อมส่ง", confirmed_by: list | None = None,
    panels: list[str] | None = None, validator: bytes | None = FAKE_VALIDATOR_OK,
    master_version: str = "M1", changelog_since: str | None = None,
    tamper_panel: str | None = None,
) -> Path:
    confirmed_by = ["Owner A", "Owner B"] if confirmed_by is None else confirmed_by
    panels = list(ice_package.PANEL_IDS) if panels is None else panels

    panel_zip_bytes = {}
    for panel_id in panels:
        raw = _panel_zip_bytes(panel_id, _PANEL_CSV_ROWS[panel_id], tamper=(panel_id == tamper_panel))
        panel_zip_bytes[f"panels/{panel_id}.zip"] = raw

    index = {
        "period": "2569-08", "version": 1, "master_version": master_version,
        "status": status, "confirmed_by": confirmed_by, "changelog_since": changelog_since,
        "panels": panels,
        "files": {name: {"md5": hashlib.md5(data).hexdigest()} for name, data in panel_zip_bytes.items()},
    }

    out = tmp_path / f"TDR_FULL_2569-08_v1_M1_{next(_unique)}.zip"
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr("full_package.json", json.dumps(index).encode("utf-8"))
        zf.writestr("CHANGELOG.csv", b"col1,col2\n")
        if validator is not None:
            zf.writestr("validate_package.py", validator)
        for name, data in panel_zip_bytes.items():
            zf.writestr(name, data)
    return out


# ---------------------------------------------------------------------------
# --check (offline)
# ---------------------------------------------------------------------------

def test_a_fully_valid_synthetic_package_has_no_problems(tmp_path):
    path = _build_full_package(tmp_path)
    assert cli.check(path) == []


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
    # The module must only ever execute the validator bytes it read out of the
    # package itself -- never import or shell out to a fixed repo-local path.
    assert "automotive/vehicle_master/tools/validate_package" not in source
    assert "from tools import validate_package" not in source
    assert "from tools.validate_package" not in source


# ---------------------------------------------------------------------------
# --apply (fake REST layer; never touches a real database)
# ---------------------------------------------------------------------------

class FakeRest:
    def __init__(self):
        self.calls: list[tuple] = []
        self._imports: list[dict] = []

    def __call__(self, method, path, payload=None, *, prefer=None):
        self.calls.append((method, path, payload, prefer))
        if method == "GET" and path.startswith("ice_package_imports"):
            return list(reversed(self._imports))[:1]
        if method == "POST" and path == "ice_package_imports":
            self._imports.append(payload)
            return None
        return None


def test_apply_refuses_and_writes_nothing_when_check_fails(tmp_path):
    path = _build_full_package(tmp_path, confirmed_by=[])
    rest = FakeRest()
    with pytest.raises(cli.IceImportError):
        cli.apply_package(path, rest=rest, imported_by="test")
    write_calls = [c for c in rest.calls if c[0] in ("POST", "DELETE")]
    assert write_calls == []


def test_apply_deletes_then_inserts_every_table_for_a_valid_package(tmp_path):
    path = _build_full_package(tmp_path)
    rest = FakeRest()
    summary = cli.apply_package(path, rest=rest, imported_by="tester")
    assert set(summary["tables"]) == set(cli.TABLES)

    for table in cli.TABLES:
        table_calls = [c for c in rest.calls if c[1].startswith(table)]
        assert table_calls, table
        assert table_calls[0][0] == "DELETE", f"{table} must be deleted before being reloaded"
        assert any(c[0] == "POST" for c in table_calls[1:]), f"{table} got no insert"


def test_apply_inserts_the_actual_row_data(tmp_path):
    path = _build_full_package(tmp_path)
    rest = FakeRest()
    cli.apply_package(path, rest=rest, imported_by="tester")
    inserts = [c for c in rest.calls if c[0] == "POST" and c[1] == "ice_dims_brand"]
    assert len(inserts) == 1
    assert inserts[0][2] == [{"brand": "TOY"}]


def test_apply_chunks_large_tables(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "CHUNK_SIZE", 1)
    path = _build_full_package(tmp_path)
    rest = FakeRest()
    cli.apply_package(path, rest=rest, imported_by="tester")
    # ice_reg_trend's fixture carries 3 rows -- chunk size 1 must produce 3 separate inserts.
    inserts = [c for c in rest.calls if c[0] == "POST" and c[1] == "ice_reg_trend"]
    assert len(inserts) == 3, inserts
    for payload in (c[2] for c in inserts):
        assert len(payload) == 1
    all_model_ids = sorted(row["model_group_id"] for payload in (c[2] for c in inserts) for row in payload)
    assert all_model_ids == ["toy.a", "toy.b", "toy.c"]


def test_apply_does_not_over_chunk_when_rows_fit_in_one_page(tmp_path):
    path = _build_full_package(tmp_path)  # default CHUNK_SIZE (1000); 3 reg_trend rows
    rest = FakeRest()
    cli.apply_package(path, rest=rest, imported_by="tester")
    inserts = [c for c in rest.calls if c[0] == "POST" and c[1] == "ice_reg_trend"]
    assert len(inserts) == 1
    assert len(inserts[0][2]) == 3


def test_apply_records_the_import_metadata_row_last(tmp_path):
    path = _build_full_package(tmp_path, master_version="M7")
    rest = FakeRest()
    cli.apply_package(path, rest=rest, imported_by="tester")
    meta_calls = [c for c in rest.calls if c[1] == "ice_package_imports" and c[0] == "POST"]
    assert len(meta_calls) == 1
    payload = meta_calls[0][2]
    assert payload["master_version"] == "M7"
    assert payload["period"] == "2569-08"
    assert payload["imported_by"] == "tester"
    assert meta_calls[0] == rest.calls[-1], "the import log row must be written after every table"


def test_apply_passes_the_last_recorded_master_version_into_the_changelog_check(tmp_path):
    path = _build_full_package(tmp_path, changelog_since="M3")
    rest = FakeRest()
    rest._imports.append({"master_version": "M3"})
    # Should succeed: changelog_since (M3) matches the last recorded master_version (M3).
    cli.apply_package(path, rest=rest, imported_by="tester")

    path2 = _build_full_package(tmp_path, changelog_since="M3", master_version="M4")
    rest2 = FakeRest()
    rest2._imports.append({"master_version": "M9"})  # a version was skipped
    with pytest.raises(cli.IceImportError, match="changelog_since"):
        cli.apply_package(path2, rest=rest2, imported_by="tester")
