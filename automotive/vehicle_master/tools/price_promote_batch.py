#!/usr/bin/env python3
"""Turn reviewed P5 candidates into a validated canonical market-file plan.

Dry-run is the default. ``--apply`` writes only ``vehreg/data/<year>/market``
files after the complete in-memory ledger validates. It never commits, pushes,
opens a PR, or publishes Supabase serving data; ``price_promotion_pr.py`` wraps
this command for the Git branch/PR step.

Required inputs:

* ``--candidate-state``: P5 CandidateBook JSON
* ``--reconcile``: P5 reconcile report from the same/latest run
* ``--fetch``: P4 fetch batch, used to retain the exact source document/claim
* ``--review``: HUMAN approval/rejection bundle; may also create reviewed
  campaign identities used by bound campaign/finance candidates
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vehreg.catalog import Catalog, DATA_DIR, DEFAULT_YEAR  # noqa: E402
from vehreg.price_promote import (  # noqa: E402
    PromotionAction,
    PromotionError,
    PromotionPlan,
    build_promotion_plan,
    disposition_map,
    load_promotion_bundle,
)
from vehreg.price_reconcile import (  # noqa: E402
    CandidateBook,
    ReconcileDisposition,
)
from vehreg.pricing import PriceLedger, PriceType  # noqa: E402
# Temporary shared writer primitive until price authoring is split out of
# product.py. Both manual maintenance and P6 must serialize through the same
# lock and use atomic temp-file replacement; having two independent filesystem
# writers was a correctness bug, not merely code style.
from vehreg.product import _write_json, _writer_lock  # noqa: E402


def _load(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PromotionError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise PromotionError(f"{path}: root must be an object")
    return payload


def _refuse_multiple_current_approvals(book: CandidateBook, decisions: dict) -> None:
    """One bot PR may select at most one current truth per canonical stream."""
    selected: dict[tuple, str] = {}
    for candidate_id, decision in decisions.items():
        if decision.action is not PromotionAction.APPROVE:
            continue
        candidate = book.candidates.get(candidate_id)
        if candidate is None or candidate.historical_only:
            continue
        key = (
            candidate.trim_id,
            candidate.price_type.value,
            candidate.campaign_id or "",
            candidate.option_id or "",
        )
        previous = selected.get(key)
        if previous is not None and previous != candidate_id:
            raise PromotionError(
                "multiple approved current candidates target the same canonical "
                f"stream: {previous} and {candidate_id}; choose one or rerun review"
            )
        selected[key] = candidate_id


def _aware_timestamp(raw: str, *, candidate_id: str, field: str) -> datetime:
    try:
        stamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError as exc:
        raise PromotionError(
            f"{candidate_id}: invalid {field} timestamp {raw!r}") from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise PromotionError(f"{candidate_id}: {field} must be offset-aware")
    return stamp


def _refuse_stale_replacements(*, data_dir: Path, year: int,
                               book: CandidateBook, reconcile: dict,
                               decisions: dict) -> None:
    """Fail if approval/P5 state is stale against current canonical truth.

    The shared writer lock prevents changes while P6 is running, but it cannot
    make an old P5 decision or an old HUMAN approval fresh again. A review must
    be made after the candidate was observed, and a confirmed replacement must
    be reviewed after confirmation. Immediately before write, its expected
    prior amount must also remain canonical current truth on the confirmation
    date. Any mismatch means rerun P5/review rather than silently overriding a
    newer canonical price.
    """
    dispositions = disposition_map(reconcile)
    catalog = Catalog.load(data_dir, year)
    ledger = PriceLedger.load(data_dir, year=year, catalog=catalog)

    for candidate_id, decision in decisions.items():
        if decision.action is not PromotionAction.APPROVE:
            continue
        candidate = book.candidates.get(candidate_id)
        if candidate is None:
            continue

        first_seen = _aware_timestamp(
            candidate.first_seen_at, candidate_id=candidate_id, field="first_seen_at")
        reviewed_at = _aware_timestamp(
            decision.reviewed_at, candidate_id=candidate_id, field="reviewed_at")
        if reviewed_at < first_seen:
            raise PromotionError(
                f"{candidate_id}: HUMAN approval predates candidate first_seen_at; "
                "review the current candidate again")

        if candidate.price_type in {PriceType.CAMPAIGN_PRICE, PriceType.FINANCE_PRICE}:
            if not candidate.campaign_id or not candidate.option_id:
                raise PromotionError(
                    f"{candidate_id}: {candidate.price_type.value} promotion requires "
                    "canonical campaign_id + option_id; rerun binding/P5")

        if dispositions.get(candidate_id) is not ReconcileDisposition.CONFIRMED_REPLACEMENT:
            continue
        if not candidate.confirmed_at or candidate.replaces_amount_thb is None:
            raise PromotionError(
                f"{candidate_id}: confirmed replacement lacks confirmation/prior amount")

        confirmed_at = _aware_timestamp(
            candidate.confirmed_at, candidate_id=candidate_id, field="confirmed_at")
        if reviewed_at < confirmed_at:
            raise PromotionError(
                f"{candidate_id}: HUMAN approval predates 24h confirmation; "
                "review the confirmed replacement again")

        current = ledger.current_price_for_scope(
            candidate.trim_id,
            candidate.price_type,
            as_of=confirmed_at.date(),
            campaign_id=candidate.campaign_id,
            option_id=candidate.option_id,
        )
        if current is None or current.amount_thb != candidate.replaces_amount_thb:
            actual = "none" if current is None else f"{current.amount_thb:,}"
            raise PromotionError(
                f"{candidate_id}: canonical stream changed since P5; expected current "
                f"{candidate.replaces_amount_thb:,} THB at confirmation but found "
                f"{actual}; rerun P5 before promotion")

        # Even a same-amount row with a later start means the canonical stream
        # was revised during this observation cycle. Candidate v1 does not retain
        # a full prior-row fingerprint yet, so fail conservatively.
        current_start = current.effective_from or current.observed_at
        if current_start and current_start > first_seen.date().isoformat():
            raise PromotionError(
                f"{candidate_id}: canonical stream was revised after candidate "
                "first_seen_at even though the amount matches; rerun P5")


def _refuse_unbound_evidence(*, book: CandidateBook, fetch: dict,
                             decisions: dict) -> None:
    """Bind every approved candidate to the exact latest P4 claim/document.

    Matching only ``source_id + target_id`` is insufficient provenance: the same
    URL can change between P5 and promotion. Candidate claim_ids are durable P5
    evidence. The latest supporting claim must be present in this P4 batch, must
    belong to the fetched immutable document, and must agree on amount/type and
    exact canonical MarketTrim. Otherwise P6 refuses to write a misleading SHA.
    """
    rows = fetch.get("results")
    if not isinstance(rows, list):
        raise PromotionError("fetch batch must contain results array")

    support: dict[tuple[str, str, str], tuple[dict, str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        source_id = str(row.get("source_id") or "").strip()
        target_id = str(row.get("target_id") or "").strip()
        document = row.get("document") or {}
        if not isinstance(document, dict):
            continue
        document_id = str(document.get("document_id") or "").strip()
        claims = row.get("claims") or []
        if not isinstance(claims, list):
            raise PromotionError(
                f"{source_id}/{target_id}: fetch claims must be an array")
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            claim_id = str(claim.get("claim_id") or "").strip()
            if not claim_id:
                continue
            key = (source_id, target_id, claim_id)
            item = (claim, document_id)
            previous = support.get(key)
            if previous is not None and previous != item:
                raise PromotionError(
                    f"{source_id}/{target_id}: claim {claim_id} appears with "
                    "multiple evidence documents")
            support[key] = item

    for candidate_id, decision in decisions.items():
        if decision.action is not PromotionAction.APPROVE:
            continue
        candidate = book.candidates.get(candidate_id)
        if candidate is None:
            continue
        if not candidate.claim_ids:
            raise PromotionError(
                f"{candidate_id}: candidate has no supporting claim_ids")
        claim_id = candidate.claim_ids[-1]
        item = support.get((candidate.source_id, candidate.target_id, claim_id))
        if item is None:
            raise PromotionError(
                f"{candidate_id}: latest supporting claim {claim_id} is absent from "
                "the supplied P4 fetch batch; rerun fetch/P5/review")
        claim, document_id = item
        if str(claim.get("document_id") or "") != document_id:
            raise PromotionError(
                f"{candidate_id}: supporting claim/document SHA mismatch")
        try:
            amount = int(claim.get("amount_thb"))
        except (TypeError, ValueError) as exc:
            raise PromotionError(
                f"{candidate_id}: supporting claim has invalid amount_thb") from exc
        if amount != candidate.amount_thb or str(claim.get("price_type") or "") != candidate.price_type.value:
            raise PromotionError(
                f"{candidate_id}: supporting claim amount/type does not match candidate")
        match = claim.get("match")
        if not isinstance(match, dict) or match.get("state") != "EXACT" or \
                match.get("trim_id") != candidate.trim_id:
            raise PromotionError(
                f"{candidate_id}: supporting claim lacks the same P4 EXACT MarketTrim match")


def _apply_with_rollback(plan: PromotionPlan) -> None:
    """Atomically replace each touched file; caller holds the writer lock.

    The plan has already been fully validated while the same common lock was
    held. We snapshot every touched file and perform each replacement through
    product._write_json (temp file + fsync + os.replace). Ordinary exceptions
    restore the complete pre-apply set.
    """
    before: dict[Path, bytes | None] = {
        planned.path: (planned.path.read_bytes() if planned.path.exists() else None)
        for planned in plan.files
    }
    try:
        for planned in plan.files:
            _write_json(planned.path, planned.payload)
    except Exception:
        for path, payload in before.items():
            if payload is None:
                path.unlink(missing_ok=True)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        raise


def _build(*, data_dir: Path, year: int, book: CandidateBook,
           reconcile: dict, fetch: dict, decisions: dict,
           campaigns: tuple[dict, ...]) -> PromotionPlan:
    return build_promotion_plan(
        data_dir=data_dir,
        year=year,
        candidate_book=book,
        reconcile_report=reconcile,
        fetch_batch=fetch,
        decisions=decisions,
        create_campaigns=campaigns,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--candidate-state", type=Path, required=True)
    parser.add_argument("--reconcile", type=Path, required=True)
    parser.add_argument("--fetch", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR)
    parser.add_argument("--manifest-out", type=Path, default=None)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    book = CandidateBook.from_payload(_load(args.candidate_state))
    reconcile = _load(args.reconcile)
    fetch = _load(args.fetch)
    decisions, campaigns = load_promotion_bundle(args.review)
    _refuse_multiple_current_approvals(book, decisions)
    _refuse_unbound_evidence(book=book, fetch=fetch, decisions=decisions)

    if args.apply:
        # The common writer lock covers stale-P5 check -> canonical read -> plan
        # -> validation -> apply, so no writer can invalidate the decision after
        # the final freshness check and before bytes land.
        with _writer_lock(args.data_dir, args.year):
            _refuse_stale_replacements(
                data_dir=args.data_dir,
                year=args.year,
                book=book,
                reconcile=reconcile,
                decisions=decisions,
            )
            plan = _build(
                data_dir=args.data_dir,
                year=args.year,
                book=book,
                reconcile=reconcile,
                fetch=fetch,
                decisions=decisions,
                campaigns=campaigns,
            )
            _apply_with_rollback(plan)
    else:
        # Dry-run also reports stale input when possible. It is not serialized
        # against a writer, so --apply repeats this check under the lock.
        _refuse_stale_replacements(
            data_dir=args.data_dir,
            year=args.year,
            book=book,
            reconcile=reconcile,
            decisions=decisions,
        )
        plan = _build(
            data_dir=args.data_dir,
            year=args.year,
            book=book,
            reconcile=reconcile,
            fetch=fetch,
            decisions=decisions,
            campaigns=campaigns,
        )

    manifest = plan.manifest(args.data_dir)
    manifest["applied"] = bool(args.apply)
    if args.manifest_out:
        args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
        args.manifest_out.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
