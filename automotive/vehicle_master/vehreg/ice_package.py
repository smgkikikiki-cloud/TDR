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

import csv
import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from typing import Any

PANEL_IDS: tuple[str, ...] = (
    "dims", "reg_province", "reg_trend", "reg_powertrain", "rim_province", "tyre_province",
)

REQUIRED_STATUS = "พร้อมส่ง"
REQUIRED_CONFIRMED_BY = 2

#: tdr-package-import/SKILL.md §2 step 1: a file name carrying this marker is a draft, never production.
DRAFT_FILENAME_MARKER = "_ร่าง"

#: panel.json ``access`` values (SKILL.md §4 "free/pro/enterprise").
PANEL_ACCESS_VALUES = frozenset({"free", "pro", "enterprise"})

#: CHANGELOG.csv ``status`` values (read from the real header, R2 compatibility).
#: ``เสนอ`` = proposed, never a released fact -> refused. ``ออกเวอร์ชัน`` = released.
UNRESOLVED_CHANGELOG_STATUSES = frozenset({"เสนอ"})
RELEASED_CHANGELOG_STATUS = "ออกเวอร์ชัน"

#: CHANGELOG.csv ``entity`` value marking a model-group identity (crosswalk) change (SKILL.md §3).
CROSSWALK_ENTITY = "crosswalk"
CHANGELOG_REQUIRED_COLUMNS = frozenset({"change_id", "level", "entity", "status"})

#: SKILL.md §3 id_changes.csv contract.
ID_CHANGES_COLUMNS = frozenset({
    "old_model_group_id", "new_model_group_id", "reg_moved_all_periods", "share_of_old_pct", "type"})
ID_CHANGE_TYPES = frozenset({"เปลี่ยนรหัส", "รวม", "แยก"})

PERIOD_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}$")

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


def _bytes_mismatch(filename: str, meta: Any, actual_size: int) -> list[str]:
    """A declared ``bytes`` size is checked when present; a bare-md5 declaration has none to check."""
    if not isinstance(meta, dict) or "bytes" not in meta:
        return []
    if meta["bytes"] != actual_size:
        return [f"{filename}: size mismatch (declared {meta['bytes']!r} bytes, actual {actual_size})"]
    return []


def declared_panel_files(index: dict) -> dict[str, Any]:
    """Map ``panels/<file>`` -> declared ``{md5, bytes}``.

    Two shapes are accepted, and nothing is inferred beyond them. The real trial
    package declares ``panels`` as ``{panel_id: {file, md5, bytes}}`` with no
    ``files`` key (R2 compatibility). The earlier assumed shape was a ``files``
    map keyed by ``panels/<file>``.
    """
    if isinstance(index.get("files"), dict):
        return dict(index["files"])
    panels = index.get("panels")
    if isinstance(panels, dict):
        return {f"panels/{meta['file']}": meta for meta in panels.values()
                if isinstance(meta, dict) and isinstance(meta.get("file"), str)}
    return {}


def verify_package_md5_index(index: dict, panel_zip_bytes: dict[str, bytes]) -> list[str]:
    """Every panel zip's md5 and size must match the outer index."""
    problems = []
    declared_files = declared_panel_files(index)
    for filename, meta in declared_files.items():
        if filename not in panel_zip_bytes:
            problems.append(f"full_package.json lists {filename!r} but it is not in the package")
            continue
        actual = hashlib.md5(panel_zip_bytes[filename]).hexdigest()
        declared = meta.get("md5") if isinstance(meta, dict) else meta
        if actual != declared:
            problems.append(f"{filename}: md5 mismatch (declared {declared!r}, actual {actual!r})")
        problems += _bytes_mismatch(filename, meta, len(panel_zip_bytes[filename]))
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
        data = zf.read(filename)
        actual = hashlib.md5(data).hexdigest()
        declared = meta.get("md5") if isinstance(meta, dict) else meta
        if actual != declared:
            problems.append(f"{panel_id}: {filename} md5 mismatch (declared {declared!r}, actual {actual!r})")
        problems += [f"{panel_id}: {p}" for p in _bytes_mismatch(filename, meta, len(data))]
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


def coverage_intersection(first: tuple[str, str], second: tuple[str, str]) -> tuple[str, str] | None:
    """Overlap of two declared ``(period_from, period_to)`` manifest ranges, or None.

    Reconciliation between two panels runs only over this overlap. Nothing is
    hard-coded: a panel's start period is whatever its own manifest declares.
    """
    start = max(first[0], second[0])
    end = min(first[1], second[1])
    return (start, end) if start <= end else None


def in_coverage(period: str, window: tuple[str, str]) -> bool:
    return window[0] <= period <= window[1]


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


