"""Pure structural validation for an Ice Full Package (Market Track M2).

Everything here operates on in-memory bytes/dicts only -- no filesystem, no
network, no Supabase. ``tools/ice_package_import.py`` is the thin I/O wrapper
around this module. Keeping the rules here pure means they are fully testable
with synthetic fixtures, independent of whether a real package is on hand.

Reference: ``.claude/skills/tdr-package-import/SKILL.md``,
``docs/vehicle-db/VEHICLE_DB_V3.md`` §14.1. Nothing here imports anything;
``verify_full_package`` only ever reports problems.

UNVERIFIED ASSUMPTION -- isolated here, not left implicit: the exact outer
``full_package.json`` schema below (the field names ``status``,
``confirmed_by``, ``panels``, ``files``, ``period``, ``version``,
``master_version``, ``changelog_since``) has never been observed in a real
Full Package. Every real delivery inspected for M2 so far was missing that
file entirely (the two incomplete 2569-08 drops found on the owner's
filesystem had no ``full_package.json`` at all). This shape is inferred from
the skill's prose and the owner's own field list, nothing more.
``OUTER_PACKAGE_SCHEMA_VERIFIED_AGAINST_REAL_FILE`` below is ``False`` for
exactly that reason -- flip it (and update this note) the first time a real
``full_package.json`` is actually inspected. If its real field names differ,
only ``verify_full_package_status``/``verify_panel_set``/
``verify_package_md5_index``/``verify_changelog_continuity`` and their test
fixtures need to change -- nothing in the SQL schema (migration_v62) depends
on this assumption; every table/column there is ground-truthed against the
real per-panel ``manifest.json``/``panel.json``/CSV headers already
inspected, independently of what the outer wrapper turns out to look like.
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass, field
from typing import Any

PANEL_IDS: tuple[str, ...] = (
    "dims", "reg_province", "reg_trend", "reg_powertrain", "rim_province", "tyre_province",
)

REQUIRED_STATUS = "พร้อมส่ง"
REQUIRED_CONFIRMED_BY = 2

#: See the module docstring's "UNVERIFIED ASSUMPTION" note. Set to True only
#: once a real full_package.json has actually been read and these field names
#: confirmed against it.
OUTER_PACKAGE_SCHEMA_VERIFIED_AGAINST_REAL_FILE = False

#: Ground-truthed against the real Ice delivery inspected for M2 (period 2569-08,
#: panel version 2) for every panel except reg_powertrain, which was never
#: delivered -- its columns come from the skill's own §1 table instead.
#: dims/model_group.csv may additionally carry segment/body (the skill's contract
#: names them; the first real delivery did not include them).
PANEL_SCHEMAS: dict[str, dict[str, list[str]]] = {
    "reg_province": {
        "data/reg_province.csv": ["period", "province", "reg_type", "brand", "fuel_group", "reg_count"],
    },
    "reg_trend": {
        "data/reg_trend.csv": [
            "period", "province", "reg_type", "brand", "model_group_id", "model_name", "reg_count"],
    },
    "reg_powertrain": {
        "data/reg_powertrain.csv": [
            "period", "province", "reg_type", "brand", "model_group_id", "model_name",
            "fuel_group", "reg_est", "reg_min", "reg_max", "certainty"],
    },
    "rim_province": {
        "data/rim_province.csv": ["period", "province", "reg_type", "brand", "rim_bucket", "reg_est"],
        "data/coverage.csv": ["period", "province", "reg_type", "brand", "reg_total", "reg_tyre_known"],
    },
    "tyre_province": {
        "data/tyre_province.csv": [
            "period", "province", "reg_type", "brand", "tyre_size", "rim_inch", "reg_est"],
        "data/coverage.csv": ["period", "province", "reg_type", "brand", "reg_total", "reg_tyre_known"],
    },
    "dims": {
        "dims/brand.csv": ["brand"],
        "dims/province.csv": ["province"],
        "dims/reg_type.csv": ["reg_type"],
        "dims/fuel.csv": ["fuel_dlt", "fuel_group"],
        "dims/tyre.csv": ["tyre_size", "rim_inch"],
        "dims/model_group.csv": ["model_group_id", "model_name", "brand", "reg_total_all"],
    },
}

#: dims/model_group.csv may carry these without it being a problem (contract
#: allows them; the first real delivery omitted them -- never inferred).
_OPTIONAL_EXTRA_COLUMNS = {
    "dims/model_group.csv": {"segment", "body"},
}


class IcePackageError(RuntimeError):
    pass


@dataclass
class PanelManifest:
    panel_id: str
    version: int
    files: dict[str, dict[str, Any]]
    confirmed_by: list
    period_from: str | None
    period_to: str | None
    problems: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# full_package.json
# ---------------------------------------------------------------------------

def parse_full_package_index(data: bytes) -> dict:
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IcePackageError(f"full_package.json is not valid JSON: {exc}") from exc


def verify_full_package_status(index: dict) -> list[str]:
    """§2 step 1: md5 (checked elsewhere) + status + confirmed_by."""
    problems = []
    status = index.get("status")
    if status != REQUIRED_STATUS:
        problems.append(f"status is {status!r}, must be {REQUIRED_STATUS!r} before import")
    confirmed_by = index.get("confirmed_by") or []
    if len(confirmed_by) < REQUIRED_CONFIRMED_BY:
        problems.append(
            f"confirmed_by has {len(confirmed_by)} name(s) ({confirmed_by!r}), "
            f"needs at least {REQUIRED_CONFIRMED_BY}")
    return problems


def verify_panel_set(index: dict) -> list[str]:
    declared = set(index.get("panels") or [])
    missing = set(PANEL_IDS) - declared
    extra = declared - set(PANEL_IDS)
    problems = []
    if missing:
        problems.append(f"missing panel(s): {sorted(missing)}")
    if extra:
        problems.append(f"unexpected panel(s) not in the known contract: {sorted(extra)}")
    return problems


def verify_package_md5_index(index: dict, panel_zip_bytes: dict[str, bytes]) -> list[str]:
    """``index['files']`` maps each panel zip's filename (inside panels/) to its
    declared md5, per the skill's full_package.json contract."""
    problems = []
    declared_files = index.get("files") or {}
    for filename, meta in declared_files.items():
        if filename not in panel_zip_bytes:
            problems.append(f"full_package.json lists {filename!r} but it is not in the package")
            continue
        actual = hashlib.md5(panel_zip_bytes[filename]).hexdigest()
        declared = meta.get("md5") if isinstance(meta, dict) else meta
        if actual != declared:
            problems.append(f"{filename}: md5 mismatch (declared {declared!r}, actual {actual!r})")
    for filename in panel_zip_bytes:
        if filename not in declared_files:
            problems.append(f"{filename} is in the package but not listed in full_package.json")
    return problems


