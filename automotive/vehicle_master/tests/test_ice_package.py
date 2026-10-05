"""Market Track M2: pure Ice Full Package structural validation."""

from __future__ import annotations

import hashlib
import io
import zipfile

import pytest

from vehreg import ice_package


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _manifest(panel_id: str, version: int, files: dict[str, bytes]) -> bytes:
    import json
    return json.dumps({
        "panel_id": panel_id,
        "version": version,
        "period_from": "2564-01",
        "period_to": "2569-08",
        "files": {name: {"md5": hashlib.md5(data).hexdigest(), "bytes": len(data)} for name, data in files.items()},
        "qc_passed": True,
        "confirmed_by": [],
    }).encode("utf-8")


def _panel_json(panel_id: str, version: int) -> bytes:
    import json
    return json.dumps({"panel_id": panel_id, "version": version}).encode("utf-8")


def _valid_panel_zip(panel_id: str, version: int = 2, *, data_files: dict[str, bytes] | None = None) -> bytes:
    data_files = data_files or {}
    all_files = {**data_files, "panel.json": _panel_json(panel_id, version)}
    manifest = _manifest(panel_id, version, all_files)
    return _zip_bytes({**all_files, "manifest.json": manifest})


# ---------------------------------------------------------------------------
# full_package.json status/confirmed_by/panel set
# ---------------------------------------------------------------------------

def test_status_must_be_exactly_the_required_thai_string():
    assert ice_package.verify_full_package_status({"status": "พร้อมส่ง", "confirmed_by": ["a", "b"]}) == []
    problems = ice_package.verify_full_package_status({"status": "ร่าง", "confirmed_by": ["a", "b"]})
    assert any("status" in p for p in problems)


def test_confirmed_by_needs_at_least_two_names():
    assert ice_package.verify_full_package_status({"status": "พร้อมส่ง", "confirmed_by": ["a", "b"]}) == []
    problems = ice_package.verify_full_package_status({"status": "พร้อมส่ง", "confirmed_by": []})
    assert any("confirmed_by" in p for p in problems)
    problems_one = ice_package.verify_full_package_status({"status": "พร้อมส่ง", "confirmed_by": ["solo"]})
    assert any("confirmed_by" in p for p in problems_one)


def test_panel_set_requires_exactly_the_six_known_panels():
    full = list(ice_package.PANEL_IDS)
    assert ice_package.verify_panel_set({"panels": full}) == []
    missing_one = [p for p in full if p != "reg_powertrain"]
    problems = ice_package.verify_panel_set({"panels": missing_one})
    assert any("reg_powertrain" in p for p in problems)
    with_extra = full + ["something_new"]
    problems2 = ice_package.verify_panel_set({"panels": with_extra})
    assert any("something_new" in p for p in problems2)


# ---------------------------------------------------------------------------
# Package-level md5 index
# ---------------------------------------------------------------------------

def test_package_md5_index_catches_a_mismatch():
    panel_bytes = _valid_panel_zip("dims")
    index = {"files": {"panels/dims.zip": {"md5": "0" * 32}}}
    problems = ice_package.verify_package_md5_index(index, {"panels/dims.zip": panel_bytes})
    assert any("md5 mismatch" in p for p in problems)


def test_package_md5_index_passes_when_correct():
    panel_bytes = _valid_panel_zip("dims")
    index = {"files": {"panels/dims.zip": {"md5": hashlib.md5(panel_bytes).hexdigest()}}}
    assert ice_package.verify_package_md5_index(index, {"panels/dims.zip": panel_bytes}) == []


def test_package_md5_index_catches_an_undeclared_file():
    panel_bytes = _valid_panel_zip("dims")
    problems = ice_package.verify_package_md5_index({"files": {}}, {"panels/dims.zip": panel_bytes})
    assert any("not listed" in p for p in problems)


# ---------------------------------------------------------------------------
# CHANGELOG continuity
# ---------------------------------------------------------------------------

def test_changelog_continuity_is_skipped_on_the_very_first_import():
    assert ice_package.verify_changelog_continuity({"changelog_since": "M9"}, None) == []


def test_changelog_continuity_catches_a_skipped_version():
    problems = ice_package.verify_changelog_continuity({"changelog_since": "M9"}, "M10")
    assert any("changelog_since" in p for p in problems)


def test_changelog_continuity_passes_when_contiguous():
    assert ice_package.verify_changelog_continuity({"changelog_since": "M10"}, "M10") == []


# ---------------------------------------------------------------------------
# Per-panel internal consistency (manifest/panel.json/md5/columns)
# ---------------------------------------------------------------------------

def test_valid_panel_has_no_problems():
    data = {"data/dims_sample.csv": b"a,b\n1,2\n"}
    raw = _valid_panel_zip("dims", data_files=data)
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        assert ice_package.verify_panel_internal("dims", zf) == []


def test_panel_missing_manifest_is_caught():
    raw = _zip_bytes({"panel.json": _panel_json("dims", 2)})
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        problems = ice_package.verify_panel_internal("dims", zf)
    assert any("manifest.json" in p for p in problems)


