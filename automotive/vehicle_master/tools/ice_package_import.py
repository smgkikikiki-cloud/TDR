"""Validate, and (once approved) import, an Ice Full Package (Market Track M2).

    python -m tools.ice_package_import --check path/to/TDR_FULL_<period>_v<n>_M<ver>.zip
    python -m tools.ice_package_import --apply path/to/TDR_FULL_<period>_v<n>_M<ver>.zip \\
        --imported-by "name" --repo-root /path/to/this/repo

``--check`` is fully offline: it only reads the local zip file and reports
every problem found via ``vehreg.ice_package`` -- status/confirmed_by, the
six-panel set, the package-level md5 index, changelog continuity against the
last recorded import, each panel's own internal manifest/md5/column-header
consistency, AND the cross-panel reconciliation checks (reg_province ==
reg_trend; reg_powertrain ~= reg_trend ±0.5) over the package's own rows. It
never touches Supabase, and ``--apply`` always runs it first.

``--apply`` additionally requires ``SUPABASE_URL``/``SUPABASE_SECRET_KEY`` (or
the legacy ``SUPABASE_SERVICE_ROLE_KEY``) and performs a transactional
"replace whole set" import (tdr-package-import/SKILL.md §2 step 3):

1. ``check()`` must pass with zero problems (structural + reconciliation) --
   no live or staging table is touched before this.
2. Every one of the twelve panel/dims tables is loaded into its
   ``<table>_staging`` twin (migration_v62). A failure here never touches a
   *live* table -- staging is never read by anything live.
3. One RPC, ``ice_commit_staged_import``, runs as one Postgres transaction:
   it replaces every live table from its staging twin and records the
   import-log row together, or raises and leaves every live table exactly as
   it was. The importer never issues its own DELETE/INSERT against a live
   table.
4. An independent post-commit readback (``ice_live_table_counts``) is
   compared against the rows actually sent, and any discrepancy raises
   loudly -- the import has already committed by this point, so this can
   only report a problem, never undo one; a clean readback is the expected
   path, not a formality.
5. Only after a successful commit *and* a clean readback does the importer
   update the package-versioning log (``data/packages/ล่าสุด.json``,
   ``ประวัติการนำเข้า.csv``, and the archived package copy, archiving any
   other active version folder for the same period first --
   tdr-package-import/SKILL.md §6/§6.2) -- never on any failure path, so
   ``ล่าสุด.json``/history never advance as though a failed import had
   succeeded.

``--repo-root`` is **required** with ``--apply`` at the CLI: a real import
must never be allowed to silently skip the versioning state. (The
``apply_package``/``update_package_version_log`` functions themselves still
accept an optional ``repo_root`` for other programmatic callers and tests --
only the CLI enforces that a production ``--apply`` always provides one.)
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from tools.canonical_input_worker import _request
from vehreg import ice_package

RestCall = Callable[..., Any]

#: table name -> (declared panel_id this table belongs to, the CSV file(s) inside
#: that panel's inner zip that feed it, the table's primary-key columns, matching
#: migration_v62 exactly -- including fuel_group in ice_reg_powertrain's PK). A
#: panel may feed more than one table (dims; rim/tyre_province also feed the
#: shared coverage table).
TABLES: dict[str, dict[str, Any]] = {
    "ice_reg_province": {
        "panel_id": "reg_province", "source": "data/reg_province.csv",
        "pk": ("period", "province", "reg_type", "brand", "fuel_group")},
    "ice_reg_trend": {
        "panel_id": "reg_trend", "source": "data/reg_trend.csv",
        "pk": ("period", "province", "reg_type", "brand", "model_group_id")},
    "ice_reg_powertrain": {
        "panel_id": "reg_powertrain", "source": "data/reg_powertrain.csv",
        "pk": ("period", "province", "reg_type", "brand", "model_group_id", "fuel_group")},
    "ice_rim_province": {
        "panel_id": "rim_province", "source": "data/rim_province.csv",
        "pk": ("period", "province", "reg_type", "brand", "rim_bucket")},
    "ice_tyre_province": {
        "panel_id": "tyre_province", "source": "data/tyre_province.csv",
        "pk": ("period", "province", "reg_type", "brand", "tyre_size")},
    "ice_tyre_coverage": {
        "panel_id": "rim_province", "source": "data/coverage.csv",
        "pk": ("period", "province", "reg_type", "brand")},
    "ice_dims_brand": {"panel_id": "dims", "source": "dims/brand.csv", "pk": ("brand",)},
    "ice_dims_province": {"panel_id": "dims", "source": "dims/province.csv", "pk": ("province",)},
    "ice_dims_reg_type": {"panel_id": "dims", "source": "dims/reg_type.csv", "pk": ("reg_type",)},
    "ice_dims_fuel": {"panel_id": "dims", "source": "dims/fuel.csv", "pk": ("fuel_dlt",)},
    "ice_dims_tyre": {"panel_id": "dims", "source": "dims/tyre.csv", "pk": ("tyre_size",)},
    "ice_dims_model_group": {"panel_id": "dims", "source": "dims/model_group.csv", "pk": ("model_group_id",)},
}

#: The three panels the §2 step-4 reconciliation checks run over.
_RECONCILIATION_TABLES = {
    "reg_province": "ice_reg_province",
    "reg_trend": "ice_reg_trend",
    "reg_powertrain": "ice_reg_powertrain",
}

CHUNK_SIZE = 1000

#: tdr-package-import/SKILL.md §6.
PACKAGES_DIR_NAME = "data/packages"


class IceImportError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Loading the outer TDR_FULL_*.zip
# ---------------------------------------------------------------------------

class LoadedPackage:
    def __init__(
        self, *, index: dict, panel_zip_bytes: dict[str, bytes],
        validator_source: bytes | None, changelog_csv: bytes | None, raw_names: list[str],
        id_changes_csv: bytes | None = None,
    ):
        self.index = index
        self.panel_zip_bytes = panel_zip_bytes  # "panels/<name>.zip" -> bytes
        self.validator_source = validator_source
        self.changelog_csv = changelog_csv
        self.id_changes_csv = id_changes_csv
        self.raw_names = raw_names

    def open_panel(self, panel_id: str) -> zipfile.ZipFile | None:
        for name, data in self.panel_zip_bytes.items():
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as zf:
                    manifest = ice_package.parse_panel_manifest(zf)
            except Exception:
                continue
            if manifest.get("panel_id") == panel_id:
                return zipfile.ZipFile(io.BytesIO(data))
        return None


def load_package(path: Path) -> LoadedPackage:
    with zipfile.ZipFile(path) as outer:
        names = outer.namelist()
        if "full_package.json" not in names:
            raise IceImportError(f"{path}: no full_package.json at the top level")
        index = ice_package.parse_full_package_index(outer.read("full_package.json"))
        panel_zip_bytes = {
            name: outer.read(name) for name in names
            if name.startswith("panels/") and name.endswith(".zip")}
        validator_source = outer.read("validate_package.py") if "validate_package.py" in names else None
        changelog_csv = outer.read("CHANGELOG.csv") if "CHANGELOG.csv" in names else None
        id_changes_csv = outer.read("id_changes.csv") if "id_changes.csv" in names else None
    return LoadedPackage(
        index=index, panel_zip_bytes=panel_zip_bytes,
        validator_source=validator_source, changelog_csv=changelog_csv,
        id_changes_csv=id_changes_csv, raw_names=names)


# ---------------------------------------------------------------------------
# The shipped validator -- never the superseded repo copy
# ---------------------------------------------------------------------------

def run_shipped_validator(package: LoadedPackage, package_path: Path) -> tuple[bool, str]:
    """Run the release's own validate_package.py against the panel zips, exactly
    as a human operator would (SKILL.md §2 step 2). Never substitutes any other
    copy -- if the package ships none, this is itself a check failure."""
    if package.validator_source is None:
        return False, "package ships no validate_package.py; cannot validate with the old repo copy (superseded)"
    with tempfile.TemporaryDirectory(prefix="ice-validate-") as tmp:
        tmp_path = Path(tmp)
        validator_path = tmp_path / "validate_package.py"
        validator_path.write_bytes(package.validator_source)
        panel_paths = []
        for name, data in package.panel_zip_bytes.items():
            dest = tmp_path / Path(name).name
            dest.write_bytes(data)
            panel_paths.append(str(dest))
        result = subprocess.run(
            [sys.executable, str(validator_path), *panel_paths],
            capture_output=True, text=True, cwd=tmp_path)
        output = (result.stdout or "") + (result.stderr or "")
        return result.returncode == 0, output


# ---------------------------------------------------------------------------
# --check: fully offline, structural + reconciliation
# ---------------------------------------------------------------------------

def _read_csv_rows(zf: zipfile.ZipFile, filename: str) -> list[dict[str, str]]:
    with zf.open(filename) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
        return list(csv.DictReader(text))


def check_split(
    path: Path, *, previous_master_version: str | None = None,
    previous_model_group_ids: set[str] | None = None, owner_declared_final: str | None = None,
) -> tuple[list[str], list[str], list[dict]]:
    """Returns ``(structural_problems, authority_problems, panel_releases)``.

    Structural: the package is intact, self-consistent and reconciles.
    Authority: the package may be released to production -- owner declaration,
    release status, sign-offs, CHANGELOG, identity redirects, changelog
    continuity. A structurally valid package can still have no authority, and
    the status fields alone never supply it.

    ``previous_model_group_ids`` / ``previous_master_version`` are the last
    imported state; ``None`` means nothing has been imported yet.
    """
    try:
        package = load_package(path)
    except (IceImportError, ice_package.IcePackageError, zipfile.BadZipFile) as exc:
        return [str(exc)], [], []

    structural: list[str] = []
    authority: list[str] = []

    authority += ice_package.verify_release_authority(path.name, owner_declared_final)
    authority += ice_package.verify_full_package_status(package.index)
    authority += ice_package.verify_changelog_continuity(package.index, previous_master_version)
    structural += ice_package.verify_panel_set(package.index)
    structural += ice_package.verify_package_md5_index(package.index, package.panel_zip_bytes)

    changelog_problems, entity_change = ice_package.verify_changelog(package.changelog_csv)
    authority += changelog_problems

    panel_releases: list[dict] = []
    reconciliation_rows: dict[str, list[dict]] = {}
    coverage: dict[str, tuple[str, str]] = {}
    package_model_group_ids: set[str] = set()
    for panel_id in ice_package.PANEL_IDS:
        zf = package.open_panel(panel_id)
        if zf is None:
            structural.append(f"panel {panel_id!r} not found among the package's panel zips")
            continue
        with zf:
            structural += ice_package.verify_panel_internal(panel_id, zf)
            manifest = ice_package.parse_panel_manifest(zf)
            authority += ice_package.verify_panel_signoffs(panel_id, manifest)
            if isinstance(manifest.get("period_from"), str) and isinstance(manifest.get("period_to"), str):
                coverage[panel_id] = (manifest["period_from"], manifest["period_to"])
            if "panel.json" in zf.namelist():
                panel_meta = ice_package.parse_full_package_index(zf.read("panel.json"))
                release, release_problems = ice_package.parse_panel_release(panel_id, manifest, panel_meta)
                structural += release_problems
                if release is not None:
                    panel_releases.append(release)
            if panel_id == "dims":
                try:
                    package_model_group_ids = {
                        row["model_group_id"]
                        for row in _read_csv_rows(zf, TABLES["ice_dims_model_group"]["source"])}
                except Exception as exc:
                    structural.append(f"dims: could not read model_group_id values: {exc}")
            if panel_id in _RECONCILIATION_TABLES:
                table = _RECONCILIATION_TABLES[panel_id]
                try:
                    reconciliation_rows[panel_id] = _read_csv_rows(zf, TABLES[table]["source"])
                except Exception as exc:
                    structural.append(f"{panel_id}: could not read rows for reconciliation: {exc}")

    authority += ice_package.verify_id_changes(
        package.id_changes_csv,
        entity_change_declared=entity_change,
        package_model_group_ids=package_model_group_ids,
        previous_model_group_ids=previous_model_group_ids,
    )

    # §2 step 4: reg_province == reg_trend; reg_powertrain ~= reg_trend ±0.5.
    # Run fully offline, over the package's own rows -- before anything is
    # staged, let alone committed.
    if "reg_province" in reconciliation_rows and "reg_trend" in reconciliation_rows:
        structural += ice_package.check_reg_province_matches_reg_trend(
            reconciliation_rows["reg_province"], reconciliation_rows["reg_trend"])
    # Only over the overlap of the two panels' declared manifest coverage. Periods one
    # panel does not cover are outside its contract, not reconciliation failures.
    if "reg_powertrain" in reconciliation_rows and "reg_trend" in reconciliation_rows:
        if "reg_powertrain" not in coverage or "reg_trend" not in coverage:
            structural.append("reg_powertrain / reg_trend: manifest period_from/period_to missing; cannot scope reconciliation")
        else:
            window = ice_package.coverage_intersection(coverage["reg_powertrain"], coverage["reg_trend"])
            if window is None:
                structural.append("reg_powertrain / reg_trend declared coverage ranges do not overlap")
            else:
                powertrain_rows = [r for r in reconciliation_rows["reg_powertrain"] if ice_package.in_coverage(r["period"], window)]
                trend_rows = [r for r in reconciliation_rows["reg_trend"] if ice_package.in_coverage(r["period"], window)]
                structural += ice_package.check_reg_powertrain_matches_reg_trend(powertrain_rows, trend_rows)

    ok, output = run_shipped_validator(package, path)
    if not ok:
        structural.append(f"shipped validate_package.py failed:\n{output.strip()}")

    return structural, authority, panel_releases


def check(
    path: Path, *, previous_master_version: str | None = None,
    previous_model_group_ids: set[str] | None = None, owner_declared_final: str | None = None,
) -> list[str]:
    """Every problem, structural and authority together. See ``check_split``."""
    structural, authority, _ = check_split(
        path, previous_master_version=previous_master_version,
        previous_model_group_ids=previous_model_group_ids, owner_declared_final=owner_declared_final)
    return structural + authority


# ---------------------------------------------------------------------------
# --apply: stage every table, then one atomic commit RPC, then readback
# ---------------------------------------------------------------------------

def _chunks(rows: list[dict], size: int | None = None):
    if size is None:
        size = CHUNK_SIZE  # looked up at call time, not bound when the module loads
    for start in range(0, len(rows), size):
        yield rows[start:start + size]


def stage_table(table: str, rows: list[dict], *, rest: RestCall = _request) -> None:
    """Load one table's complete new rows into its `_staging` twin. Never
    touches the live table -- a failure here is invisible to anything live."""
    staging = f"{table}_staging"
    pk = TABLES[table]["pk"]
    # PostgREST refuses an unconditional DELETE; every PK column is NOT NULL by
    # schema, so filtering on the first PK column being non-null deletes every row.
    rest("DELETE", f"{staging}?{pk[0]}=not.is.null")
    for chunk in _chunks(rows):
        rest("POST", staging, chunk, prefer="return=minimal")


def commit_staged_import(
    index: dict, *, rest: RestCall = _request, imported_by: str, panel_releases: list[dict],
) -> dict:
    """The one atomic RPC call: staging -> live + import log, or nothing.

    ``p_panels`` carries the per-panel release metadata (panel_id, version,
    period_from, period_to, access, free_scope, confirmed_by), stored on the
    ``ice_package_imports`` row for this import. The row already links the
    package, period, package version and master_version, so the metadata stays
    tied to exactly the import that produced it.
    """
    payload = {
        "p_period": index.get("period"),
        "p_package_version": index.get("version"),
        "p_master_version": index.get("master_version"),
        "p_status": index.get("status"),
        "p_confirmed_by": index.get("confirmed_by"),
        "p_md5_index": ice_package.declared_panel_files(index),
        "p_panels": panel_releases,
        "p_imported_by": imported_by,
    }
    result = rest("POST", "rpc/ice_commit_staged_import", payload)
    if not isinstance(result, dict):
        raise IceImportError(f"ice_commit_staged_import returned an unexpected shape: {result!r}")
    return result


def _readback_sanity_check(expected_counts: dict[str, int], *, rest: RestCall = _request) -> None:
    """Independent post-commit read: re-count every live table and compare
    against what was actually sent. The import has already committed by the
    time this runs -- a mismatch can only be reported, never undone, so it is
    reported loudly rather than swallowed."""
    reported = rest("POST", "rpc/ice_live_table_counts", {})
    if not isinstance(reported, dict):
        raise IceImportError(f"ice_live_table_counts returned an unexpected shape: {reported!r}")
    problems = []
    for table, expected in expected_counts.items():
        actual = reported.get(table)
        if actual != expected:
            problems.append(f"{table}: live count is {actual}, expected {expected} from the committed package")
    if problems:
        raise IceImportError(
            "POST-COMMIT READBACK MISMATCH (the import already committed -- investigate immediately): "
            + "; ".join(problems))


# ---------------------------------------------------------------------------
# Package-versioning workflow (tdr-package-import/SKILL.md §6), written only
# after a successful commit + clean readback.
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


#: SKILL.md §6: "<period>/เวอร์ชันเก่า/<old_folder>_เก่า/" for a superseded
#: version of the same period, never deleted.
OLD_VERSIONS_DIR_NAME = "เวอร์ชันเก่า"
OLD_VERSION_SUFFIX = "_เก่า"


def package_folder_name(index: dict) -> str:
    """SKILL.md §6's folder template is literally ``v<n>_M<master_version>``.
    Whether the real ``master_version`` value Ice sends already includes the
    leading "M" is itself part of the unverified outer-schema assumption
    (vehreg/ice_package.py's module docstring) -- never having seen a real
    one, guard against double-prefixing either way rather than guess."""
    master_version = str(index.get("master_version") or "")
    master_label = master_version if master_version.upper().startswith("M") else f"M{master_version}"
    return f"v{index.get('version')}_{master_label}"


def _archive_superseded_version_folders(packages_dir: Path, period: str, new_folder_name: str) -> None:
    """SKILL.md §6.2 step 2: if this period already has a different active
    version folder, move it (never delete, never overwrite) under
    ``<period>/เวอร์ชันเก่า/<old_folder>_เก่า/``. A name collision at the
    destination (e.g. the same old folder name superseded twice) gets a safe,
    unique numbered suffix instead of clobbering the earlier archive."""
    period_dir = packages_dir / period
    if not period_dir.is_dir():
        return
    old_versions_dir = period_dir / OLD_VERSIONS_DIR_NAME
    for entry in sorted(period_dir.iterdir()):
        if not entry.is_dir() or entry.name in (OLD_VERSIONS_DIR_NAME, new_folder_name):
            continue
        old_versions_dir.mkdir(parents=True, exist_ok=True)
        dest = old_versions_dir / f"{entry.name}{OLD_VERSION_SUFFIX}"
        suffix = 2
        while dest.exists():
            dest = old_versions_dir / f"{entry.name}{OLD_VERSION_SUFFIX}_{suffix}"
            suffix += 1
        shutil.move(str(entry), str(dest))


def update_package_version_log(repo_root: Path, index: dict, package_path: Path, *, imported_by: str) -> None:
    """Write data/packages/ล่าสุด.json, append to ประวัติการนำเข้า.csv, archive
    any superseded same-period version folder, and copy the package archive
    into its new period/version folder -- SKILL.md §6/§6.2. Only ever called
    after apply_package's commit + readback succeed; never on any failure
    path, so a failed import cannot advance these.

    No real TDR_FULL_*.zip has existed yet to exercise the archive copy
    against in production; this path is implemented and tested against the
    synthetic package built in tests/test_ice_package_import.py, and is ready
    to populate data/packages/<period>/v<n>_M<master_version>/ the first time
    a real package is actually applied.
    """
    packages_dir = repo_root / PACKAGES_DIR_NAME
    period = index.get("period")
    folder_name = package_folder_name(index)

    _archive_superseded_version_folders(packages_dir, period, folder_name)

    period_dir = packages_dir / period / folder_name
    period_dir.mkdir(parents=True, exist_ok=True)

    dest_zip = period_dir / package_path.name
    if not dest_zip.exists():
        shutil.copy2(package_path, dest_zip)

    latest_path = packages_dir / "ล่าสุด.json"
    latest = {
        "period": period,
        "version": index.get("version"),
        "master_version": index.get("master_version"),
        "folder": f"{period}/{folder_name}",
        "md5": index.get("files"),
        "imported_at": _now_iso(),
    }
    latest_path.write_text(json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8")

    history_path = packages_dir / "ประวัติการนำเข้า.csv"
    is_new = not history_path.exists()
    # The BOM belongs once, at the true start of the file -- utf-8-sig would
    # re-emit it on every append, corrupting the file with embedded BOMs.
    mode, encoding = ("w", "utf-8-sig") if is_new else ("a", "utf-8")
    with history_path.open(mode, encoding=encoding, newline="") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(["วันที่", "งวด", "version", "master_version", "md5", "ผลตรวจ", "ผู้นำเข้า"])
        writer.writerow([
            _now_iso(), period, index.get("version"), index.get("master_version"),
            json.dumps(index.get("files"), ensure_ascii=False), "ผ่าน", imported_by])


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def apply_package(
    path: Path, *, rest: RestCall = _request, imported_by: str, repo_root: Path | None = None,
    owner_declared_final: str | None = None,
) -> dict:
    last = rest("GET", "ice_package_imports?select=master_version&order=imported_at.desc&limit=1") or []
    previous_master_version = last[0]["master_version"] if last else None
    # Only a previous import can have retired model groups, so the live ids are
    # read only then. Read-only, like the GET above.
    previous_model_group_ids = None
    if last:
        live_groups = rest("GET", "ice_dims_model_group?select=model_group_id") or []
        previous_model_group_ids = {row["model_group_id"] for row in live_groups}

    structural, authority, panel_releases = check_split(
        path, previous_master_version=previous_master_version,
        previous_model_group_ids=previous_model_group_ids, owner_declared_final=owner_declared_final)
    problems = structural + authority
    if problems:
        raise IceImportError("refusing to import: " + "; ".join(problems))

    # Everything above is read-only (one GET) plus local parsing. Zero live or
    # staging write has happened yet.
    package = load_package(path)
    index = package.index

    panel_rows: dict[str, list[dict]] = {}
    for table, meta in TABLES.items():
        zf = package.open_panel(meta["panel_id"])
        if zf is None:
            raise IceImportError(f"panel {meta['panel_id']!r} unexpectedly missing during apply")
        with zf:
            panel_rows[table] = _read_csv_rows(zf, meta["source"])

    try:
        for table, rows in panel_rows.items():
            stage_table(table, rows, rest=rest)
        commit_staged_import(index, rest=rest, imported_by=imported_by, panel_releases=panel_releases)
        _readback_sanity_check({table: len(rows) for table, rows in panel_rows.items()}, rest=rest)
    except IceImportError:
        raise
    except Exception as exc:
        raise IceImportError(
            f"import failed during staging/commit: {exc} -- the commit RPC is one Postgres "
            "transaction, so a failure here should leave every live table exactly as it was"
        ) from exc

    if repo_root is not None:
        update_package_version_log(repo_root, index, path, imported_by=imported_by)

    return {
        "period": index.get("period"),
        "master_version": index.get("master_version"),
        "tables": list(TABLES),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", metavar="PATH", type=Path, help="offline structural + reconciliation check only")
    mode.add_argument("--apply", metavar="PATH", type=Path, help="check, then transactional replace-whole-set import")
    parser.add_argument("--imported-by", default="", help="actor recorded on ice_package_imports (--apply only)")
    parser.add_argument(
        "--repo-root", type=Path, default=None,
        help="repo root to write data/packages/ into -- required with --apply, "
             "so a real import can never silently skip the versioning state")
    parser.add_argument(
        "--owner-declared-final", default=None, metavar="FILENAME",
        help="the exact package file name the owner has declared final. Without it the "
             "package is structurally checked but refused as production authority, and "
             "--apply refuses to import")
    args = parser.parse_args(argv)

    if args.check is not None:
        structural, authority, _ = check_split(args.check, owner_declared_final=args.owner_declared_final)
        for problem in structural + authority:
            print(f"INVALID: {problem}")
        report = {
            "path": str(args.check),
            "structurally_valid": not structural,
            "production_authorized": not authority,
            "valid": not structural and not authority,
        }
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report["valid"] else 1

    if not args.imported_by:
        print("INVALID: --imported-by is required with --apply")
        return 1
    if args.repo_root is None:
        print("INVALID: --repo-root is required with --apply -- a real import must always "
              "update data/packages/ล่าสุด.json and ประวัติการนำเข้า.csv, never skip them")
        return 1
    try:
        summary = apply_package(
            args.apply, imported_by=args.imported_by, repo_root=args.repo_root,
            owner_declared_final=args.owner_declared_final)
    except IceImportError as exc:
        print(f"INVALID: {exc}")
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