def verify_changelog_continuity(index: dict, previous_master_version: str | None) -> list[str]:
    """§3: a ``changelog_since`` that does not match the last imported
    ``master_version`` means a version was skipped -- notify Ice before importing.
    Only meaningful from the second import onward (``previous_master_version``
    is ``None`` for the very first import, so there is nothing to compare)."""
    if previous_master_version is None:
        return []
    changelog_since = index.get("changelog_since")
    if changelog_since != previous_master_version:
        return [
            f"changelog_since {changelog_since!r} does not match the last imported "
            f"master_version {previous_master_version!r} -- a version was skipped; "
            "notify Ice before importing"]
    return []


# ---------------------------------------------------------------------------
# Per-panel inner zip
# ---------------------------------------------------------------------------

def parse_panel_manifest(zf: zipfile.ZipFile) -> dict:
    try:
        manifest_bytes = zf.read("manifest.json")
    except KeyError as exc:
        raise IcePackageError("panel zip has no manifest.json") from exc
    return parse_full_package_index(manifest_bytes)


def verify_panel_internal(panel_id: str, zf: zipfile.ZipFile) -> list[str]:
    """Structural + md5 self-consistency of one panel zip against its own
    manifest.json -- the same check already proven by hand against the real
    (partial) M2 delivery, now a reusable, tested function."""
    problems: list[str] = []
    names = set(zf.namelist())
    for required in ("manifest.json", "panel.json"):
        if required not in names:
            problems.append(f"{panel_id}: missing {required}")
    if problems:
        return problems

    manifest = parse_panel_manifest(zf)
    panel_meta = parse_full_package_index(zf.read("panel.json"))
    if manifest.get("panel_id") != panel_id:
        problems.append(
            f"{panel_id}: manifest.json panel_id is {manifest.get('panel_id')!r}, expected {panel_id!r}")
    if manifest.get("panel_id") != panel_meta.get("panel_id"):
        problems.append(f"{panel_id}: manifest.json and panel.json disagree on panel_id")
    if manifest.get("version") != panel_meta.get("version"):
        problems.append(f"{panel_id}: manifest.json and panel.json disagree on version")

    declared_files = manifest.get("files") or {}
    for filename, meta in declared_files.items():
        if filename not in names:
            problems.append(f"{panel_id}: manifest.json lists {filename!r} but it is not in the zip")
            continue
        actual = hashlib.md5(zf.read(filename)).hexdigest()
        declared = meta.get("md5") if isinstance(meta, dict) else meta
        if actual != declared:
            problems.append(f"{panel_id}: {filename} md5 mismatch (declared {declared!r}, actual {actual!r})")
    for filename in names - {"manifest.json"}:
        if filename not in declared_files:
            problems.append(f"{panel_id}: {filename} is in the zip but not listed in manifest.json")

    schemas = PANEL_SCHEMAS.get(panel_id, {})
    for filename, expected_columns in schemas.items():
        if filename not in names:
            continue  # already reported as missing above if it truly should exist
        try:
            header_line = zf.read(filename).split(b"\n", 1)[0]
            header = [c.strip() for c in header_line.decode("utf-8-sig").split(",")]
        except Exception as exc:  # pragma: no cover - defensive
            problems.append(f"{panel_id}: could not read header of {filename}: {exc}")
            continue
        problems.extend(verify_csv_header(panel_id, filename, header))

    return problems


