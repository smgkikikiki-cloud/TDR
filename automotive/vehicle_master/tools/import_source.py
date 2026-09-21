"""Import an ECO Sticker export into MarketTrim columns: resolve, patch, write.

    python -m tools.import_source export.xlsx --source ECO [--apply]

Without ``--apply`` it resolves and reports and writes nothing. With it, the
batches go straight through the canonical pipeline -- no queue, no review, no
PR. Rows the catalogue cannot place deterministically are written to an
exceptions file instead of being guessed at or parked in a review queue.

This is the ECO path specifically. Every source has its own shape, and
running one through another's normalizer produces confident nonsense:
registration files go to ``vehreg.registration_import`` instead, and a
source with no parser of its own is reported unsupported rather than fed to
whichever parser happens to be nearest. ``tools/import_worker.py`` is what
routes an uploaded file to the right one.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from vehreg.catalog import Catalog, DATA_DIR
from vehreg.comparable_specs import SpecRegistry
from vehreg.ecosticker_export import normalize_row
from vehreg.ecosticker_import import UNRESOLVED, plan_row
from vehreg.input_pipeline import CanonicalInputPipeline
from vehreg.source_import import (
    CREATED, EXCEPTION, PATCHED, ExistingTrim, RowOutcome, SourceRow,
    batches_from_commands, commands_from_outcomes, resolve_rows, summarize,
)

DEFAULT_YEAR = 2026


def read_rows(path: Path) -> list[dict]:
    import pandas

    frame = (pandas.read_csv(path) if path.suffix.lower() == ".csv"
             else pandas.read_excel(path))
    return frame.to_dict(orient="records")


def existing_trims(catalog: Catalog) -> list[ExistingTrim]:
    out = []
    for model_id in catalog.models:
        for trim in catalog.trims_of(model_id):
            out.append(ExistingTrim(
                canonical_id=trim.id, model_id=model_id,
                generation_id=trim.generation_id, name=trim.name,
                powertrain=trim.powertrain.value,
                columns={
                    "seats": trim.seats, "length_mm": trim.length_mm,
                    "width_mm": trim.width_mm, "height_mm": trim.height_mm,
                    "engine_cc": trim.engine_cc, "tire_front": trim.tire_front,
                    "tire_rear": trim.tire_rear,
                    "source_refs": {k: list(v) for k, v in (trim.source_refs or {}).items()},
                },
                source_ids=tuple(
                    str(v) for values in (trim.source_refs or {}).values() for v in values),
            ))
    return out


def source_rows(raw_rows, catalog: Catalog, registry: SpecRegistry,
                source_kind: str) -> tuple[list[SourceRow], list[dict]]:
    """Normalize and place each export row; unplaceable rows become exceptions."""
    rows: list[SourceRow] = []
    exceptions: list[dict] = []
    for raw in raw_rows:
        plan = plan_row(raw, catalog, registry)
        if plan.status == UNRESOLVED or not plan.model_id:
            exceptions.append({
                "source_id": plan.source_id, "brand": plan.brand_raw,
                "model": plan.model_raw, "reason": plan.reason or "identity unresolved",
            })
            continue
        rows.append(SourceRow(
            source_id=plan.source_id, source_kind=source_kind,
            model_id=plan.model_id, generation_id=plan.generation_id or "",
            powertrain=plan.vehicle.powertrain or "",
            trim_name=plan.trim_name or "",
            values=dict(normalize_row(raw).specs),
        ))
    return rows, exceptions


def exception_record(outcome: RowOutcome) -> dict:
    return {
        "source_id": outcome.row.source_id,
        "model_id": outcome.row.model_id,
        "trim_name": outcome.row.trim_name,
        "powertrain": outcome.row.powertrain,
        "reason": outcome.reason,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path)
    parser.add_argument("--source", default="ECO",
                        help="source kind; only ECO has a parser on this path")
    parser.add_argument("--source-ref", default="", help="where the export came from")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR)
    parser.add_argument("--actor", default="bulk-import")
    parser.add_argument("--report-dir", type=Path, default=None)
    parser.add_argument("--apply", action="store_true",
                        help="write through the canonical pipeline instead of reporting only")
    args = parser.parse_args(argv)
    if args.source.upper() != "ECO":
        raise SystemExit(
            f"{args.source.upper()} has no parser on the ECO path; "
            "route it to its own importer instead of normalizing it as ECO")

    catalog = Catalog.load(args.data_dir, args.year)
    registry = SpecRegistry.load(args.data_dir, args.year)
    raw_rows = read_rows(args.export)

    rows, unplaced = source_rows(raw_rows, catalog, registry, args.source)
    trims = existing_trims(catalog)
    generation_codes = {g.id: g.code for model_id in catalog.models
                        for g in catalog.generations_of(model_id) if g.code}
    outcomes = resolve_rows(rows, trims, known_generations=generation_codes)
    commands, stranded = commands_from_outcomes(
        outcomes, generation_codes=generation_codes,
        existing_by_trim={t.canonical_id: t for t in trims})

    exceptions = unplaced + [exception_record(o) for o in outcomes
                             if o.status == EXCEPTION] + [
        exception_record(o) for o in stranded]
    conflicts = [{"source_id": o.row.source_id, "trim_id": o.trim_id,
                  "conflicts": o.conflicts} for o in outcomes if o.conflicts]

    counts = summarize(outcomes)
    report = {
        "rows_read": len(raw_rows),
        "rows_placed": len(rows),
        "patched": counts.get(PATCHED, 0),
        "created": counts.get(CREATED, 0),
        "unchanged": counts.get("UNCHANGED", 0),
        "exceptions": len(exceptions),
        "conflicts": len(conflicts),
        "commands": len(commands),
        "applied": False,
    }

    batches = batches_from_commands(
        commands, year=args.year, source_kind=args.source,
        source_ref=args.source_ref or str(args.export.name),
        batch_prefix=f"import-{args.source.lower()}-{args.export.stem[:24]}")

    if args.apply and batches:
        pipeline = CanonicalInputPipeline(args.data_dir)
        for batch in batches:
            batch = {**batch, "actor": args.actor,
                     "submitted_at": datetime.now(timezone.utc).isoformat()}
            result = pipeline.apply(batch)
            if result.status != "APPLIED":
                raise SystemExit(f"batch {batch['batch_id']} returned {result.status}")
        report["applied"] = True

    report_dir = args.report_dir or (args.data_dir / str(args.year) / "market" / "trims")
    report_dir.mkdir(parents=True, exist_ok=True)
    stem = f"import_{args.source.lower()}_{args.export.stem[:24]}"
    (report_dir / f"{stem}_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (report_dir / f"{stem}_exceptions.json").write_text(
        json.dumps({"exceptions": exceptions, "conflicts": conflicts},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
