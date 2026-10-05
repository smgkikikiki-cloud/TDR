"""Validate, and (once approved) import, an Ice Full Package (Market Track M2).

    python -m tools.ice_package_import --check path/to/TDR_FULL_<period>_v<n>_M<ver>.zip
    python -m tools.ice_package_import --apply path/to/TDR_FULL_<period>_v<n>_M<ver>.zip

``--check`` is fully offline: it only reads the local zip file and reports every
problem found via ``vehreg.ice_package`` (status/confirmed_by, the six-panel set,
the package-level md5 index, changelog continuity against the last recorded
import, and each panel's own internal manifest/md5/column-header consistency).
It never touches Supabase.

``--apply`` additionally requires ``SUPABASE_URL``/``SUPABASE_SECRET_KEY`` (or the
legacy ``SUPABASE_SERVICE_ROLE_KEY``) and performs the "replace whole set" import
(tdr-package-import/SKILL.md §2 step 3): every one of the twelve
``ice_*``/dims tables (migration_v62) is fully replaced, never merged -- Ice may
revise any historical period on any delivery. It refuses to write anything
unless ``--check``'s own gate passes with zero problems first, and it never runs
the old, superseded ``tools/validate_package.py`` -- only the ``validate_package.py``
shipped inside the package itself (``run_shipped_validator``), per the skill.

Every table is deleted and reloaded in full; a failure partway through must be
treated as the table being in a mixed state until the next successful import,
exactly as the skill's own "replace whole set" semantics intend.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Callable

from tools.canonical_input_worker import _request
from vehreg import ice_package

RestCall = Callable[..., Any]

#: table name -> (declared panel_id this table belongs to, the CSV file(s) inside
#: that panel's inner zip that feed it, the table's primary-key columns). A panel
#: may feed more than one table (dims; rim/tyre_province also feed the shared
#: coverage table).
TABLES: dict[str, dict[str, Any]] = {
    "ice_reg_province": {
        "panel_id": "reg_province", "source": "data/reg_province.csv",
        "pk": ("period", "province", "reg_type", "brand", "fuel_group")},
    "ice_reg_trend": {
        "panel_id": "reg_trend", "source": "data/reg_trend.csv",
        "pk": ("period", "province", "reg_type", "brand", "model_group_id")},
    "ice_reg_powertrain": {
        "panel_id": "reg_powertrain", "source": "data/reg_powertrain.csv",
        "pk": ("period", "province", "reg_type", "brand", "model_group_id")},
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

CHUNK_SIZE = 1000


class IceImportError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Loading the outer TDR_FULL_*.zip
# ---------------------------------------------------------------------------

class LoadedPackage:
    def __init__(
        self, *, index: dict, panel_zip_bytes: dict[str, bytes],
        validator_source: bytes | None, changelog_csv: bytes | None, raw_names: list[str],
    ):
        self.index = index
        self.panel_zip_bytes = panel_zip_bytes  # "panels/<name>.zip" -> bytes
        self.validator_source = validator_source
        self.changelog_csv = changelog_csv
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
    return LoadedPackage(
        index=index, panel_zip_bytes=panel_zip_bytes,
        validator_source=validator_source, changelog_csv=changelog_csv, raw_names=names)


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
# --check: fully offline
# ---------------------------------------------------------------------------

def check(path: Path, *, previous_master_version: str | None = None) -> list[str]:
    problems: list[str] = []
    try:
        package = load_package(path)
    except (IceImportError, ice_package.IcePackageError, zipfile.BadZipFile) as exc:
        return [str(exc)]

    problems += ice_package.verify_full_package_status(package.index)
    problems += ice_package.verify_panel_set(package.index)
    problems += ice_package.verify_package_md5_index(package.index, package.panel_zip_bytes)
    problems += ice_package.verify_changelog_continuity(package.index, previous_master_version)

    for panel_id in ice_package.PANEL_IDS:
        zf = package.open_panel(panel_id)
        if zf is None:
            problems.append(f"panel {panel_id!r} not found among the package's panel zips")
            continue
        with zf:
            problems += ice_package.verify_panel_internal(panel_id, zf)

    ok, output = run_shipped_validator(package, path)
    if not ok:
        problems.append(f"shipped validate_package.py failed:\n{output.strip()}")

    return problems


# ---------------------------------------------------------------------------
# --apply: replace-whole-set import (only after check() is clean)
# ---------------------------------------------------------------------------

def _read_csv_rows(zf: zipfile.ZipFile, filename: str) -> list[dict[str, str]]:
    with zf.open(filename) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
        return list(csv.DictReader(text))


def _chunks(rows: list[dict], size: int | None = None):
    if size is None:
        size = CHUNK_SIZE  # looked up at call time, not bound when the module loads
    for start in range(0, len(rows), size):
        yield rows[start:start + size]


def replace_table(table: str, rows: list[dict], *, rest: RestCall = _request) -> None:
    pk = TABLES[table]["pk"]
    # PostgREST refuses an unconditional DELETE; every PK column is NOT NULL by
    # schema, so filtering on the first PK column being non-null deletes every row.
    rest("DELETE", f"{table}?{pk[0]}=not.is.null")
    for chunk in _chunks(rows):
        rest("POST", table, chunk, prefer="return=minimal")


def apply_package(path: Path, *, rest: RestCall = _request, imported_by: str) -> dict:
    last = rest("GET", "ice_package_imports?select=master_version&order=imported_at.desc&limit=1") or []
    previous_master_version = last[0]["master_version"] if last else None

    problems = check(path, previous_master_version=previous_master_version)
    if problems:
        raise IceImportError("refusing to import: " + "; ".join(problems))

    package = load_package(path)
    index = package.index

    for table, meta in TABLES.items():
        zf = package.open_panel(meta["panel_id"])
        if zf is None:
            raise IceImportError(f"panel {meta['panel_id']!r} unexpectedly missing during apply")
        with zf:
            rows = _read_csv_rows(zf, meta["source"])
        replace_table(table, rows, rest=rest)

    rest("POST", "ice_package_imports", {
        "period": index.get("period"),
        "package_version": index.get("version"),
        "master_version": index.get("master_version"),
        "status": index.get("status"),
        "confirmed_by": index.get("confirmed_by"),
        "md5_index": index.get("files"),
        "panels": index.get("panels"),
        "imported_by": imported_by,
    }, prefer="return=minimal")

    return {"period": index.get("period"), "master_version": index.get("master_version"), "tables": list(TABLES)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", metavar="PATH", type=Path, help="offline structural check only")
    mode.add_argument("--apply", metavar="PATH", type=Path, help="check, then replace-whole-set import")
    parser.add_argument("--imported-by", default="", help="actor recorded on ice_package_imports (--apply only)")
    args = parser.parse_args(argv)

    if args.check is not None:
        problems = check(args.check)
        if problems:
            for problem in problems:
                print(f"INVALID: {problem}")
            return 1
        print(json.dumps({"valid": True, "path": str(args.check)}, ensure_ascii=False))
        return 0

    if not args.imported_by:
        print("INVALID: --imported-by is required with --apply")
        return 1
    try:
        summary = apply_package(args.apply, imported_by=args.imported_by)
    except IceImportError as exc:
        print(f"INVALID: {exc}")
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