def verify_csv_header(panel_id: str, filename: str, header: list[str]) -> list[str]:
    expected = PANEL_SCHEMAS.get(panel_id, {}).get(filename)
    if expected is None:
        return []
    allowed_extra = _OPTIONAL_EXTRA_COLUMNS.get(filename, set())
    missing = [c for c in expected if c not in header]
    extra = [c for c in header if c not in expected and c not in allowed_extra]
    problems = []
    if missing:
        problems.append(f"{panel_id}/{filename}: missing column(s) {missing}")
    if extra:
        problems.append(f"{panel_id}/{filename}: unexpected column(s) {extra}")
    return problems


# ---------------------------------------------------------------------------
# Cross-panel post-import reconciliation (§2 step 4) -- pure, over row lists
# ---------------------------------------------------------------------------

def _sum_by_key(rows: list[dict], key_fields: tuple[str, ...], value_field: str) -> dict[tuple, float]:
    totals: dict[tuple, float] = {}
    for row in rows:
        key = tuple(row.get(f) for f in key_fields)
        value = row.get(value_field)
        if value is None:
            continue
        totals[key] = totals.get(key, 0.0) + float(value)
    return totals


def check_reg_province_matches_reg_trend(
    reg_province_rows: list[dict], reg_trend_rows: list[dict],
) -> list[str]:
    """§2 step 4: "ยอดรายเดือน reg_province = reg_trend" -- exact, same
    (period, province, reg_type) totals on both sides."""
    key = ("period", "province", "reg_type")
    province_totals = _sum_by_key(reg_province_rows, key, "reg_count")
    trend_totals = _sum_by_key(reg_trend_rows, key, "reg_count")
    problems = []
    for k in sorted(set(province_totals) | set(trend_totals)):
        a, b = province_totals.get(k, 0.0), trend_totals.get(k, 0.0)
        if a != b:
            problems.append(f"reg_province vs reg_trend at {k}: {a} != {b}")
    return problems


def _powertrain_value(row: dict) -> float | None:
    if row.get("reg_est") is not None:
        return float(row["reg_est"])
    if row.get("reg_min") is not None and row.get("reg_max") is not None:
        return (float(row["reg_min"]) + float(row["reg_max"])) / 2
    return None


def check_reg_powertrain_matches_reg_trend(
    reg_powertrain_rows: list[dict], reg_trend_rows: list[dict], *, tolerance: float = 0.5,
) -> list[str]:
    """§2 step 4: "ผลรวม reg_powertrain ... = reg_trend (±0.5)"."""
    key = ("period", "province", "reg_type", "model_group_id")
    trend_totals = _sum_by_key(reg_trend_rows, key, "reg_count")
    powertrain_totals: dict[tuple, float] = {}
    for row in reg_powertrain_rows:
        value = _powertrain_value(row)
        if value is None:
            continue
        k = tuple(row.get(f) for f in key)
        powertrain_totals[k] = powertrain_totals.get(k, 0.0) + value
    problems = []
    for k in sorted(set(powertrain_totals) | set(trend_totals)):
        a, b = powertrain_totals.get(k, 0.0), trend_totals.get(k, 0.0)
        if abs(a - b) > tolerance:
            problems.append(f"reg_powertrain vs reg_trend at {k}: {a} vs {b} (diff {abs(a - b)} > {tolerance})")
    return problems
