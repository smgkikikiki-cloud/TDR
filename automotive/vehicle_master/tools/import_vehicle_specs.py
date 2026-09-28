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
from pathlib import Path

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

    applied_batches = []
    changed_files: list[str] = []
    if apply:
        pipeline = CanonicalInputPipeline(DATA_DIR)
        for batch in batches:
            result = pipeline.apply(batch)
            applied_batches.append({
                "batch_id": result.batch_id,
                "status": result.status,
                "idempotent_replay": result.idempotent_replay,
            })
            changed_files.extend(result.changed_files)

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
