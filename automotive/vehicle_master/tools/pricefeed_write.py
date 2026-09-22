"""Write the prices the resolver accepted into the canonical ledger.

    python -m tools.pricefeed_write vehreg/data/2026/market/pricefeed/batch-XXXX.json

``vehreg market price-run`` reads a harvest batch and decides what is
canonical, but it is evidence only: it has never been able to write, and
the production workflow calling it with ``--write`` has been failing on
every tick. This is the writer that command was pretending to be.

The path is the same one a Save in the admin takes -- canonical input
batch -> CanonicalWritePipeline -> PriceLedger -> release -- so an
automatic price and a typed one land in one ledger with one history.
Nothing here decides whether a price *should* change: ``pricefeed.run``
decided that, and ``pricefeed_writer`` decides precedence by rule.
Whatever neither could settle becomes a durable exception, not a queue
somebody has to keep clear before other prices can publish.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vehreg import pricefeed
from vehreg.catalog import DATA_DIR, DEFAULT_YEAR, Catalog
from vehreg.input_pipeline import CanonicalInputPipeline
from vehreg.pricefeed_writer import (
    EXCEPTION, HeldPrice, WRITTEN, batch_from_outcomes, exception_rows,
    plan_offers, summarize,
)
from vehreg.pricing import PriceLedger, PriceType, PricingError

SOURCE_KIND = "PRICE"


def _scopes(offers: list[dict]) -> list[tuple[str, str, str, str]]:
    seen: list[tuple[str, str, str, str]] = []
    for offer in offers:
        campaign = (offer.get("campaign_hint") or "").strip()
        option = (offer.get("option_hint") or "").strip() or ("default" if campaign else "")
        key = (str(offer.get("trim_id") or ""), str(offer.get("price_type") or ""),
               campaign, option)
        if key[0] and key[1] and key not in seen:
            seen.append(key)
    return seen


def held_prices(ledger: PriceLedger, offers: list[dict], *, as_of: date
                ) -> tuple[list[HeldPrice], dict[tuple, str]]:
    """What the ledger currently serves for every scope these offers touch.

    Resolved rows, not the whole history: the question the feed is asking
    is "what is being served", and it has to be asked the same way the
    correction path will ask it. A scope the ledger cannot resolve at all
    is reported rather than written over.
    """
    held: list[HeldPrice] = []
    unresolvable: dict[tuple, str] = {}
    for trim_id, price_type, campaign_id, option_id in _scopes(offers):
        try:
            parsed = PriceType.parse(price_type)
        except (PricingError, ValueError) as exc:
            unresolvable[(trim_id, price_type, campaign_id, option_id)] = str(exc)
            continue
        try:
            row = ledger.current_price_for_scope(
                trim_id, parsed, as_of=as_of,
                campaign_id=campaign_id or None, option_id=option_id or None)
        except PricingError as exc:
            unresolvable[(trim_id, price_type, campaign_id, option_id)] = str(exc)
            continue
        if row is None:
            continue
        held.append(HeldPrice(
            trim_id=row.trim_id, price_type=row.price_type.value,
            amount_thb=row.amount_thb, observed_at=row.observed_at,
            effective_from=row.effective_from,
            source=row.source, reviewed_by=row.reviewed_by,
            campaign_id=row.campaign_id, option_id=row.option_id))
    return held, unresolvable


def _split_unresolvable(offers: list[dict], unresolvable: dict[tuple, str]):
    """Keep an offer away from a scope the ledger cannot currently resolve."""
    writable: list[dict] = []
    blocked: list[dict] = []
    for offer in offers:
        campaign = (offer.get("campaign_hint") or "").strip()
        option = (offer.get("option_hint") or "").strip() or ("default" if campaign else "")
        key = (str(offer.get("trim_id") or ""), str(offer.get("price_type") or ""),
               campaign, option)
        if key in unresolvable:
            blocked.append({**offer, "reasons": [unresolvable[key]]})
        else:
            writable.append(offer)
    return writable, blocked


def _store_exceptions(rows: list[dict], *, data_dir: Path, year: int,
                      batch_ref: str) -> dict:
    """Durable on disk always; in the owner's exception list when we can.

    The file is committed with the run, so nothing is lost even where the
    database is not reachable. ``import_run_exceptions`` is what
    /admin/exceptions reads, so that is where the owner meets it.
    """
    folder = pricefeed.feed_dir(data_dir, year) / "exceptions"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{batch_ref}.json"
    target.write_text(json.dumps({
        "batch_ref": batch_ref,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "exceptions": rows,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    stored = {"file": str(target), "count": len(rows), "database": "skipped"}
    if rows and os.environ.get("SUPABASE_URL"):
        stored["database"] = _post_exceptions(rows, batch_ref=batch_ref)
    return stored


def _post_exceptions(rows: list[dict], *, batch_ref: str) -> str:
    from tools.import_worker import _rest

    run = _rest("POST", "import_runs", {
        "storage_path": f"pricefeed/{batch_ref}",
        "original_name": f"{batch_ref}.json",
        "source_kind": SOURCE_KIND,
        "status": "COMPLETED",
        "actor": "price-feed",
        "exceptions": len(rows),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }, prefer="return=representation")
    run_id = (run or [{}])[0].get("id")
    if not run_id:
        raise RuntimeError("import_runs insert returned no id")
    for start in range(0, len(rows), 500):
        _rest("POST", "import_run_exceptions", [{
            "run_id": run_id,
            "source_kind": SOURCE_KIND,
            "kind": str(item.get("kind") or "PRICE_IDENTITY"),
            "reason": str(item.get("reason") or "")[:2000],
            "source_identity": item.get("source_identity") or {},
            "status": "OPEN",
        } for item in rows[start:start + 500]], prefer="return=minimal")
    return run_id


def run(path: Path, *, data_dir: Path, year: int,
        observed_at: str, apply: bool) -> dict:
    """The normal, automated production path: evidence in, canonical OR
    exception out, deterministically -- never a human decision file.

    A decision entry with origin HUMAN and action "publish" is what
    ``pricefeed.run`` uses to promote a single-source ("provisional")
    price to canonical; the production workflow used to pass one in
    (``--decisions review/decisions.json``), which meant a person's
    earlier call on an unrelated claim could silently promote a
    provisional price the very next time this ran, with no review
    happening in that run at all. There is never a decisions argument
    here, by construction, so that path cannot be reopened by a future
    caller passing one back in. Manual review of a batch is still
    possible -- ``vehreg market price-run --decisions`` -- but that
    command is evidence-only and was never wired to a writer.
    """
    documents, claims = pricefeed.load_batch(path)
    catalog = Catalog.load(data_dir, year)
    ledger = PriceLedger.load(data_dir, year=year, catalog=catalog)
    result = pricefeed.run(documents, claims,
                           pricefeed.load_sources(data_dir, year),
                           catalog, campaigns=ledger.campaigns,
                           decisions={}, ledger=ledger)

    as_of = date.fromisoformat(observed_at)
    held, unresolvable = held_prices(ledger, result.offers, as_of=as_of)
    writable, blocked = _split_unresolvable(result.offers, unresolvable)
    outcomes = plan_offers(writable, held, observed_at=observed_at)
    batch = batch_from_outcomes(outcomes, year=year, submitted_at=f"{observed_at}T00:00:00+00:00")

    exceptions = exception_rows(outcomes, [*result.review, *blocked])
    batch_ref = batch["batch_id"] if batch else f"pricefeed-{observed_at}-none"
    stored = _store_exceptions(exceptions, data_dir=data_dir, year=year,
                               batch_ref=batch_ref)

    summary = {
        **result.summary(),
        "observed_at": observed_at,
        "planned": summarize(outcomes),
        "batch_id": batch["batch_id"] if batch else None,
        "applied": False,
        "exceptions_stored": stored,
    }
    if batch and apply:
        applied = CanonicalInputPipeline(data_dir).apply(batch)
        summary["applied"] = True
        summary["idempotent_replay"] = applied.idempotent_replay
        summary["changed_files"] = list(applied.changed_files)
        after = PriceLedger.load(data_dir, year=year, catalog=Catalog.load(data_dir, year))
        summary["now_serving"] = _serving(after, outcomes, as_of=as_of)
    elif batch:
        summary["commands"] = batch["commands"]
    return summary


def _serving(ledger: PriceLedger, outcomes, *, as_of: date) -> list[dict]:
    """Read the written prices back out of the ledger the site reads.

    A write that the resolver does not return afterwards is not a price
    change, however cleanly the command applied.
    """
    rows: list[dict] = []
    for outcome in outcomes:
        if outcome.status != WRITTEN or not outcome.command:
            continue
        payload = outcome.command["payload"]
        record = ledger.current_price_for_scope(
            payload["trim_id"], PriceType.parse(payload["price_type"]), as_of=as_of,
            campaign_id=payload.get("campaign_id"), option_id=payload.get("option_id"))
        rows.append({
            "trim_id": payload["trim_id"],
            "price_type": payload["price_type"],
            "expected_thb": payload["amount_thb"],
            "serving_thb": record.amount_thb if record else None,
        })
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="a harvest batch produced by pricefeed_harvest")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR)
    parser.add_argument("--observed-at", default=date.today().isoformat())
    parser.add_argument("--plan-only", action="store_true",
                        help="decide and record exceptions without writing prices")
    args = parser.parse_args(argv)

    summary = run(args.path, data_dir=args.data_dir, year=args.year,
                  observed_at=args.observed_at, apply=not args.plan_only)
    print(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False))
    mismatched = [row for row in summary.get("now_serving", [])
                  if row["serving_thb"] != row["expected_thb"]]
    if mismatched:
        print(json.dumps({"error": "written prices are not being served",
                          "rows": mismatched}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
