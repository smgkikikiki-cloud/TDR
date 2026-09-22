"""Import an ECO Sticker export into canonical MarketTrim and spec facts.

    python -m tools.import_source export.xlsx --source ECO [--apply]

Without ``--apply`` it resolves and reports and writes nothing. With it, the
batches go straight through the canonical pipeline -- no queue, no review, no
PR. Rows the catalogue cannot place deterministically are written to an
exceptions file instead of being guessed at or parked in a review queue.

The ECO normalizer knows substantially more than the compact MarketTrim row
can hold. Values that have a MarketTrim representation still patch that row;
every registry-valid comparable value is also written as an evidence-backed
APPEND_SPEC fact. A field therefore stops disappearing merely because it has
no MarketTrim column of its own.

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
from typing import Iterable

from vehreg.catalog import Catalog, DATA_DIR
from vehreg.comparable_specs import SpecLedger, SpecRegistry
from vehreg.ecosticker_export import NormalizedVehicle, applicable_specs
from vehreg.ecosticker_import import UNRESOLVED, plan_row
from vehreg.input_pipeline import CanonicalInputPipeline
from vehreg.normalize import trim_identity
from vehreg.source_import import (
    CREATED, EXCEPTION, FIELD_TO_COLUMN, PATCHED, ExistingTrim, RowOutcome,
    SourceRow, batches_from_commands, commands_from_outcomes, resolve_rows,
    summarize,
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
                source_kind: str, *,
                vehicles: dict[str, NormalizedVehicle] | None = None,
                ) -> tuple[list[SourceRow], list[dict]]:
    """Normalize and place each export row; unplaceable rows become exceptions.

    ``vehicles`` is an optional sink for the already-normalized ECO record. It
    lets the write stage reuse exactly the same normalized values for
    comparable specs instead of parsing the spreadsheet a second time.
    """
    rows: list[SourceRow] = []
    exceptions: list[dict] = []
    for raw in raw_rows:
        plan = plan_row(raw, catalog, registry)
        if vehicles is not None and plan.source_id:
            vehicles[plan.source_id] = plan.vehicle
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
            values=dict(plan.vehicle.specs),
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


def _same_existing_fact(existing, *, trim_id: str, payload: dict) -> bool:
    """True when an ECO fact is already on disk byte-for-byte in meaning.

    APPEND_SPEC deliberately supports revising a fact_id, but a monthly ECO
    export repeats old approvals too. Emitting the same fact again would make
    a fresh audit revision for no data change, so the importer suppresses an
    exact replay before it reaches the writer.
    """
    return (
        existing.trim_id == trim_id
        and existing.field_key == payload["field_key"]
        and existing.value_state.value == payload["value_state"]
        and existing.value == payload["value"]
        and existing.unit == payload.get("unit", "")
        and dict(existing.qualifiers) == payload.get("qualifiers", {})
        and existing.observed_at == payload["observed_at"]
        and existing.effective_from is None
        and existing.effective_to is None
        and tuple(existing.claim_ids) == ()
        and existing.verification_status.value == payload["verification_status"]
        and existing.source == payload["source"]
        and existing.source_ref == payload["source_ref"]
        and existing.source_locator == payload["source_locator"]
    )


def spec_commands_from_outcomes(
    outcomes: Iterable[RowOutcome],
    *,
    vehicles: dict[str, NormalizedVehicle],
    registry: SpecRegistry,
    existing_facts: Iterable = (),
) -> tuple[list[dict], dict[str, int], list[dict]]:
    """Compile resolved ECO rows into APPEND_SPEC commands.

    Identity resolution remains the gate: an EXCEPTION gets no facts. Existing
    trims use their canonical id; a trim created by this same import is named
    with ``trim_ref`` so CanonicalWritePipeline resolves it with the exact same
    identity rule after the preceding UPSERT_MODEL_BUNDLE has created it.

    Same-day, same-context source disagreements are withheld as conflicts
    instead of letting SpecLedger reject the whole bulk batch. Equal duplicate
    claims are harmless and may coexist because they are distinct ECO records.
    """
    facts_by_id = {fact.fact_id: fact for fact in existing_facts}
    candidates: list[dict] = []
    groups: dict[tuple, list[dict]] = {}
    stats = {
        "spec_values_dropped": 0,
        "spec_rows_missing_observed_at": 0,
        "spec_rows_missing_source_id": 0,
        "spec_unchanged": 0,
        "spec_conflicts": 0,
    }

    for outcome in outcomes:
        if outcome.status == EXCEPTION:
            continue
        row = outcome.row
        vehicle = vehicles.get(row.source_id)
        if vehicle is None:
            continue
        if not vehicle.source_id:
            stats["spec_rows_missing_source_id"] += 1
            continue
        # A homologation fact is dated by the filing's own approval date. The
        # import clock is not evidence that the vehicle changed on that day.
        if not vehicle.approved_at:
            stats["spec_rows_missing_observed_at"] += 1
            continue

        specs, dropped = applicable_specs(vehicle, registry)
        stats["spec_values_dropped"] += len(dropped)
        if not specs:
            continue

        target_id = outcome.trim_id or trim_identity(
            row.generation_id, None, row.trim_name, row.powertrain)
        trim_ref = None if outcome.trim_id else {
            "generation_id": row.generation_id,
            "name": row.trim_name,
            "powertrain": row.powertrain,
        }

        for key, value in sorted(specs.items()):
            definition = registry.fields[key]
            payload = {
                "fact_id": f"eco:{vehicle.source_id}:{key}",
                "field_key": key,
                "value_state": "KNOWN",
                "value": value,
                "unit": definition.canonical_unit,
                "observed_at": vehicle.approved_at,
                "verification_status": "VERIFIED",
                "source": "ecosticker",
                "source_ref": vehicle.source_url,
                "source_locator": vehicle.source_url,
            }
            qualifiers = vehicle.qualifiers.get(key)
            if qualifiers:
                payload["qualifiers"] = qualifiers
            if trim_ref is None:
                payload["trim_id"] = target_id
            else:
                payload["trim_ref"] = trim_ref

            existing = facts_by_id.get(payload["fact_id"])
            if existing is not None and _same_existing_fact(
                    existing, trim_id=target_id, payload=payload):
                stats["spec_unchanged"] += 1
                continue

            command = {"operation": "APPEND_SPEC", "payload": payload}
            if trim_ref is None:
                command["canonical_id"] = target_id

            qualifier_key = json.dumps(
                payload.get("qualifiers", {}), ensure_ascii=False, sort_keys=True,
                separators=(",", ":"))
            group_key = (target_id, key, qualifier_key, vehicle.approved_at)
            candidate = {
                "command": command,
                "group_key": group_key,
                "target_id": target_id,
                "field_key": key,
                "source_id": vehicle.source_id,
                "value": value,
                "value_token": json.dumps(value, ensure_ascii=False, sort_keys=True),
                "qualifiers": payload.get("qualifiers", {}),
                "observed_at": vehicle.approved_at,
            }
            candidates.append(candidate)
            groups.setdefault(group_key, []).append(candidate)

    conflicting = {
        key for key, items in groups.items()
        if len({item["value_token"] for item in items}) > 1
    }
    conflicts: list[dict] = []
    for key in sorted(conflicting):
        items = groups[key]
        first = items[0]
        conflicts.append({
            "source_id": ",".join(sorted({item["source_id"] for item in items})),
            "trim_id": first["target_id"],
            "conflicts": [{
                "field_key": first["field_key"],
                "observed_at": first["observed_at"],
                "qualifiers": first["qualifiers"],
                "reason": "ECO records disagree for the same trim/spec/date/context",
                "values": [
                    {"source_id": item["source_id"], "value": item["value"]}
                    for item in items
                ],
            }],
        })
    stats["spec_conflicts"] = len(conflicts)
    commands = [item["command"] for item in candidates
                if item["group_key"] not in conflicting]
    return commands, stats, conflicts


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
    ledger = SpecLedger.load(args.data_dir, args.year, registry=registry, catalog=catalog)
    raw_rows = read_rows(args.export)

    vehicles: dict[str, NormalizedVehicle] = {}
    rows, unplaced = source_rows(
        raw_rows, catalog, registry, args.source, vehicles=vehicles)
    trims = existing_trims(catalog)
    generation_codes = {g.id: g.code for model_id in catalog.models
                        for g in catalog.generations_of(model_id) if g.code}
    outcomes = resolve_rows(rows, trims, known_generations=generation_codes)
    trim_commands, stranded = commands_from_outcomes(
        outcomes, generation_codes=generation_codes,
        existing_by_trim={t.canonical_id: t for t in trims})
    spec_commands, spec_stats, spec_conflicts = spec_commands_from_outcomes(
        outcomes, vehicles=vehicles, registry=registry, existing_facts=ledger.facts)
    # Every trim create/patch must precede every fact. A fact for a newly
    # created trim may therefore fall into a later batch and still resolve.
    commands = trim_commands + spec_commands

    exceptions = unplaced + [exception_record(o) for o in outcomes
                             if o.status == EXCEPTION] + [
        exception_record(o) for o in stranded]
    conflicts = [{"source_id": o.row.source_id, "trim_id": o.trim_id,
                  "conflicts": o.conflicts} for o in outcomes if o.conflicts]
    conflicts.extend(spec_conflicts)

    counts = summarize(outcomes)
    report = {
        "rows_read": len(raw_rows),
        "rows_placed": len(rows),
        "patched": counts.get(PATCHED, 0),
        "created": counts.get(CREATED, 0),
        "unchanged": counts.get("UNCHANGED", 0),
        "exceptions": len(exceptions),
        "conflicts": len(conflicts),
        "trim_commands": len(trim_commands),
        "spec_commands": len(spec_commands),
        **spec_stats,
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
        json.dumps({"exceptions": exceptions, "conflicts": conflicts},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