# ---------------------------------------------------------------------------
# Release authority (Market Track R1). A package can be structurally valid and
# still not be production authority: the status / sign-off fields are never
# enough on their own (ROADMAP.md, R0-R1).
# ---------------------------------------------------------------------------

def verify_release_authority(package_filename: str, owner_declared_final: str | None) -> list[str]:
    """Production authority needs an explicit owner declaration naming this exact file.

    ``owner_declared_final`` must equal the package's file name. Anything else
    (absent, a different name, a stale name) is refused, and the status and
    sign-off fields never substitute for the declaration.
    """
    problems = []
    if DRAFT_FILENAME_MARKER in package_filename:
        problems.append(
            f"{package_filename} carries the draft marker {DRAFT_FILENAME_MARKER!r} -- never publish to production")
    if owner_declared_final != package_filename:
        problems.append(
            f"no owner declaration that {package_filename!r} is final (declared: {owner_declared_final!r}); "
            "status and confirmed_by fields alone are not authority -- the owner must declare the exact package")
    return problems


def verify_panel_signoffs(panel_id: str, manifest: dict) -> list[str]:
    """Every panel manifest must carry the same two sign-offs as the package.

    Assumption: SKILL.md §2 step 2 ("manifest ... รวม confirmed_by 2 ชื่อ") applies
    to each panel's own manifest, not only the outer package. The first real
    delivery had ``confirmed_by: []`` in every panel manifest, so this is never
    inferred as satisfied.
    """
    confirmed_by = manifest.get("confirmed_by") or []
    if len(confirmed_by) < REQUIRED_CONFIRMED_BY:
        return [
            f"{panel_id}: manifest.json confirmed_by has {len(confirmed_by)} name(s), "
            f"needs at least {REQUIRED_CONFIRMED_BY}"]
    return []


def verify_changelog(changelog_csv: bytes | None) -> tuple[list[str], bool]:
    """Returns ``(problems, released_crosswalk_change_declared)``.

    Parsed by the real header (``change_id, date, level, entity, key, before, after,
    reason, impact_units, status, confirmed_by, released_in``); the required
    columns are checked, not assumed. A row still ``เสนอ`` is refused as
    unresolved, never treated as released. A released row whose ``entity`` is
    ``crosswalk`` is a model-group identity change, which requires the root
    ``id_changes.csv``. Redirects are never inferred from the row text.
    """
    if changelog_csv is None:
        return ["CHANGELOG.csv is missing -- release changes cannot be verified"], False
    try:
        text = changelog_csv.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        return [f"CHANGELOG.csv is not valid UTF-8: {exc}"], False

    reader = csv.DictReader(io.StringIO(text))
    columns = {c.strip() for c in (reader.fieldnames or [])}
    missing = sorted(CHANGELOG_REQUIRED_COLUMNS - columns)
    if missing:
        return [f"CHANGELOG.csv header lacks required column(s) {missing}"], False

    problems: list[str] = []
    crosswalk_released = False
    for line_no, row in enumerate(reader, start=2):
        status = (row.get("status") or "").strip()
        entity = (row.get("entity") or "").strip()
        if status in UNRESOLVED_CHANGELOG_STATUSES:
            problems.append(
                f"CHANGELOG.csv line {line_no} ({row.get('change_id')}) is still {status!r} -- an unresolved "
                "change is not a released fact; ask Ice to resolve it before importing")
        if entity == CROSSWALK_ENTITY and status == RELEASED_CHANGELOG_STATUS:
            crosswalk_released = True
    return problems, crosswalk_released


