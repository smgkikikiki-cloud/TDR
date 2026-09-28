"""Import a direct canonical vehicle-spec workbook.

    python -m tools.import_vehicle_specs workbook.xlsx
    python -m tools.import_vehicle_specs workbook.xlsx --apply

The workbook is not a source/evidence export. It is a deterministic edit surface
for existing MarketTrims: exact canonical trim id, fixed field headers, blank
means no-op, and no identity or field guessing.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile

from vehreg.catalog import Catalog, DATA_DIR, DEFAULT_YEAR
from vehreg.comparable_specs import SpecLedger, SpecRegistry
from vehreg.input_pipeline import CanonicalInputPipeline
from vehreg.source_import import batches_from_commands
from vehreg.spec_excel import SpecExcelError, compile_rows

DISPLAY_COLUMNS = frozenset({"brand", "model", "generation", "trim", "powertrain"})


def read_rows(path: Path) -> list[dict]:
    import pandas

    frame = (pandas.read_csv(path, keep_default_na=False)
             if path.suffix.lower() == ".csv"
             else pandas.read_excel(path, sheet_name="SPECS", keep_default_na=False))
    # Template display columns exist only so a human/AI can see which row it is
    # editing. Placement still comes solely from canonical_trim_id.
    return [
        {key: value for key, value in row.items() if str(key).strip() not in DISPLAY_COLUMNS}
        for row in frame.to_dict(orient="records")
    ]


def _submitted_at(raw: str | None) -> str:
    value = (raw or "").strip()
    if not value:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise SpecExcelError("submitted_at must include timezone")
    return parsed.isoformat(timespec="seconds")


def _relative_changed_path(raw: str) -> Path:
    relative = Path(str(raw))
    if relative.is_absolute() or ".." in relative.parts:
        raise RuntimeError(f"canonical pipeline returned unsafe changed path {raw!r}")
    return relative


def _promote_file(staged_data: Path, live_data: Path, relative: Path) -> None:
    source = staged_data / relative
    if not source.is_file():
        raise RuntimeError(f"canonical pipeline reported missing changed file {relative}")
    target = live_data / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_bytes(source.read_bytes())
    os.replace(temporary, target)


def _apply_batches_atomically(batches: list[dict], *, data_dir: Path) -> tuple[list[dict], list[str]]:
    """Apply every workbook batch to a sandbox, then promote only after all pass.

    CanonicalInputPipeline is atomic per batch. A workbook can exceed one batch,
    so applying batches directly to the live tree could leave the first batch
    behind when a later batch failed. The outer sandbox makes the workbook the
    transaction boundary instead.
    """
    if not batches:
        return [], []

    live_data = Path(data_dir)
    with tempfile.TemporaryDirectory(prefix="tdr-vehicle-spec-workbook-") as temp:
        staged_data = Path(temp) / "data"
        shutil.copytree(live_data, staged_data)
        pipeline = CanonicalInputPipeline(staged_data)

        applied_batches: list[dict] = []
        changed: set[Path] = set()
        for batch in batches:
            result = pipeline.apply(batch)
            applied_batches.append({
                "batch_id": result.batch_id,
                "status": result.status,
                "idempotent_replay": result.idempotent_replay,
            })
            changed.update(_relative_changed_path(path) for path in result.changed_files)

        # Data first, canonical_state/audit markers last, matching the existing
        # per-batch pipeline's recovery ordering. Sort the path as a tie-breaker
        # so promotion and reports do not depend on set/hash iteration order.
        ordered = sorted(
            changed,
            key=lambda path: ("canonical_state" in path.parts, str(path)),
        )
        for relative in ordered:
            _promote_file(staged_data, live_data, relative)

    return applied_batches, [str(path) for path in ordered]


def import_workbook(
    path: Path,
    *,
    year: int = DEFAULT_YEAR,
    apply: bool = False,
    submitted_at: str | None = None,
    actor: str = "vehicle-spec-excel",
    batch_prefix: str = "vehicle-spec-excel",
) -> dict:
    submitted = _submitted_at(submitted_at)
    observed_at = datetime.fromisoformat(submitted).date().isoformat()

    catalog = Catalog.load(DATA_DIR, year)
    registry = SpecRegistry.load(DATA_DIR, year)
    ledger = SpecLedger.load(DATA_DIR, year, registry=registry, catalog=catalog)
    rows = read_rows(path)
    compiled = compile_rows(
        rows,
        catalog=catalog,
        registry=registry,
        existing_facts=ledger.facts,
        observed_at=observed_at,
    )

    batches = batches_from_commands(
        list(compiled.commands),
        year=year,
        source_kind="ADMIN",
        source_ref="vehicle-spec-excel",
        batch_prefix=batch_prefix,
        submitted_at=submitted,
        actor=actor,
    ) if compiled.commands else []

    applied_batches: list[dict] = []
    changed_files: list[str] = []
    if apply:
        applied_batches, changed_files = _apply_batches_atomically(
            batches, data_dir=DATA_DIR)

    return {
        "schema_version": 1,
        "file": path.name,
        "year": year,
        "rows_read": compiled.rows_read,
        "rows_changed": compiled.rows_changed,
        "values_written": compiled.values_written,
        "values_unchanged": compiled.values_unchanged,
        "commands": len(compiled.commands),
        "batches": len(batches),
        "canonical_changed": bool(compiled.commands),
        "applied": apply,
        "applied_batches": applied_batches,
        "changed_files": sorted(set(changed_files)),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--submitted-at")
    parser.add_argument("--actor", default="vehicle-spec-excel")
    parser.add_argument("--batch-prefix", default="vehicle-spec-excel")
    parser.add_argument("--report-dir", type=Path)
    args = parser.parse_args(argv)

    report = import_workbook(
        args.file,
        year=args.year,
        apply=args.apply,
        submitted_at=args.submitted_at,
        actor=args.actor,
        batch_prefix=args.batch_prefix,
    )
    if args.report_dir:
        args.report_dir.mkdir(parents=True, exist_ok=True)
        target = args.report_dir / f"{args.file.stem}_vehicle_specs_report.json"
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
