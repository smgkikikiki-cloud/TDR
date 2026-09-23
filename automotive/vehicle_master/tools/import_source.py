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
from vehreg.comparable_specs import (
    ComparableCohort, SpecLedger, SpecRegistry, spec_conflict_key, spec_value_identity,
)
from vehreg.ecosticker_export import NormalizedVehicle, applicable_specs
from vehreg.ecosticker_import import UNRESOLVED, plan_row
from vehreg.input_pipeline import CanonicalInputPipeline
from vehreg.normalize import trim_identity
from vehreg.pricing import PriceLedger, PriceType
from vehreg.source_import import (
    CREATED, EXCEPTION, FIELD_TO_COLUMN, PATCHED, ExistingTrim, RowOutcome,
    SourceRow, batches_from_commands, commands_from_outcomes, resolve_rows,
    summarize,
)

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

            group_key = spec_conflict_key(
                definition, trim_id=target_id, field_key=key,
                qualifiers=payload.get("qualifiers", {}), start=vehicle.approved_at)
            candidate = {
                "command": command,
                "fact_id": payload["fact_id"],
                "group_key": group_key,
                "target_id": target_id,
                "field_key": key,
                "source_id": vehicle.source_id,
                "value": value,
                "value_token": spec_value_identity("KNOWN", value),
                "qualifiers": payload.get("qualifiers", {}),
                "observed_at": vehicle.approved_at,
            }
            candidates.append(candidate)
            groups.setdefault(group_key, []).append(candidate)

    # Compare against the ledger state too. A fact being revised under the
    # same fact_id replaces its old file, so its old version is deliberately
    # omitted from this comparison; every other stored fact participates.
    incoming_fact_ids = {item["fact_id"] for item in candidates}
    for fact in existing_facts:
        if fact.fact_id in incoming_fact_ids:
            continue
        definition = registry.fields.get(fact.field_key)
        if definition is None:
            continue
        group_key = spec_conflict_key(
            definition, trim_id=fact.trim_id, field_key=fact.field_key,
            qualifiers=fact.qualifiers, start=fact.start)
        groups.setdefault(group_key, []).append({
            "command": None,
            "fact_id": fact.fact_id,
            "group_key": group_key,
            "target_id": fact.trim_id,
            "field_key": fact.field_key,
            "source_id": f"existing:{fact.fact_id}",
            "value": fact.value,
            "value_token": spec_value_identity(fact.value_state, fact.value),
            "qualifiers": dict(fact.qualifiers),
            "observed_at": fact.start,
        })

    conflicting = {
        key for key, items in groups.items()
        if any(item["command"] is not None for item in items)
        and len({item["value_token"] for item in items}) > 1
    }
    conflicts: list[dict] = []
    for key in sorted(conflicting, key=repr):
        all_items = groups[key]
        incoming = [item for item in all_items if item["command"] is not None]
        first = incoming[0]
        conflicts.append({
            "source_id": ",".join(sorted({item["source_id"] for item in incoming})),
            "trim_id": first["target_id"],
            "conflicts": [{
                "field_key": first["field_key"],
                "observed_at": first["observed_at"],
                "qualifiers": first["qualifiers"],
                "reason": "ECO records disagree for the same trim/spec/date/context",
                "values": [
                    {"source_id": item["source_id"], "value": item["value"]}
                    for item in all_items
                ],
            }],
        })
    stats["spec_conflicts"] = len(conflicts)
    commands = [item["command"] for item in candidates
                if item["group_key"] not in conflicting]
    return commands, stats, conflicts


