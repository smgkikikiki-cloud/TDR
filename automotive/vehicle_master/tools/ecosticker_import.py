#!/usr/bin/env python3
"""Run the monthly ECO Sticker export into the catalogue.

The export arrives once a month as a spreadsheet of every vehicle homologated
in Thailand. This is the one command that turns it into catalogue content:

    python -m tools.ecosticker_import export.xlsx --observed-at 2026-09-18

By default it only plans and writes the reports, which is the safe thing to
run first -- ``--apply`` is what actually writes. Applying goes through
``CanonicalInputPipeline``, the same path an admin's edit takes, so staging
validation, the revision audit and the catalogue's own invariants all hold; a
batch that would produce an invalid catalogue fails instead of landing.

Three reports come out, because the interesting number is never the one that
worked:

  applied     one line per row that became catalogue content
  unresolved  one line per row that did not, with the reason in Thai
  dropped     source values the registry refused, counted by field
  repaired    rows whose source measurements were corrected or withheld

The unresolved report is the point of the whole exercise. A row nobody can
place is not an error to be suppressed: it is a brand, a model or a generation
the catalogue does not describe yet, and it is meant to be read.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from typing import Any, Iterable

from vehreg.catalog import Catalog, DATA_DIR, DEFAULT_YEAR
from vehreg.comparable_specs import SpecRegistry
from vehreg.ecosticker_import import (
    MATCHED, NEW_TRIM, UNRESOLVED, ImportPlan, batches_from_plan, plan_import,
)
from vehreg.input_pipeline import CanonicalInputPipeline


def read_rows(path: Path) -> list[dict[str, Any]]:
    """The export's rows as plain dicts, from .xlsx or .csv alike.

    pandas is imported here rather than at module import: the catalogue's own
    code does not depend on it, and a missing spreadsheet library should fail
    this command rather than everything that imports this package.
    """
    import pandas

    if path.suffix.lower() in (".csv", ".tsv"):
        frame = pandas.read_csv(path, sep="\t" if path.suffix.lower() == ".tsv" else ",")
    else:
        frame = pandas.read_excel(path)
    return frame.to_dict(orient="records")


def unresolved_report(plan: ImportPlan, *, source: str, observed_at: str) -> dict[str, Any]:
    rows = [{
        "source_id": row.source_id,
        "brand": row.brand_raw,
        "model": row.model_raw,
        "eco_url": row.vehicle.source_url,
        "reason": row.reason,
    } for row in plan.of(UNRESOLVED)]
    return {
        "schema_version": 1,
        "generated_from": source,
        "observed_at": observed_at,
        "count": len(rows),
        "note": ("แถวที่ระบบจับคู่กับแคตตาล็อกไม่ได้ ต้องให้คนตัดสิน "
                 "ไม่ได้เดาให้ เพราะสเปกที่ผูกผิดรุ่นแก้ยากกว่าสเปกที่ยังไม่มี"),
        "rows": sorted(rows, key=lambda row: (row["brand"], row["model"])),
    }


def applied_report(plan: ImportPlan, *, source: str, observed_at: str) -> dict[str, Any]:
    rows = [{
        "source_id": row.source_id,
        "status": row.status,
        "model_id": row.model_id,
        "trim_id": row.trim_id,
        "trim_name": row.trim_name,
        "powertrain": row.vehicle.powertrain,
        "approved_at": row.vehicle.approved_at,
        "facts": len(row.specs),
    } for row in plan.rows if row.status != UNRESOLVED]
    return {
        "schema_version": 1,
        "generated_from": source,
        "observed_at": observed_at,
        "count": len(rows),
        "facts": sum(row["facts"] for row in rows),
        "rows": sorted(rows, key=lambda row: (row["model_id"] or "", row["trim_id"] or "")),
    }


def repaired_report(plan: ImportPlan, *, source: str) -> dict[str, Any]:
    """Every source value this run corrected or refused to publish.

    A silent correction is indistinguishable from a silent error, so each one
    says what the source stated and what was done about it.
    """
    rows = [{
        "source_id": row.source_id,
        "brand": row.brand_raw,
        "model": row.model_raw,
        "eco_url": row.vehicle.source_url,
        "repairs": row.vehicle.repairs,
    } for row in plan.rows if row.vehicle.repairs]
    return {
        "schema_version": 1,
        "generated_from": source,
        "count": len(rows),
        "rows": sorted(rows, key=lambda row: (row["brand"], row["model"])),
    }


def dropped_report(plan: ImportPlan) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in plan.rows:
        if row.status != UNRESOLVED:
            counts.update(row.dropped)
    return dict(counts.most_common())


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def apply_batches(batches: Iterable[dict[str, Any]], data_dir: Path) -> list[str]:
    """Applies every batch, returning the ids of any that did not land."""
    pipeline = CanonicalInputPipeline(data_dir)
    failed = []
    for batch in batches:
        result = pipeline.apply(batch)
        if result.status != "APPLIED":
            failed.append(f"{batch['batch_id']}: {result.status} {getattr(result, 'detail', '')}")
    return failed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Plan and apply the monthly ECO Sticker export")
    parser.add_argument("export", type=Path, help="the monthly .xlsx or .csv export")
    parser.add_argument("--observed-at", required=True,
                        help="YYYY-MM-DD, used only for rows whose approval date the "
                             "export does not state")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR)
    parser.add_argument("--actor", default="ecosticker-import")
    parser.add_argument("--report-dir", type=Path,
                        help="where the three reports go (default: alongside the "
                             "year's market data)")
    parser.add_argument("--apply", action="store_true",
                        help="write to the catalogue; without it nothing is changed")
    args = parser.parse_args(argv)

    rows = read_rows(args.export)
    catalog = Catalog.load(args.data_dir, args.year)
    registry = SpecRegistry.load(args.data_dir, args.year)
    if not registry.fields:
        parser.error(f"no comparable-spec registry under {args.data_dir}/{args.year}")

    plan = plan_import(rows, catalog, registry)
    summary = plan.summary()

    report_dir = args.report_dir or (args.data_dir / str(args.year) / "market" / "trims")
    stem = f"ecosticker_import_{args.observed_at}"
    _write(report_dir / f"{stem}_unresolved.json",
           unresolved_report(plan, source=args.export.name, observed_at=args.observed_at))
    _write(report_dir / f"{stem}_applied.json",
           applied_report(plan, source=args.export.name, observed_at=args.observed_at))
    _write(report_dir / f"{stem}_dropped.json", dropped_report(plan))
    _write(report_dir / f"{stem}_repaired.json",
           repaired_report(plan, source=args.export.name))

    batches = batches_from_plan(
        plan, registry, year=args.year, actor=args.actor,
        observed_at=args.observed_at, batch_prefix=stem.replace("_", "-"))

    print(f"rows {summary['rows']}  matched {summary[MATCHED]}  "
          f"new trims {summary[NEW_TRIM]}  unresolved {summary[UNRESOLVED]}")
    print(f"spec facts {summary['spec_facts']} in {len(batches)} batches")
    repaired = sum(1 for row in plan.rows if row.vehicle.repairs)
    if repaired:
        print(f"source measurements corrected or withheld on {repaired} rows")
    print(f"reports -> {report_dir}/{stem}_*.json")

    if not args.apply:
        print("planned only; re-run with --apply to write")
        return 0

    failed = apply_batches(batches, args.data_dir)
    if failed:
        for line in failed:
            print(f"FAILED {line}", file=sys.stderr)
        return 1

    problems = Catalog.load(args.data_dir, args.year).validate()
    if problems:
        for problem in problems[:20]:
            print(f"INVALID {problem}", file=sys.stderr)
        return 1
    print(f"applied {len(batches)} batches; catalogue validates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
