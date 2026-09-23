"""Import an ECO Sticker export into MarketTrim columns, comparable-spec
facts and price observations: resolve, patch, write.

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

This is also the one place a bulk ECO export becomes canonical commands --
``tools/ecosticker_import.py``'s monthly full-catalogue run uses the exact
same ``source_rows``/``resolve_rows``/``commands_from_outcomes``/
``spec_commands_from_outcomes``/``price_commands_from_outcomes`` pipeline
this module calls, so an ad-hoc admin upload and a monthly run resolve a
row's identity and its comparable-spec facts the same way. There used to be
a second, older implementation (``vehreg/ecosticker_import.py``'s own
``plan_row``/``commands_for``) that only this module's identity half ever
adopted; that duplication is retired.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path

from vehreg.catalog import Catalog, DATA_DIR
from vehreg.comparable_specs import SpecLedger, SpecRegistry
from vehreg.ecosticker_import import UNRESOLVED, plan_row
from vehreg.source_import import (
    CREATED, EXCEPTION, FIELD_TO_COLUMN, PATCHED, ExistingTrim, RowOutcome,
    SourceRow, batches_from_commands, commands_from_outcomes,
    preflight_spec_commands, price_commands_from_outcomes, resolve_rows,
    spec_commands_from_outcomes, summarize,
)
from vehreg.input_pipeline import CanonicalInputPipeline

DEFAULT_YEAR = 2026
#: The type an ECO Sticker's filed retail price is recorded as -- a
#: homologation filing, not a price list. PriceLedger.current_list_price()
#: only ever resolves the LIST_PRICE stream, so nothing written under this
#: type can surface as the price a reader is shown.
ECO_PRICE_TYPE = "ECO_STICKER_PRICE"


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
                # Read straight off FIELD_TO_COLUMN rather than a hand-kept
                # second list. A column that is mapped for writing but
                # missing here reads as blank, so the import would treat a
                # value somebody set by hand as absent and overwrite it --
                # the protection would be there and do nothing.
                columns={
                    **{column: getattr(trim, column, None)
                       for column in FIELD_TO_COLUMN.values()},
                    "source_refs": {k: list(v) for k, v in (trim.source_refs or {}).items()},
                },
                source_ids=tuple(
                    str(v) for values in (trim.source_refs or {}).values() for v in values),
            ))
    return out


def source_rows(raw_rows, catalog: Catalog, registry: SpecRegistry,
                source_kind: str) -> tuple[list[SourceRow], list[dict], dict[str, int]]:
    """Normalize and place each export row; unplaceable rows become exceptions.

    ``plan_row`` already folds the raw row (``normalize_row``) and filters it
    against the registry (``applicable_specs``) to resolve brand/model/
    generation identity -- calling either again here would be a second,
    possibly-drifting copy of that folding, not a second opinion of it, so
    ``plan.specs``/``plan.dropped``/``plan.vehicle`` are read directly rather
    than re-derived. Only ``plan.trim_id``/``plan.status``'s MATCHED/NEW_TRIM
    classification is not trusted here: which trim a row belongs to is
    resolve_rows()'s job below, since it also protects against creating a
    second copy of a grade some other row in this run left unclaimed --
    a check plan_row's own trim step does not make.
    """
    rows: list[SourceRow] = []
    exceptions: list[dict] = []
    dropped_counts: dict[str, int] = {}
    for raw in raw_rows:
        plan = plan_row(raw, catalog, registry)
        for key in plan.dropped:
            dropped_counts[key] = dropped_counts.get(key, 0) + 1
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
            # Unfiltered: MarketTrim's own columns are not a comparable-spec
            # registry concept, and column_patch must not lose a value just
            # because the registry does not (yet) define that key.
            values=dict(plan.vehicle.specs),
            # Registry-accepted only -- what applicable_specs() already
            # computed inside plan_row(), read here rather than re-derived.
            specs=dict(plan.specs),
            qualifiers=dict(plan.vehicle.qualifiers),
            observed_at=plan.vehicle.approved_at,
            source_ref=plan.vehicle.source_url,
            price_thb=plan.vehicle.price_thb,
        ))
    return rows, exceptions, dropped_counts


def exception_record(outcome: RowOutcome) -> dict:
    return {
        "source_id": outcome.row.source_id,
        "model_id": outcome.row.model_id,
        "trim_name": outcome.row.trim_name,
        "powertrain": outcome.row.powertrain,
        "reason": outcome.reason,
    }


@dataclass
class SourceImportPlan:
    """Everything a caller needs to report on or apply one export run.

    Built once by ``plan_source_import`` and read by both this module's own
    ``main`` and ``tools/ecosticker_import.py``'s monthly wrapper, so the
    two only ever differ in report shape and CLI flags -- never in how a
    row resolves or what commands it produces.
    """

    raw_rows: list[dict]
    rows: list[SourceRow]
    unplaced: list[dict]
    dropped_counts: dict[str, int]
    outcomes: list[RowOutcome]
    model_commands: list[dict]
    stranded: list[RowOutcome]
    spec_commands: list[dict]
    spec_conflicts: list[dict]
    price_commands: list[dict]
    price_suppressed: list[dict]

    @property
    def commands(self) -> list[dict]:
        return self.model_commands + self.spec_commands + self.price_commands

    @property
    def exception_outcomes(self) -> list[RowOutcome]:
        return [o for o in self.outcomes if o.status == EXCEPTION] + self.stranded


def plan_source_import(
    export: Path, *, catalog: Catalog, registry: SpecRegistry, source_kind: str,
    data_dir: Path, year: int, submitted_at: str,
) -> SourceImportPlan:
    """Resolve an export's rows and compile every command they produce.

    ``submitted_at`` is the run timestamp. Its calendar date is used only for
    a row whose source states no observation date of its own -- see
    ``spec_commands_from_outcomes``. A row with one is never overridden by it.
    The timestamp is validated before any rows are resolved or commands built.
    """
    submitted_text = str(submitted_at or "").strip()
    try:
        datetime.fromisoformat(submitted_text.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("submitted_at must be a valid ISO-8601 date or timestamp") from exc

    raw_rows = read_rows(export)
    rows, unplaced, dropped_counts = source_rows(raw_rows, catalog, registry, source_kind)
    trims = existing_trims(catalog)
    generation_codes = {g.id: g.code for model_id in catalog.models
                        for g in catalog.generations_of(model_id) if g.code}
    outcomes = resolve_rows(rows, trims, known_generations=generation_codes)
    model_commands, stranded = commands_from_outcomes(
        outcomes, generation_codes=generation_codes,
        existing_by_trim={t.canonical_id: t for t in trims})

    # Comparable-spec facts and price observations come after every
    # UPSERT_MODEL_BUNDLE: a CREATED row's trim does not exist in the
    # catalogue this pipeline reads until its own bundle command has run
    # (vehreg/canonical_write.py's CanonicalWritePipeline invalidates its
    # catalogue cache only when a bundle command writes), and APPEND_PRICE
    # has no by-reference fallback for a trim that is not there yet at all.
    ledger = SpecLedger.load(data_dir, year, registry=registry, catalog=catalog)
    existing_facts = {
        fact.fact_id: {
            "trim_id": fact.trim_id, "field_key": fact.field_key,
            "value_state": fact.value_state.value, "value": fact.value,
            "unit": fact.unit, "qualifiers": fact.qualifiers,
            "effective_from": fact.effective_from, "effective_to": fact.effective_to,
            "observed_at": fact.observed_at,
            "verification_status": fact.verification_status.value,
            "source": fact.source, "source_ref": fact.source_ref,
        } for fact in ledger.facts
    }
    candidate_spec_commands = spec_commands_from_outcomes(
        outcomes, registry=registry, existing_facts=existing_facts, submitted_at=submitted_at)
    spec_commands, spec_conflicts = preflight_spec_commands(
        candidate_spec_commands, registry=registry, existing_facts=existing_facts)
    price_commands, price_suppressed = price_commands_from_outcomes(
        outcomes, price_type=ECO_PRICE_TYPE, submitted_at=submitted_at)

    return SourceImportPlan(
        raw_rows=raw_rows, rows=rows, unplaced=unplaced, dropped_counts=dropped_counts,
        outcomes=outcomes, model_commands=model_commands, stranded=stranded,
        spec_commands=spec_commands, spec_conflicts=spec_conflicts,
        price_commands=price_commands, price_suppressed=price_suppressed,
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path)
    parser.add_argument("--source", default="ECO",
                        help="source kind; only ECO has a parser on this path")
    parser.add_argument("--source-ref", default="", help="where the export came from")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR)
    parser.add_argument("--actor", default="bulk-import")
    # The moment this import was submitted, which the worker passes from
    # the run row so a retry of that run is the same import, not a new one.
    parser.add_argument("--submitted-at",
                        default=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        help="ISO-8601 timestamp for the batches this run submits")
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
    plan = plan_source_import(
        args.export, catalog=catalog, registry=registry, source_kind=args.source,
        data_dir=args.data_dir, year=args.year, submitted_at=args.submitted_at)

    exceptions = plan.unplaced + [exception_record(o) for o in plan.exception_outcomes]
    conflicts = [{"source_id": o.row.source_id, "trim_id": o.trim_id,
                  "conflicts": o.conflicts} for o in plan.outcomes if o.conflicts]

    counts = summarize(plan.outcomes)
    commands = plan.commands
    report = {
        "rows_read": len(plan.raw_rows),
        "rows_placed": len(plan.rows),
        "patched": counts.get(PATCHED, 0),
        "created": counts.get(CREATED, 0),
        "unchanged": counts.get("UNCHANGED", 0),
        "exceptions": len(exceptions),
        "conflicts": len(conflicts),
        "facts": len(plan.spec_commands),
        "spec_conflicts": len(plan.spec_conflicts),
        "dropped": dict(sorted(plan.dropped_counts.items(), key=lambda item: -item[1])),
        "prices": len(plan.price_commands),
        "prices_suppressed": len(plan.price_suppressed),
        "commands": len(commands),
        "applied": False,
        # Whether the canonical Vehicle Master tree actually has a change
        # that needs a commit and a publish. Never inferred from `patched`
        # alone: a row classified PATCHED still runs through the same
        # write pipeline as every other command, and that pipeline always
        # appends an audit trail (revisions.jsonl/outbox.jsonl/shadow) even
        # when the underlying catalogue data ends up identical, so "a
        # command was generated" is not the same fact as "a command wrote
        # a real change". Below, `commands` empty (every row UNCHANGED or
        # EXCEPTION) already answers this before anything is applied; once
        # applied, a batch that turned out to be a byte-identical replay
        # of one already committed (idempotent_replay=True) does not count
        # either.
        "canonical_changed": False,
    }

    # The run's own timestamp, not the clock at the moment each batch is
    # sent. A retry has to produce the same batches to be recognised as a
    # retry; a fresh `now()` per batch made an interrupted import fail on
    # the batch that had already landed.
    batches = batches_from_commands(
        commands, year=args.year, source_kind=args.source,
        source_ref=args.source_ref or str(args.export.name),
        batch_prefix=f"import-{args.source.lower()}-{args.export.stem[:24]}",
        submitted_at=args.submitted_at, actor=args.actor)

    if args.apply and batches:
        pipeline = CanonicalInputPipeline(args.data_dir)
        for batch in batches:
            result = pipeline.apply(batch)
            if result.status != "APPLIED":
                raise SystemExit(f"batch {batch['batch_id']} returned {result.status}")
            if not result.idempotent_replay and result.changed_files:
                report["canonical_changed"] = True
        report["applied"] = True
    elif not args.apply:
        # Dry run: no pipeline was asked to write anything, so the closest
        # honest answer is "would a command have been sent at all".
        report["canonical_changed"] = bool(commands)

    report_dir = args.report_dir or (args.data_dir / str(args.year) / "market" / "trims")
    report_dir.mkdir(parents=True, exist_ok=True)
    stem = f"import_{args.source.lower()}_{args.export.stem[:24]}"
    (report_dir / f"{stem}_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (report_dir / f"{stem}_exceptions.json").write_text(
        json.dumps({"exceptions": exceptions, "conflicts": conflicts,
                   "spec_conflicts": plan.spec_conflicts,
                   "price_suppressed": plan.price_suppressed},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