def compile_price_commands(
    outcomes: Iterable[RowOutcome],
    vehicles: dict[str, NormalizedVehicle],
    price_ledger: PriceLedger,
    *,
    pilot_model_ids: frozenset[str] = frozenset(),
) -> tuple[list[dict], dict[str, int], list[dict]]:
    """Compile resolved ECO rows' filed prices into APPEND_PRICE commands.

    Recorded as ECO_STICKER_PRICE, never LIST_PRICE: an ECO record is a
    homologation filing, not a price list, and PriceLedger.current_list_price()
    only ever resolves the LIST_PRICE stream, so nothing written here can
    surface as the price a reader is shown.

    ``pilot_model_ids`` (ComparableCohort.pilot_model_ids) is excluded
    outright, not merely deprioritised: a pilot model's current market price
    is promoted from its manufacturer's own listing (load_oem_sources()),
    never from an ECO filing alone -- homologation proves a configuration
    exists, not that it is what the showroom sells today. Checked against
    the row's own model_id rather than a catalogue lookup on the resolved
    trim_id, so a trim this same run is about to create is excluded exactly
    as reliably as one that already exists.

    Two ECO records disagreeing on one trim's price for one date mean the
    trim identity is too coarse to price, not that one of them is wrong --
    the fix is a finer trim, never a guess at which figure is real. Both are
    withheld and reported. This has to be decided here, before any command
    reaches the writer: _append_price's own same-day-different-amount path
    (_replace_same_day_price) exists for a deliberate correction -- someone
    re-saving a price they got wrong -- and would retract the first of two
    disagreeing ECO records the moment the second one applied, which is
    exactly the silent picking this preflight exists to prevent. The
    existing ledger participates in the same comparison, so a workbook that
    disagrees with what is already published is caught the same way a
    workbook that disagrees with itself is.
    """
    groups: dict[tuple[str, str], list[dict]] = {}
    stats = {
        "price_rows_missing_observed_at": 0,
        "price_pilot_model_skipped": 0,
        "price_equal_duplicates_collapsed": 0,
        "price_unchanged": 0,
        "price_commands": 0,
        "price_conflicts": 0,
    }
    for outcome in outcomes:
        if outcome.status == EXCEPTION:
            continue
        vehicle = vehicles.get(outcome.row.source_id)
        if vehicle is None or not vehicle.price_thb or vehicle.price_thb <= 0:
            continue
        if outcome.row.model_id in pilot_model_ids:
            stats["price_pilot_model_skipped"] += 1
            continue
        if not vehicle.approved_at:
            stats["price_rows_missing_observed_at"] += 1
            continue
        target_id = outcome.trim_id or trim_identity(
            outcome.row.generation_id, None, outcome.row.trim_name, outcome.row.powertrain)
        groups.setdefault((target_id, vehicle.approved_at), []).append({
            "source_id": vehicle.source_id,
            "amount_thb": int(vehicle.price_thb),
            "source_ref": vehicle.source_url,
        })

    existing_by_key: dict[tuple[str, str], list] = {}
    for record in price_ledger.records:
        if record.retracted or record.price_type is not PriceType.ECO_STICKER_PRICE:
            continue
        start = record.effective_from or record.observed_at
        if start:
            existing_by_key.setdefault((record.trim_id, start), []).append(record)

    commands: list[dict] = []
    conflicts: list[dict] = []
    for key in sorted(groups):
        trim_id, observed_at = key
        incoming = groups[key]
        incoming_amounts = {row["amount_thb"] for row in incoming}
        existing = existing_by_key.get(key, [])
        existing_amounts = {record.amount_thb for record in existing}
        if len(incoming_amounts | existing_amounts) > 1:
            stats["price_conflicts"] += 1
            conflicts.append({
                "source_id": ",".join(sorted(row["source_id"] for row in incoming)),
                "trim_id": trim_id,
                "conflicts": [{
                    "field_key": "price.eco_sticker_price",
                    "observed_at": observed_at,
                    "reason": "ECO records disagree on price for the same trim/date",
                    "values": [{"source_id": row["source_id"], "value": row["amount_thb"]}
                              for row in incoming] + [
                        {"source_id": f"existing:{record.source_ref}", "value": record.amount_thb}
                        for record in existing],
                }],
            })
            continue
        if existing_amounts:
            stats["price_unchanged"] += 1
            continue
        representative = sorted(incoming, key=lambda row: row["source_id"])[0]
        commands.append({
            "operation": "APPEND_PRICE",
            "canonical_id": trim_id,
            "payload": {
                "trim_id": trim_id,
                "amount_thb": representative["amount_thb"],
                "price_type": ECO_PRICE_TYPE,
                "observed_at": observed_at,
                "source": "ecosticker",
                "source_ref": representative["source_ref"],
                "notes": ("ราคาแนะนำที่ผู้ผลิตยื่นไว้กับ ECO Sticker ณ วันที่อนุมัติ "
                          "เก็บเป็นหลักฐานเท่านั้น ไม่ใช่ราคาขายปัจจุบัน"),
            },
        })
        stats["price_commands"] += 1
        stats["price_equal_duplicates_collapsed"] += max(0, len(incoming) - 1)
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
    price_ledger = PriceLedger.load(args.data_dir, year=args.year, catalog=catalog)
    # A pilot model's price is promoted from its own manufacturer listing,
    # never from an ECO filing -- see compile_price_commands. No cohort file
    # at all (a data dir with comparable specs not yet set up, e.g. a test
    # fixture) excludes nothing, the same as an empty pilot list would.
    try:
        pilot_model_ids = frozenset(ComparableCohort.load(args.data_dir, args.year).pilot_model_ids)
    except (OSError, ValueError):
        pilot_model_ids = frozenset()
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
    price_commands, price_stats, price_conflicts = compile_price_commands(
        outcomes, vehicles, price_ledger, pilot_model_ids=pilot_model_ids)
    # Every trim create/patch must precede every fact or price. A fact/price
    # for a newly created trim may therefore fall into a later batch and
    # still resolve.
    commands = trim_commands + spec_commands + price_commands

    exceptions = unplaced + [exception_record(o) for o in outcomes
                             if o.status == EXCEPTION] + [
        exception_record(o) for o in stranded]
    conflicts = [{"source_id": o.row.source_id, "trim_id": o.trim_id,
                  "conflicts": o.conflicts} for o in outcomes if o.conflicts]
    conflicts.extend(spec_conflicts)
    conflicts.extend(price_conflicts)

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
        "price_commands": len(price_commands),
        **price_stats,
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
        # Every reader the write touched, reloaded fresh off disk and
        # revalidated -- not inferred from individual command results. A
        # batch can each individually APPLY and still leave the tree
        # inconsistent for a reason none of them checks alone (a spec
        # conflict introduced across two different batches, say); this is
        # the one place that would be caught before the run reports success.
        after_catalog = Catalog.load(args.data_dir, args.year)
        catalog_problems = after_catalog.validate()
        after_specs = SpecLedger.load(
            args.data_dir, args.year, registry=registry, catalog=after_catalog)
        spec_problems = after_specs.validate()
        after_prices = PriceLedger.load(args.data_dir, year=args.year, catalog=after_catalog)
        price_problems = after_prices.validate()
        problems = catalog_problems + spec_problems + price_problems
        if problems:
            raise SystemExit("post-apply validation failed: " + "; ".join(problems[:20]))
        report["post_apply_catalog_problems"] = len(catalog_problems)
        report["post_apply_spec_problems"] = len(spec_problems)
        report["post_apply_price_problems"] = len(price_problems)
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
