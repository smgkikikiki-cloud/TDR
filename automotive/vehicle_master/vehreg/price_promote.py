"""P6 reviewed promotion from P5 staging into canonical PriceLedger files.

This is the *automated price-bot* write boundary.  P5 decides whether an
observation is safe/new, historical, pending, or a confirmed replacement.  P6
requires an explicit HUMAN approval before any promotable candidate can change
canonical market files.  It never guesses a campaign binding and never promotes
PENDING/REVERTED/REVIEW candidates.

The canonical price history rule is append + supersede, not destructive rewrite:

* a new price is appended as its own JSON file;
* a confirmed replacement closes the exact prior stream by adding
  ``effective_to`` to that prior row, then appends the new row;
* LIST/CAMPAIGN/FINANCE/ESTIMATED streams never close one another;
* campaign/finance supersession is scoped by campaign_id + option_id;
* if the source did not state an effective date, confirmed replacement becomes
  effective on the confirmation date.  ``observed_at`` still records when the
  system first saw it, so no unknown effective date is invented.

Campaign identities can be created in the same reviewed bundle.  Existing
campaigns are never silently rewritten by the price bot.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from enum import Enum
import hashlib
import json
from pathlib import Path
from typing import Iterable, Optional

from .catalog import Catalog, DATA_DIR, DEFAULT_YEAR
from .price_reconcile import (
    CandidateBook,
    CandidateState,
    PriceCandidate,
    ReconcileDisposition,
)
from .pricing import (
    Campaign,
    PriceLedger,
    PriceRecord,
    PriceType,
    PricingError,
    campaign_dir,
    price_dir,
)


PROMOTION_SCHEMA_VERSION = 1
PROMOTABLE_DISPOSITIONS = frozenset({
    ReconcileDisposition.SAFE_CANDIDATE,
    ReconcileDisposition.CONFIRMED_REPLACEMENT,
    ReconcileDisposition.HISTORICAL_ONLY,
})


class PromotionError(ValueError):
    pass


class PromotionAction(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    candidate_id: str
    action: PromotionAction
    reviewer: str
    origin: str
    reviewed_at: str
    notes: str = ""

    @classmethod
    def from_dict(cls, raw: dict) -> "PromotionDecision":
        if not isinstance(raw, dict):
            raise PromotionError("promotion decision must be an object")
        allowed = {"candidate_id", "action", "reviewer", "origin", "reviewed_at", "notes"}
        unknown = set(raw) - allowed
        if unknown:
            raise PromotionError(f"unknown promotion decision fields: {sorted(unknown)}")
        try:
            action = PromotionAction(str(raw.get("action") or "").strip().upper())
        except ValueError as exc:
            raise PromotionError(f"invalid promotion action {raw.get('action')!r}") from exc
        decision = cls(
            candidate_id=str(raw.get("candidate_id") or "").strip(),
            action=action,
            reviewer=str(raw.get("reviewer") or "").strip(),
            origin=str(raw.get("origin") or "").strip().upper(),
            reviewed_at=str(raw.get("reviewed_at") or "").strip(),
            notes=str(raw.get("notes") or "").strip(),
        )
        decision.validate()
        return decision

    def validate(self) -> None:
        problems: list[str] = []
        if not self.candidate_id:
            problems.append("candidate_id is required")
        if not self.reviewer:
            problems.append("reviewer is required")
        # P6 intentionally starts human-gated.  SYSTEM_EVIDENCE may eventually
        # earn a safe auto-promotion class, but it must not arrive accidentally.
        if self.origin != "HUMAN":
            problems.append("P6 promotion decisions must have origin HUMAN")
        if _timestamp(self.reviewed_at) is None:
            problems.append("reviewed_at must be an offset-aware ISO timestamp")
        if problems:
            raise PromotionError("; ".join(problems))


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    source_id: str
    target_id: str
    url: str


@dataclass(frozen=True, slots=True)
class PlannedFile:
    path: Path
    payload: dict
    kind: str

    def as_dict(self, data_dir: Path) -> dict:
        try:
            relative = self.path.relative_to(data_dir)
        except ValueError:
            relative = self.path
        return {"path": str(relative), "kind": self.kind}


@dataclass(frozen=True, slots=True)
class PromotionItem:
    candidate_id: str
    action: str
    disposition: str
    trim_id: str
    amount_thb: int
    price_type: str
    previous_amount_thb: Optional[int]
    start_date: Optional[str]
    source_ref: str
    reviewer: str

    def as_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "action": self.action,
            "disposition": self.disposition,
            "trim_id": self.trim_id,
            "amount_thb": self.amount_thb,
            "price_type": self.price_type,
            "previous_amount_thb": self.previous_amount_thb,
            "start_date": self.start_date,
            "source_ref": self.source_ref,
            "reviewer": self.reviewer,
        }


@dataclass(frozen=True, slots=True)
class PromotionPlan:
    year: int
    files: tuple[PlannedFile, ...]
    items: tuple[PromotionItem, ...]
    rejected_candidate_ids: tuple[str, ...]
    affected_model_ids: tuple[str, ...]

    def manifest(self, data_dir: Path | str = DATA_DIR) -> dict:
        root = Path(data_dir)
        return {
            "schema_version": PROMOTION_SCHEMA_VERSION,
            "year": self.year,
            "items": [item.as_dict() for item in self.items],
            "rejected_candidate_ids": list(self.rejected_candidate_ids),
            "affected_model_ids": list(self.affected_model_ids),
            "files": [planned.as_dict(root) for planned in self.files],
        }

    def apply(self) -> None:
        """Write the already-validated plan.  No network/git operations here."""
        for planned in self.files:
            planned.path.parent.mkdir(parents=True, exist_ok=True)
            planned.path.write_text(
                json.dumps(planned.payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )


def _timestamp(raw: object) -> Optional[datetime]:
    if not raw:
        return None
    text = str(raw).strip().replace("Z", "+00:00")
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return None
    return value


def _date_of(raw: str) -> date:
    stamp = _timestamp(raw)
    if stamp is None:
        raise PromotionError(f"invalid candidate timestamp {raw!r}")
    return stamp.date()


def load_promotion_bundle(path: Path | str) -> tuple[dict[str, PromotionDecision], tuple[dict, ...]]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PromotionError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != PROMOTION_SCHEMA_VERSION:
        raise PromotionError(
            f"{path}: schema_version must be {PROMOTION_SCHEMA_VERSION}")
    rows = payload.get("decisions")
    if not isinstance(rows, list):
        raise PromotionError(f"{path}: decisions must be an array")
    decisions: dict[str, PromotionDecision] = {}
    for raw in rows:
        decision = PromotionDecision.from_dict(raw)
        if decision.candidate_id in decisions:
            raise PromotionError(f"{path}: duplicate decision for {decision.candidate_id}")
        decisions[decision.candidate_id] = decision
    campaigns = payload.get("create_campaigns") or []
    if not isinstance(campaigns, list):
        raise PromotionError(f"{path}: create_campaigns must be an array")
    for raw in campaigns:
        if not isinstance(raw, dict):
            raise PromotionError(f"{path}: campaign payload must be an object")
    return decisions, tuple(deepcopy(campaigns))


def disposition_map(reconcile_report: dict) -> dict[str, ReconcileDisposition]:
    rows = reconcile_report.get("decisions")
    if not isinstance(rows, list):
        raise PromotionError("reconcile report must contain decisions array")
    out: dict[str, ReconcileDisposition] = {}
    for row in rows:
        decision = row.get("decision") if isinstance(row, dict) else None
        if not isinstance(decision, dict):
            continue
        candidate_id = str(decision.get("candidate_id") or "").strip()
        if not candidate_id:
            continue
        try:
            disposition = ReconcileDisposition(str(decision.get("disposition") or ""))
        except ValueError as exc:
            raise PromotionError(
                f"candidate {candidate_id}: invalid P5 disposition") from exc
        previous = out.get(candidate_id)
        if previous is not None and previous is not disposition:
            # One candidate must not be simultaneously safe and conflicted.
            raise PromotionError(
                f"candidate {candidate_id}: reconcile report has multiple dispositions")
        out[candidate_id] = disposition
    return out


def evidence_map(fetch_batch: dict) -> dict[tuple[str, str], EvidenceRef]:
    rows = fetch_batch.get("results")
    if not isinstance(rows, list):
        raise PromotionError("fetch batch must contain results array")
    out: dict[tuple[str, str], EvidenceRef] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        target_id = str(row.get("target_id") or "").strip()
        source_id = str(row.get("source_id") or "").strip()
        document = row.get("document") or {}
        url = str(document.get("url") or "").strip() if isinstance(document, dict) else ""
        if target_id and source_id and url:
            out[(source_id, target_id)] = EvidenceRef(source_id, target_id, url)
    return out


def _candidate_start(candidate: PriceCandidate, disposition: ReconcileDisposition) -> date:
    if candidate.effective_from:
        try:
            return date.fromisoformat(candidate.effective_from)
        except ValueError as exc:
            raise PromotionError(
                f"{candidate.candidate_id}: effective_from is invalid") from exc
    if disposition is ReconcileDisposition.CONFIRMED_REPLACEMENT:
        if not candidate.confirmed_at:
            raise PromotionError(
                f"{candidate.candidate_id}: confirmed replacement lacks confirmed_at")
        return _date_of(candidate.confirmed_at)
    return _date_of(candidate.first_seen_at)


def _candidate_record(candidate: PriceCandidate, disposition: ReconcileDisposition,
                      evidence: EvidenceRef, decision: PromotionDecision) -> PriceRecord:
    start = _candidate_start(candidate, disposition)
    observed = _date_of(candidate.first_seen_at)
    # For a confirmed replacement without a literal source effective_from, use
    # the confirmation day as effective_from and preserve first-seen separately
    # in observed_at.  SAFE/HISTORICAL candidates need no invented effective
    # date; observed_at alone is their known anchor unless the source gave one.
    effective_from = candidate.effective_from
    if disposition is ReconcileDisposition.CONFIRMED_REPLACEMENT and not effective_from:
        effective_from = start.isoformat()
    notes = (
        f"P6 candidate {candidate.candidate_id}; first_seen_at={candidate.first_seen_at}; "
        f"last_seen_at={candidate.last_seen_at}; confirmed_at={candidate.confirmed_at or ''}; "
        f"approved_by={decision.reviewer}; reviewed_at={decision.reviewed_at}"
    )
    if decision.notes:
        notes += f"; review_notes={decision.notes}"
    return PriceRecord(
        trim_id=candidate.trim_id,
        amount_thb=candidate.amount_thb,
        price_type=candidate.price_type,
        effective_from=effective_from,
        effective_to=candidate.effective_to,
        observed_at=observed.isoformat(),
        source=candidate.source_id,
        source_ref=evidence.url,
        notes=notes,
        campaign_id=candidate.campaign_id,
        option_id=candidate.option_id,
        reference_price_thb=candidate.reference_price_thb,
        reviewed_by=decision.reviewer,
    )


def _record_dict(record: PriceRecord) -> dict:
    payload = {
        "trim_id": record.trim_id,
        "amount_thb": record.amount_thb,
        "price_type": record.price_type.value,
        "effective_from": record.effective_from,
        "effective_to": record.effective_to,
        "observed_at": record.observed_at,
        "source": record.source,
        "source_ref": record.source_ref,
        "notes": record.notes,
        "campaign_id": record.campaign_id,
        "option_id": record.option_id,
        "reference_price_thb": record.reference_price_thb,
        "retracted_at": record.retracted_at,
        "retraction_reason": record.retraction_reason,
        "reviewed_by": record.reviewed_by,
    }
    return {key: value for key, value in payload.items()
            if value not in (None, "")}


def _record_matches_raw(record: PriceRecord, raw: dict) -> bool:
    """Identity sufficient to find one canonical row without name matching."""
    return (
        str(raw.get("trim_id") or "") == record.trim_id
        and int(raw.get("amount_thb") or 0) == record.amount_thb
        and PriceType.parse(raw.get("price_type")) is record.price_type
        and (raw.get("effective_from") or None) == record.effective_from
        and (raw.get("observed_at") or None) == record.observed_at
        and (raw.get("campaign_id") or None) == record.campaign_id
        and (raw.get("option_id") or None) == record.option_id
        and (raw.get("retracted_at") or None) == record.retracted_at
    )


def _load_price_payloads(data_dir: Path, year: int) -> dict[Path, dict]:
    folder = price_dir(data_dir, year)
    out: dict[Path, dict] = {}
    if not folder.is_dir():
        return out
    for path in sorted(folder.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise PromotionError(f"{path}: invalid JSON: {exc}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("prices"), list):
            raise PromotionError(f"{path}: prices must be an array")
        out[path] = payload
    return out


def _find_prior_row(payloads: dict[Path, dict], record: PriceRecord) -> tuple[Path, int, dict]:
    found: list[tuple[Path, int, dict]] = []
    for path, payload in payloads.items():
        for index, raw in enumerate(payload.get("prices") or []):
            if isinstance(raw, dict) and _record_matches_raw(record, raw):
                found.append((path, index, raw))
    if len(found) != 1:
        raise PromotionError(
            f"prior canonical row for {record.trim_id} {record.price_type.value} "
            f"{record.amount_thb} matched {len(found)} files; refusing supersession")
    return found[0]


def _scope_rows(ledger: PriceLedger, candidate: PriceCandidate) -> list[PriceRecord]:
    rows = ledger.records_for(candidate.trim_id, price_type=candidate.price_type)
    if candidate.price_type in {PriceType.CAMPAIGN_PRICE, PriceType.FINANCE_PRICE}:
        rows = [row for row in rows
                if row.campaign_id == candidate.campaign_id
                and row.option_id == candidate.option_id]
    return rows


def _prior_for_replacement(ledger: PriceLedger, candidate: PriceCandidate,
                           new_start: date) -> PriceRecord:
    if candidate.replaces_amount_thb is None:
        raise PromotionError(
            f"{candidate.candidate_id}: confirmed replacement lacks replaces_amount_thb")
    candidates = [row for row in _scope_rows(ledger, candidate)
                  if row.amount_thb == candidate.replaces_amount_thb
                  and not row.retracted
                  and (row.effective_from or row.observed_at or "0001-01-01")
                      < new_start.isoformat()]
    if not candidates:
        raise PromotionError(
            f"{candidate.candidate_id}: prior canonical amount "
            f"{candidate.replaces_amount_thb} not found in exact stream")
    latest_start = max(row.effective_from or row.observed_at or "0001-01-01"
                       for row in candidates)
    winners = [row for row in candidates
               if (row.effective_from or row.observed_at or "0001-01-01") == latest_start]
    unique = {(row.amount_thb, row.source, row.source_ref, row.campaign_id, row.option_id)
              for row in winners}
    if len(winners) != 1 or len(unique) != 1:
        raise PromotionError(
            f"{candidate.candidate_id}: prior canonical stream is ambiguous at {latest_start}")
    return winners[0]


def _validate_candidate(candidate: PriceCandidate, disposition: ReconcileDisposition,
                        decision: PromotionDecision) -> None:
    if decision.action is PromotionAction.REJECT:
        return
    if disposition not in PROMOTABLE_DISPOSITIONS:
        raise PromotionError(
            f"{candidate.candidate_id}: {disposition.value} is not promotable")
    if disposition is ReconcileDisposition.CONFIRMED_REPLACEMENT:
        if candidate.state is not CandidateState.CONFIRMED or not candidate.confirmed_at:
            raise PromotionError(
                f"{candidate.candidate_id}: replacement must be CONFIRMED in P5")
    elif disposition is ReconcileDisposition.HISTORICAL_ONLY:
        if not candidate.historical_only or not candidate.effective_to:
            raise PromotionError(
                f"{candidate.candidate_id}: HISTORICAL_ONLY needs explicit closed window")
    elif candidate.state is not CandidateState.NEW:
        raise PromotionError(
            f"{candidate.candidate_id}: SAFE_CANDIDATE must still be NEW staging state")
    if candidate.state in {CandidateState.PENDING_24H, CandidateState.REVERTED, CandidateState.REVIEW}:
        raise PromotionError(
            f"{candidate.candidate_id}: state {candidate.state.value} cannot promote")


def _new_price_path(data_dir: Path, year: int, candidate_id: str) -> Path:
    token = hashlib.sha256(candidate_id.encode("utf-8")).hexdigest()[:20]
    return price_dir(data_dir, year) / f"promoted_{token}.json"


def _campaign_path(data_dir: Path, year: int, campaign: dict) -> Path:
    brand = str(campaign.get("brand_id") or "").strip()
    if not brand or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for char in brand.lower()):
        raise PromotionError("created campaign requires a safe brand_id")
    return campaign_dir(data_dir, year) / f"pricebot_{brand.lower()}.json"


def _merge_campaign_payload(existing: Optional[dict], incoming: Iterable[dict]) -> dict:
    rows = deepcopy((existing or {}).get("campaigns") or [])
    known = {str(row.get("id") or "") for row in rows if isinstance(row, dict)}
    for campaign in incoming:
        campaign_id = str(campaign.get("id") or "").strip()
        if not campaign_id:
            raise PromotionError("created campaign requires id")
        if campaign_id in known:
            raise PromotionError(
                f"campaign {campaign_id} already exists in pricebot file; bot will not rewrite it")
        rows.append(deepcopy(campaign))
        known.add(campaign_id)
    return {"campaigns": rows}


def build_promotion_plan(*, data_dir: Path | str = DATA_DIR, year: int = DEFAULT_YEAR,
                         candidate_book: CandidateBook,
                         reconcile_report: dict,
                         fetch_batch: dict,
                         decisions: dict[str, PromotionDecision],
                         create_campaigns: Iterable[dict] = ()) -> PromotionPlan:
    """Validate everything and return a market-file-only write plan."""
    root = Path(data_dir)
    catalog = Catalog.load(root, year)
    ledger = PriceLedger.load(root, year=year, catalog=catalog)
    dispositions = disposition_map(reconcile_report)
    evidence = evidence_map(fetch_batch)
    price_payloads = _load_price_payloads(root, year)
    staged_price_payloads = deepcopy(price_payloads)
    staged_ledger = deepcopy(ledger)
    planned_files: dict[Path, PlannedFile] = {}
    items: list[PromotionItem] = []
    rejected: list[str] = []
    affected_models: set[str] = set()

    # Campaign creation is reviewed input and is applied before price validation
    # so campaign-bound PriceRecords can validate in the same transaction.
    new_campaigns = tuple(deepcopy(list(create_campaigns)))
    if new_campaigns:
        grouped: dict[Path, list[dict]] = {}
        for campaign in new_campaigns:
            campaign_id = str(campaign.get("id") or "").strip()
            if campaign_id in staged_ledger.campaigns:
                raise PromotionError(
                    f"campaign {campaign_id} already exists; automated P6 only creates new identities")
            grouped.setdefault(_campaign_path(root, year, campaign), []).append(campaign)
        for path, rows in grouped.items():
            existing = None
            if path.exists():
                existing = json.loads(path.read_text(encoding="utf-8"))
            payload = _merge_campaign_payload(existing, rows)
            # Parse/validate with canonical classes before any file is touched.
            check = deepcopy(staged_ledger)
            check.add_campaign_payload({"campaigns": rows}, source="<P6 reviewed campaign>")
            staged_ledger = check
            planned_files[path] = PlannedFile(path, payload, "campaign_create")

    for candidate_id, decision in sorted(decisions.items()):
        candidate = candidate_book.candidates.get(candidate_id)
        if candidate is None:
            raise PromotionError(f"decision references unknown candidate {candidate_id}")
        disposition = dispositions.get(candidate_id)
        if disposition is None:
            raise PromotionError(
                f"{candidate_id}: candidate has no current P5 disposition in reconcile report")
        _validate_candidate(candidate, disposition, decision)
        if decision.action is PromotionAction.REJECT:
            rejected.append(candidate_id)
            continue
        evidence_ref = evidence.get((candidate.source_id, candidate.target_id))
        if evidence_ref is None:
            raise PromotionError(
                f"{candidate_id}: fetch batch has no source URL for "
                f"{candidate.source_id}/{candidate.target_id}")
        record = _candidate_record(candidate, disposition, evidence_ref, decision)
        problems = record.validate()
        if problems:
            raise PromotionError(f"{candidate_id}: " + "; ".join(problems))
        if record.campaign_id and record.campaign_id not in staged_ledger.campaigns:
            raise PromotionError(
                f"{candidate_id}: campaign {record.campaign_id} does not exist or was not created")
        if record.campaign_id and record.option_id:
            campaign = staged_ledger.campaigns[record.campaign_id]
            if campaign.option(record.option_id) is None:
                raise PromotionError(
                    f"{candidate_id}: campaign {record.campaign_id} has no option {record.option_id}")

        previous_amount = candidate.replaces_amount_thb
        start = _candidate_start(candidate, disposition)
        if disposition is ReconcileDisposition.CONFIRMED_REPLACEMENT:
            prior = _prior_for_replacement(staged_ledger, candidate, start)
            close_on = start - timedelta(days=1)
            if prior.effective_to:
                prior_end = date.fromisoformat(prior.effective_to)
                if prior_end < close_on:
                    raise PromotionError(
                        f"{candidate_id}: prior stream already closed before replacement start")
                if prior_end == close_on:
                    closed_prior = prior
                else:
                    closed_prior = replace(prior, effective_to=close_on.isoformat())
            else:
                closed_prior = replace(prior, effective_to=close_on.isoformat())
            if closed_prior is not prior:
                path, index, raw = _find_prior_row(staged_price_payloads, prior)
                payload = deepcopy(staged_price_payloads[path])
                updated_raw = deepcopy(raw)
                updated_raw["effective_to"] = close_on.isoformat()
                payload["prices"][index] = updated_raw
                staged_price_payloads[path] = payload
                planned_files[path] = PlannedFile(path, payload, "supersede_prior")
                staged_ledger.records.remove(prior)
                staged_ledger.records.append(closed_prior)

        new_path = _new_price_path(root, year, candidate_id)
        new_payload = {"prices": [_record_dict(record)]}
        if new_path.exists():
            existing = json.loads(new_path.read_text(encoding="utf-8"))
            if existing != new_payload:
                raise PromotionError(
                    f"{candidate_id}: promotion file already exists with different content")
        else:
            planned_files[new_path] = PlannedFile(new_path, new_payload, "append_price")
        staged_ledger.add_payload(new_payload, source=f"<P6 {candidate_id}>")
        affected_models.add(catalog.model_for_trim(candidate.trim_id).id)
        items.append(PromotionItem(
            candidate_id=candidate_id,
            action=decision.action.value,
            disposition=disposition.value,
            trim_id=candidate.trim_id,
            amount_thb=candidate.amount_thb,
            price_type=candidate.price_type.value,
            previous_amount_thb=previous_amount,
            start_date=start.isoformat(),
            source_ref=evidence_ref.url,
            reviewer=decision.reviewer,
        ))

    problems = staged_ledger.validate()
    if problems:
        raise PromotionError("promoted ledger validation failed: " + "; ".join(problems))

    # Prove every promoted LIST stream resolves to exactly the promoted amount
    # on/after its start.  Campaign/finance resolution is scoped in P5 and the
    # ledger validator checks campaign references.
    for item in items:
        if item.price_type != PriceType.LIST_PRICE.value or not item.start_date:
            continue
        resolved = staged_ledger.current_list_price(
            item.trim_id, as_of=date.fromisoformat(item.start_date))
        if resolved is None or resolved.amount_thb != item.amount_thb:
            raise PromotionError(
                f"{item.candidate_id}: promoted LIST_PRICE does not resolve on start date")

    return PromotionPlan(
        year=year,
        files=tuple(planned_files[path] for path in sorted(planned_files)),
        items=tuple(items),
        rejected_candidate_ids=tuple(sorted(rejected)),
        affected_model_ids=tuple(sorted(affected_models)),
    )
