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

This is a thin wrapper, not a second importer: resolving a row's identity,
deciding what it changes, and turning that into UPSERT_MODEL_BUNDLE/
APPEND_SPEC/APPEND_PRICE commands is entirely ``tools.import_source.
plan_source_import`` -- the exact function an ad-hoc admin upload calls too.
What is specific to this command is the CLI surface (``--observed-at``
rather than ``--submitted-at``) and the four reports below, both kept
because a monthly full-catalogue run reads differently to a person than a
single admin upload does.

Four reports come out, because the interesting number is never the one that
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
from typing import Any

from vehreg.catalog import Catalog, DATA_DIR, DEFAULT_YEAR
from vehreg.comparable_specs import SpecRegistry
from vehreg.input_pipeline import CanonicalInputPipeline
from vehreg.source_import import (
    CREATED, EXCEPTION, PATCHED, batches_from_commands, resolved_trim_id,
)
from tools.import_source import SourceImportPlan, plan_source_import

_STATUS_LABEL = {PATCHED: "MATCHED", CREATED: "NEW_TRIM"}


def unresolved_report(plan: SourceImportPlan, *, source: str, observed_at: str) -> dict[str, Any]:
    rows = [{
        "source_id": entry["source_id"], "brand": entry["brand"],
        "model": entry["model"], "reason": entry["reason"],
    } for entry in plan.unplaced]
    rows += [{
        "source_id": o.row.source_id, "brand": o.row.model_id.split(".", 1)[0],
        "model": o.row.model_id, "reason": o.reason,
    } for o in plan.exception_outcomes]
    return {
        "schema_version": 1,
        "generated_from": source,
        "observed_at": observed_at,
        "count": len(rows),
        "note": ("แถวที่ระบบจับคู่กับแคตตาล็อกไม่ได้ ต้องให้คนตัดสิน "
                 "ไม่ได้เดาให้ เพราะสเปกที่ผูกผิดรุ่นแก้ยากกว่าสเปกที่ยังไม่มี"),
        "rows": sorted(rows, key=lambda row: (row["brand"], row["model"])),
    }


def applied_report(plan: SourceImportPlan, *, source: str, observed_at: str) -> dict[str, Any]:
    facts_by_source_id: Counter[str] = Counter()
    for command in plan.spec_commands:
        source_id = command["payload"]["fact_id"].split(":", 2)[1]
        facts_by_source_id[source_id] += 1
    # ecosticker_export.NormalizedVehicle.source_url is a deterministic
    # function of source_id, so this is keyed by the same identity a
    # SourceRow carries even though the command payload itself has no
    # source_id field of its own to key on directly.
    price_by_source_ref = {
        command["payload"]["source_ref"]: command["payload"]["amount_thb"]
        for command in plan.price_commands
    }
    suppressed_source_ids = {entry["source_id"] for entry in plan.price_suppressed}

    rows = []
    for outcome in plan.outcomes:
        if outcome.status == EXCEPTION:
            continue
        row = outcome.row
        price_thb = (None if row.source_id in suppressed_source_ids
                    else price_by_source_ref.get(row.source_ref))
        rows.append({
            "source_id": row.source_id,
            "status": _STATUS_LABEL.get(outcome.status, outcome.status),
            "model_id": row.model_id,
            "trim_id": resolved_trim_id(outcome),
            "trim_name": row.trim_name,
            "powertrain": row.powertrain,
            "approved_at": row.observed_at,
            "facts": facts_by_source_id.get(row.source_id, 0),
            "price_thb": price_thb,
        })
    return {
        "schema_version": 1,
        "generated_from": source,
        "observed_at": observed_at,
        "count": len(rows),
        "facts": sum(row["facts"] for row in rows),
        "rows": sorted(rows, key=lambda row: (row["model_id"] or "", row["trim_id"] or "")),
    }


def repaired_report(plan: SourceImportPlan, *, source: str) -> dict[str, Any]:
    """Every dated price this run withheld because two records disagreed.

    ``ecosticker_export.normalize_row``'s own value repairs (a bad unit, an
    out-of-range figure) are reported by ``dropped_report`` instead, counted
    by field rather than by row -- ``applicable_specs`` folds a repair and a
    registry-refused value into the same ``dropped`` list, and splitting
    them back out per row is not information this module has.
    """
    by_source_id: dict[str, dict[str, Any]] = {}
    for entry in plan.price_suppressed:
        by_source_id.setdefault(entry["source_id"], {
            "source_id": entry["source_id"], "trim_id": entry["trim_id"], "repairs": {},
        })["repairs"]["price"] = entry["reason"]
    rows = sorted(by_source_id.values(), key=lambda row: row["source_id"])
    return {
        "schema_version": 1,
        "generated_from": source,
        "count": len(rows),
        "rows": rows,
    }


def dropped_report(plan: SourceImportPlan) -> dict[str, int]:
    return dict(Counter(plan.dropped_counts).most_common())


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def apply_batches(batches: list[dict[str, Any]], data_dir: Path) -> list[str]:
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
                        help="where the four reports go (default: alongside the "
                             "year's market data)")
    parser.add_argument("--apply", action="store_true",
                        help="write to the catalogue; without it nothing is changed")
    args = parser.parse_args(argv)

    catalog = Catalog.load(args.data_dir, args.year)
    registry = SpecRegistry.load(args.data_dir, args.year)
    if not registry.fields:
        parser.error(f"no comparable-spec registry under {args.data_dir}/{args.year}")

    plan = plan_source_import(
        args.export, catalog=catalog, registry=registry, source_kind="ECO",
        data_dir=args.data_dir, year=args.year, submitted_at=args.observed_at)

    report_dir = args.report_dir or (args.data_dir / str(args.year) / "market" / "trims")
    stem = f"ecosticker_import_{args.observed_at}"
    _write(report_dir / f"{stem}_unresolved.json",
           unresolved_report(plan, source=args.export.name, observed_at=args.observed_at))
    _write(report_dir / f"{stem}_applied.json",
           applied_report(plan, source=args.export.name, observed_at=args.observed_at))
    _write(report_dir / f"{stem}_dropped.json", dropped_report(plan))
    _write(report_dir / f"{stem}_repaired.json",
           repaired_report(plan, source=args.export.name))

    batches = batches_from_commands(
        plan.commands, year=args.year, source_kind="ECO",
        source_ref=args.export.name, batch_prefix=stem.replace("_", "-"),
        submitted_at=f"{args.observed_at}T00:00:00+00:00", actor=args.actor)

    matched = sum(1 for o in plan.outcomes if o.status == PATCHED)
    created = sum(1 for o in plan.outcomes if o.status == CREATED)
    unresolved = len(plan.unplaced) + len(plan.exception_outcomes)
    print(f"rows {len(plan.raw_rows)}  matched {matched}  "
          f"new trims {created}  unresolved {unresolved}")
    print(f"spec facts {len(plan.spec_commands)} in {len(batches)} batches")
    print(f"price observations {len(plan.price_commands)} "
          f"({len(plan.price_suppressed)} withheld)")
    if plan.price_suppressed:
        print(f"prices withheld on {len(plan.price_suppressed)} rows")
    print(f"reports -> {report_dir}/{stem}_*.json")

    if not args.apply:
        print("planned only; re-run with --apply to write")
        return 0

    if not batches:
        print("nothing to apply")
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