def verify_id_changes(
    id_changes_csv: bytes | None,
    *,
    entity_change_declared: bool,
    package_model_group_ids: set[str],
    previous_model_group_ids: set[str] | None,
) -> list[str]:
    """SKILL.md §3: identity changes need a machine-readable ``id_changes.csv``.

    Redirects are never inferred from prose. Absent, the package is refused when
    the CHANGELOG declares an entity change or when a previously imported
    model_group_id has disappeared. Present, its header and type vocabulary must
    match the contract, and every retired id must be covered by it.
    ``previous_model_group_ids`` is ``None`` on the first import, so nothing is retired yet.
    """
    retired = (previous_model_group_ids or set()) - package_model_group_ids

    if id_changes_csv is None:
        problems = []
        if entity_change_declared:
            problems.append(
                "CHANGELOG.csv declares a model-group identity change (entity) but id_changes.csv is absent -- "
                "redirects cannot be inferred from prose; ask Ice")
        if retired:
            problems.append(
                f"{len(retired)} previously imported model_group_id(s) are no longer in dims/model_group.csv "
                f"(e.g. {sorted(retired)[:3]}) but id_changes.csv is absent -- ask Ice; do not infer redirects")
        return problems

    try:
        text = id_changes_csv.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        return [f"id_changes.csv is not valid UTF-8: {exc}"]
    reader = csv.DictReader(io.StringIO(text))
    header = {column.strip() for column in (reader.fieldnames or [])}
    rows = list(reader)
    problems = []
    if header != ID_CHANGES_COLUMNS:
        problems.append(
            f"id_changes.csv columns are {sorted(header)}, must be exactly {sorted(ID_CHANGES_COLUMNS)}")
        return problems

    covered_old_ids: set[str] = set()
    for line_no, row in enumerate(rows, start=2):
        old_id = (row.get("old_model_group_id") or "").strip()
        new_id = (row.get("new_model_group_id") or "").strip()
        kind = (row.get("type") or "").strip()
        if not old_id or not new_id:
            problems.append(f"id_changes.csv line {line_no}: old/new model_group_id must both be set")
            continue
        if kind not in ID_CHANGE_TYPES:
            problems.append(f"id_changes.csv line {line_no}: unknown type {kind!r}")
        share = (row.get("share_of_old_pct") or "").strip()
        if share:
            try:
                float(share)
            except ValueError:
                problems.append(f"id_changes.csv line {line_no}: share_of_old_pct {share!r} is not a number")
        covered_old_ids.add(old_id)

    uncovered = retired - covered_old_ids
    if uncovered:
        problems.append(
            f"previously imported model_group_id(s) {sorted(uncovered)[:3]} are retired but id_changes.csv "
            "does not cover them -- ask Ice; do not infer redirects")
    return problems


# ---------------------------------------------------------------------------
# Per-panel release metadata (persisted with the import; read by M4 later)
# ---------------------------------------------------------------------------

def parse_panel_release(panel_id: str, manifest: dict, panel_meta: dict) -> tuple[dict | None, list[str]]:
    """Read one panel's publish window and access scope. Nothing is inferred or defaulted.

    ``period_from``/``period_to`` come from manifest.json (ROADMAP R1: "per-panel
    manifests carry period_from / period_to"). ``access``/``free_scope`` come from
    panel.json (SKILL.md §4). Either missing or malformed is a problem, never a
    default. Assumption: the real location of ``access``/``free_scope`` is only
    confirmed by the R2 compatibility pass against the real trial package.
    """
    problems: list[str] = []
    period_from = manifest.get("period_from")
    period_to = manifest.get("period_to")
    for label, value in (("period_from", period_from), ("period_to", period_to)):
        if not isinstance(value, str) or not PERIOD_PATTERN.match(value):
            problems.append(
                f"{panel_id}: manifest.json {label} is {value!r}, must be a 'YYYY-MM' string (never inferred)")
    if (isinstance(period_from, str) and isinstance(period_to, str)
            and PERIOD_PATTERN.match(period_from) and PERIOD_PATTERN.match(period_to)
            and period_from > period_to):
        problems.append(f"{panel_id}: period_from {period_from!r} is after period_to {period_to!r}")

    access = panel_meta.get("access")
    problems += verify_access_shape(panel_id, access)

    # free_scope is optional (R2 contract): preserved exactly when present, None when absent.
    # Never defaulted, and its absence alone never refuses a panel.
    free_scope = panel_meta.get("free_scope")

    if problems:
        return None, problems
    return {
        "panel_id": panel_id,
        "version": manifest.get("version"),
        "period_from": period_from,
        "period_to": period_to,
        "access": access,
        "free_scope": free_scope,
        "confirmed_by": manifest.get("confirmed_by") or [],
    }, []


def verify_access_shape(panel_id: str, access: Any) -> list[str]:
    """panel.json ``access`` is an object of per-capability tier lists, e.g.
    ``{"view": ["free", "pro"], "info": ["pro"], "csv": []}``. Tier values are
    explicit package data and are never inferred. Any other shape is a validation
    refusal, never an exception."""
    if not isinstance(access, dict) or not access:
        return [f"{panel_id}: panel.json access must be a non-empty object of capability -> tier list, got {access!r}"]
    problems = []
    for capability, tiers in access.items():
        if not isinstance(capability, str) or not capability:
            problems.append(f"{panel_id}: access capability name {capability!r} must be a non-empty string")
        if not isinstance(tiers, list) or not all(isinstance(t, str) and t in PANEL_ACCESS_VALUES for t in tiers):
            problems.append(
                f"{panel_id}: access[{capability!r}] must be a list of {sorted(PANEL_ACCESS_VALUES)}, got {tiers!r}")
    return problems