def test_panel_id_mismatch_between_requested_and_manifest_is_caught():
    raw = _valid_panel_zip("reg_trend")
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        problems = ice_package.verify_panel_internal("dims", zf)  # asked for the wrong panel_id
    assert any("panel_id" in p for p in problems)


def test_panel_tampered_data_file_fails_md5():
    data = {"data/reg_trend.csv": b"period,province,reg_type,brand,model_group_id,model_name,reg_count\n"}
    raw_files = {**data, "panel.json": _panel_json("reg_trend", 2)}
    manifest = _manifest("reg_trend", 2, raw_files)
    tampered = _zip_bytes({**raw_files, "data/reg_trend.csv": b"TAMPERED", "manifest.json": manifest})
    with zipfile.ZipFile(io.BytesIO(tampered)) as zf:
        problems = ice_package.verify_panel_internal("reg_trend", zf)
    assert any("md5 mismatch" in p for p in problems)


def test_csv_header_catches_missing_and_unexpected_columns():
    good = ["period", "province", "reg_type", "brand", "fuel_group", "reg_count"]
    assert ice_package.verify_csv_header("reg_province", "data/reg_province.csv", good) == []

    missing_col = ["period", "province", "reg_type", "brand", "reg_count"]  # dropped fuel_group
    problems = ice_package.verify_csv_header("reg_province", "data/reg_province.csv", missing_col)
    assert any("missing column" in p and "fuel_group" in p for p in problems)

    extra_col = good + ["mystery_column"]
    problems2 = ice_package.verify_csv_header("reg_province", "data/reg_province.csv", extra_col)
    assert any("unexpected column" in p and "mystery_column" in p for p in problems2)


def test_dims_model_group_header_allows_segment_and_body_but_nothing_else():
    base = ["model_group_id", "model_name", "brand", "reg_total_all"]
    assert ice_package.verify_csv_header("dims", "dims/model_group.csv", base) == []
    with_contract_fields = base + ["segment", "body"]
    assert ice_package.verify_csv_header("dims", "dims/model_group.csv", with_contract_fields) == []
    with_junk = base + ["something_else"]
    problems = ice_package.verify_csv_header("dims", "dims/model_group.csv", with_junk)
    assert any("something_else" in p for p in problems)


def test_unknown_panel_id_has_no_schema_to_check_against():
    assert ice_package.verify_csv_header("not_a_real_panel", "whatever.csv", ["a"]) == []


# ---------------------------------------------------------------------------
# Post-import reconciliation (pure, over row lists)
# ---------------------------------------------------------------------------

def test_reg_province_matches_reg_trend_when_totals_agree():
    province = [{"period": "2569-08", "province": "กรุงเทพมหานคร", "reg_type": "รย.1", "reg_count": "10"}]
    trend = [
        {"period": "2569-08", "province": "กรุงเทพมหานคร", "reg_type": "รย.1", "model_group_id": "a", "reg_count": "6"},
        {"period": "2569-08", "province": "กรุงเทพมหานคร", "reg_type": "รย.1", "model_group_id": "b", "reg_count": "4"},
    ]
    assert ice_package.check_reg_province_matches_reg_trend(province, trend) == []


def test_reg_province_matches_reg_trend_catches_a_real_mismatch():
    province = [{"period": "2569-08", "province": "กรุงเทพมหานคร", "reg_type": "รย.1", "reg_count": "10"}]
    trend = [{"period": "2569-08", "province": "กรุงเทพมหานคร", "reg_type": "รย.1", "model_group_id": "a", "reg_count": "6"}]
    problems = ice_package.check_reg_province_matches_reg_trend(province, trend)
    assert len(problems) == 1
    assert "10" in problems[0] and "6" in problems[0]


def test_reg_powertrain_matches_reg_trend_within_tolerance():
    trend = [{"period": "2569-08", "province": "x", "reg_type": "รย.1", "model_group_id": "a", "reg_count": "100"}]
    powertrain_exact = [{"period": "2569-08", "province": "x", "reg_type": "รย.1", "model_group_id": "a", "reg_est": "100.3"}]
    assert ice_package.check_reg_powertrain_matches_reg_trend(powertrain_exact, trend) == []


def test_reg_powertrain_uses_min_max_midpoint_when_reg_est_is_absent():
    trend = [{"period": "2569-08", "province": "x", "reg_type": "รย.1", "model_group_id": "a", "reg_count": "100"}]
    powertrain_range = [{
        "period": "2569-08", "province": "x", "reg_type": "รย.1", "model_group_id": "a",
        "reg_est": None, "reg_min": "90", "reg_max": "110"}]
    assert ice_package.check_reg_powertrain_matches_reg_trend(powertrain_range, trend) == []


def test_reg_powertrain_catches_a_real_mismatch_beyond_tolerance():
    trend = [{"period": "2569-08", "province": "x", "reg_type": "รย.1", "model_group_id": "a", "reg_count": "100"}]
    powertrain_off = [{"period": "2569-08", "province": "x", "reg_type": "รย.1", "model_group_id": "a", "reg_est": "50"}]
    problems = ice_package.check_reg_powertrain_matches_reg_trend(powertrain_off, trend)
    assert len(problems) == 1
