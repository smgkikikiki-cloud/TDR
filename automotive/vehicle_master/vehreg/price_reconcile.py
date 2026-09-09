"""P5 price reconciliation and 24-hour replacement persistence.

This module sits after deterministic extraction and P4 canonical MarketTrim
matching.  It is deliberately pure with respect to canonical truth: it may
advance staging :class:`PriceCandidate` rows, but it never writes PriceLedger,
never edits campaign definitions, and never publishes serving prices.

The invariants come from ``docs/price-intelligence/P0_SEMANTICS.md``:

* absence and age are never expiry;
* explicit windows are literal;
* price types are independent timelines;
* campaign/finance replacement requires an explicit campaign + option scope;
* a replacement must be *observed again* at or after first_seen + 24h;
* clock passage alone can never confirm a candidate;
* transient/reverted candidates remain staging history only.

P5 consumes the P4 disposition.  It must never silently rematch a weaker raw
string and thereby undo a deliberate AMBIGUOUS/UNMAPPED result.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from enum import Enum
import hashlib
import json
from typing import Iterable, Optional

from .price_match import TrimMatchResult, TrimMatchState
from .price_sources import TargetRole
from .pricefeed import PriceClaim, SourceDocument
from .pricing import PriceLedger, PriceRecord, PriceType


CANDIDATE_SCHEMA_VERSION = 1
REPLACEMENT_TOLERANCE = timedelta(hours=24)


class ReconcileError(ValueError):
    pass


class CandidateState(str, Enum):
    """Staging state only; canonical PriceRecord derives its own state."""

    NEW = "NEW"
    PENDING_24H = "PENDING_24H"
    CONFIRMED = "CONFIRMED"
    REVERTED = "REVERTED"
    REVIEW = "REVIEW"


class ReconcileDisposition(str, Enum):
    """What P5 recommends doing with one observation."""

    NO_CHANGE = "NO_CHANGE"
    SAFE_CANDIDATE = "SAFE_CANDIDATE"
    PENDING_REPLACEMENT = "PENDING_REPLACEMENT"
    CONFIRMED_REPLACEMENT = "CONFIRMED_REPLACEMENT"
    HISTORICAL_ONLY = "HISTORICAL_ONLY"
    REVIEW = "REVIEW"
    CONFLICT = "CONFLICT"


class ReconcileReason(str, Enum):
    UNMAPPED_TRIM = "UNMAPPED_TRIM"
    AMBIGUOUS_TRIM = "AMBIGUOUS_TRIM"
    PRICE_TYPE_UNKNOWN = "PRICE_TYPE_UNKNOWN"
    OBSERVATION_TIME_MISSING = "OBSERVATION_TIME_MISSING"
    CAMPAIGN_SCOPE_REQUIRED = "CAMPAIGN_SCOPE_REQUIRED"
    SAME_CANONICAL_PRICE = "SAME_CANONICAL_PRICE"
    NEW_PRICE_STREAM = "NEW_PRICE_STREAM"
    TYPE_TRANSITION = "TYPE_TRANSITION"
    EXPLICIT_WINDOW_CLOSED = "EXPLICIT_WINDOW_CLOSED"
    FUTURE_SCHEDULED = "FUTURE_SCHEDULED"
    NON_CURRENT_ROLE_NEEDS_DATE = "NON_CURRENT_ROLE_NEEDS_DATE"
    PROMOTION_REFERENCE_ONLY = "PROMOTION_REFERENCE_ONLY"
    REPLACEMENT_FIRST_SEEN = "REPLACEMENT_FIRST_SEEN"
    REPLACEMENT_STILL_PENDING = "REPLACEMENT_STILL_PENDING"
    REPLACEMENT_PERSISTED_24H = "REPLACEMENT_PERSISTED_24H"
    REPLACEMENT_REVERTED = "REPLACEMENT_REVERTED"
    REPLACEMENT_CHANGED = "REPLACEMENT_CHANGED"
    DUPLICATE_OBSERVATION = "DUPLICATE_OBSERVATION"
    OUT_OF_ORDER_OBSERVATION = "OUT_OF_ORDER_OBSERVATION"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"
    CANONICAL_CONFLICT = "CANONICAL_CONFLICT"


@dataclass(frozen=True, slots=True)
class PriceScope:
    """The stream inside which one price may replace another."""

    trim_id: str
    price_type: PriceType
    campaign_id: Optional[str] = None
    option_id: Optional[str] = None

    def key(self) -> tuple[str, ...]:
        parts = [self.trim_id, self.price_type.value]
        if self.campaign_id is not None or self.option_id is not None:
            parts.extend([self.campaign_id or "", self.option_id or ""])
        return tuple(parts)

    def as_dict(self) -> dict:
        return {
            "trim_id": self.trim_id,
            "price_type": self.price_type.value,
            "campaign_id": self.campaign_id,
            "option_id": self.option_id,
        }


@dataclass(frozen=True, slots=True)
class ReconcileObservation:
    """One P3 claim plus the exact P4 decision and fetch context."""

    claim: PriceClaim
    match: TrimMatchResult
    target_id: str
    target_role: TargetRole
    document: SourceDocument
    #: Canonical IDs from an explicit review/binding step. Raw campaign_hint and
    #: option_hint are not accepted as replacement scope merely because strings
    #: happen to look plausible.
    campaign_id: Optional[str] = None
    option_id: Optional[str] = None

    def observed_at(self) -> Optional[datetime]:
        return _parse_timestamp(self.document.fetched_at or self.document.first_seen_at)


@dataclass(frozen=True, slots=True)
class PriceCandidate:
    """Durable staging history for one observed price cycle."""

    candidate_id: str
    state: CandidateState
    trim_id: str
    amount_thb: int
    price_type: PriceType
    source_id: str
    target_id: str
    target_role: TargetRole
    first_seen_at: str
    last_seen_at: str
    observation_count: int
    claim_ids: tuple[str, ...] = ()
    campaign_id: Optional[str] = None
    option_id: Optional[str] = None
    confirmed_at: Optional[str] = None
    reverted_at: Optional[str] = None
    replaces_amount_thb: Optional[int] = None
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None
    reference_price_thb: Optional[int] = None
    historical_only: bool = False

    def scope(self) -> PriceScope:
        return PriceScope(
            self.trim_id,
            self.price_type,
            self.campaign_id,
            self.option_id,
        )

    def stream_key(self) -> tuple:
        return (*self.scope().key(), self.source_id, self.target_id)

    def as_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "state": self.state.value,
            "trim_id": self.trim_id,
            "amount_thb": self.amount_thb,
            "price_type": self.price_type.value,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "target_role": self.target_role.value,
            "first_seen_at": self.first_seen_at,
            "last_seen_at": self.last_seen_at,
            "observation_count": self.observation_count,
            "claim_ids": list(self.claim_ids),
            "campaign_id": self.campaign_id,
            "option_id": self.option_id,
            "confirmed_at": self.confirmed_at,
            "reverted_at": self.reverted_at,
            "replaces_amount_thb": self.replaces_amount_thb,
            "effective_from": self.effective_from,
            "effective_to": self.effective_to,
            "reference_price_thb": self.reference_price_thb,
            "historical_only": self.historical_only,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "PriceCandidate":
        if not isinstance(raw, dict):
            raise ReconcileError("candidate must be an object")
        allowed = set(cls.__dataclass_fields__)
        unknown = set(raw) - allowed
        if unknown:
            raise ReconcileError(f"unknown candidate fields: {sorted(unknown)}")
        try:
            candidate = cls(
                candidate_id=str(raw.get("candidate_id") or ""),
                state=CandidateState(str(raw.get("state") or "")),
                trim_id=str(raw.get("trim_id") or ""),
                amount_thb=int(raw.get("amount_thb") or 0),
                price_type=PriceType.parse(raw.get("price_type")),
                source_id=str(raw.get("source_id") or ""),
                target_id=str(raw.get("target_id") or ""),
                target_role=TargetRole.parse(raw.get("target_role")),
                first_seen_at=str(raw.get("first_seen_at") or ""),
                last_seen_at=str(raw.get("last_seen_at") or ""),
                observation_count=int(raw.get("observation_count") or 0),
                claim_ids=tuple(str(value) for value in (raw.get("claim_ids") or ())),
                campaign_id=str(raw.get("campaign_id") or "").strip() or None,
                option_id=str(raw.get("option_id") or "").strip() or None,
                confirmed_at=str(raw.get("confirmed_at") or "").strip() or None,
                reverted_at=str(raw.get("reverted_at") or "").strip() or None,
                replaces_amount_thb=(int(raw["replaces_amount_thb"])
                                     if raw.get("replaces_amount_thb") is not None
                                     else None),
                effective_from=str(raw.get("effective_from") or "").strip() or None,
                effective_to=str(raw.get("effective_to") or "").strip() or None,
                reference_price_thb=(int(raw["reference_price_thb"])
                                     if raw.get("reference_price_thb") is not None
                                     else None),
                historical_only=bool(raw.get("historical_only", False)),
            )
        except (TypeError, ValueError) as exc:
            raise ReconcileError(f"invalid candidate: {exc}") from exc
        candidate.validate()
        return candidate

    def validate(self) -> None:
        problems: list[str] = []
        if not self.candidate_id:
            problems.append("candidate_id is required")
        if not self.trim_id:
            problems.append("trim_id is required")
        if self.amount_thb <= 0:
            problems.append("amount_thb must be positive")
        if not self.source_id or not self.target_id:
            problems.append("source_id and target_id are required")
        if self.observation_count <= 0:
            problems.append("observation_count must be positive")
        first = _parse_timestamp(self.first_seen_at)
        last = _parse_timestamp(self.last_seen_at)
        if first is None or last is None:
            problems.append("first_seen_at and last_seen_at are required timestamps")
        elif last < first:
            problems.append("last_seen_at is before first_seen_at")
        if self.confirmed_at and _parse_timestamp(self.confirmed_at) is None:
            problems.append("confirmed_at is not a timestamp")
        if self.reverted_at and _parse_timestamp(self.reverted_at) is None:
            problems.append("reverted_at is not a timestamp")
        if self.price_type in (PriceType.CAMPAIGN_PRICE, PriceType.FINANCE_PRICE) and not (
                self.campaign_id and self.option_id):
            problems.append("campaign/finance candidate requires campaign_id + option_id")
        if self.option_id and not self.campaign_id:
            problems.append("option_id without campaign_id")
        if self.historical_only and self.state is not CandidateState.NEW:
            problems.append("historical_only candidate must remain NEW staging evidence")
        if problems:
            raise ReconcileError("; ".join(problems))


class CandidateBook:
    """Mutable staging book; serializable, but never canonical truth."""

    def __init__(self, candidates: Iterable[PriceCandidate] = ()) -> None:
        self.candidates: dict[str, PriceCandidate] = {}
        for candidate in candidates:
            candidate.validate()
            if candidate.candidate_id in self.candidates:
                raise ReconcileError(f"duplicate candidate {candidate.candidate_id}")
            self.candidates[candidate.candidate_id] = candidate

    @classmethod
    def from_payload(cls, payload: Optional[dict]) -> "CandidateBook":
        if not payload:
            return cls()
        if payload.get("schema_version") != CANDIDATE_SCHEMA_VERSION:
            raise ReconcileError(
                f"candidate schema_version must be {CANDIDATE_SCHEMA_VERSION}")
        rows = payload.get("candidates")
        if not isinstance(rows, list):
            raise ReconcileError("candidate payload must contain candidates array")
        return cls(PriceCandidate.from_dict(row) for row in rows)

    def to_payload(self) -> dict:
        return {
            "schema_version": CANDIDATE_SCHEMA_VERSION,
            "candidates": [self.candidates[key].as_dict()
                           for key in sorted(self.candidates)],
        }

    def put(self, candidate: PriceCandidate) -> None:
        candidate.validate()
        self.candidates[candidate.candidate_id] = candidate

    def active_for_stream(self, scope: PriceScope, source_id: str,
                          target_id: str) -> list[PriceCandidate]:
        key = (*scope.key(), source_id, target_id)
        active = [candidate for candidate in self.candidates.values()
                  if not candidate.historical_only
                  and candidate.stream_key() == key
                  and candidate.state in {
                      CandidateState.NEW,
                      CandidateState.PENDING_24H,
                      CandidateState.CONFIRMED,
                  }]
        return sorted(active, key=lambda candidate: candidate.first_seen_at)

    def counts(self) -> dict[str, int]:
        return {
            state.value: sum(candidate.state is state
                             for candidate in self.candidates.values())
            for state in CandidateState
        }


@dataclass(frozen=True, slots=True)
class ReconcileDecision:
    disposition: ReconcileDisposition
    reasons: tuple[ReconcileReason, ...]
    claim_id: str
    trim_id: Optional[str] = None
    scope: Optional[PriceScope] = None
    canonical_amount_thb: Optional[int] = None
    candidate_id: Optional[str] = None
    reverted_candidate_ids: tuple[str, ...] = ()
    conflicting_amounts: tuple[int, ...] = ()

    def as_dict(self) -> dict:
        return {
            "disposition": self.disposition.value,
            "reasons": [reason.value for reason in self.reasons],
            "claim_id": self.claim_id,
            "trim_id": self.trim_id,
            "scope": self.scope.as_dict() if self.scope else None,
            "canonical_amount_thb": self.canonical_amount_thb,
            "candidate_id": self.candidate_id,
            "reverted_candidate_ids": list(self.reverted_candidate_ids),
            "conflicting_amounts": list(self.conflicting_amounts),
        }


@dataclass(frozen=True, slots=True)
class ReconcileBatchResult:
    decisions: tuple[ReconcileDecision, ...]
    candidate_book: CandidateBook

    def summary(self) -> dict:
        counts = {state.value: 0 for state in ReconcileDisposition}
        for decision in self.decisions:
            counts[decision.disposition.value] += 1
        return {
            "decisions": len(self.decisions),
            "dispositions": counts,
            "candidate_states": self.candidate_book.counts(),
        }


def _parse_timestamp(raw: object) -> Optional[datetime]:
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


def _iso_timestamp(value: datetime) -> str:
    return value.isoformat()


def _price_date(raw: Optional[str]) -> Optional[date]:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def replacement_scope(observation: ReconcileObservation) -> Optional[PriceScope]:
    """Return an automatic replacement scope, or None when P0 forbids one."""
    if observation.match.state is not TrimMatchState.EXACT or not observation.match.trim_id:
        return None
    claim = observation.claim
    if claim.price_type in (PriceType.CAMPAIGN_PRICE, PriceType.FINANCE_PRICE):
        if not observation.campaign_id or not observation.option_id:
            return None
        return PriceScope(
            observation.match.trim_id,
            claim.price_type,
            observation.campaign_id,
            observation.option_id,
        )
    return PriceScope(observation.match.trim_id, claim.price_type)


def _record_start(record: PriceRecord) -> str:
    return record.effective_from or record.observed_at or "0001-01-01"


def _campaign_row_open(ledger: PriceLedger, record: PriceRecord, when: date) -> bool:
    if not record.campaign_id:
        return True
    campaign = ledger.campaigns.get(record.campaign_id)
    if campaign is None:
        # A validated canonical ledger should not get here. Do not invent a
        # closure merely because a related staging object is unavailable.
        return True
    if not campaign.live_on(when):
        return False
    option = campaign.option(record.option_id or "")
    return option.open_on(when) if option is not None else True


def current_record_for_scope(ledger: PriceLedger, scope: PriceScope, *,
                             as_of: date) -> tuple[Optional[PriceRecord], tuple[int, ...]]:
    """Return current canonical row and any same-start amount conflict.

    Like ``current_list_price``, a newer ended row never resurrects an older
    open-ended row.  Campaign/finance rows are narrowed to their explicitly
    bound campaign + option scope before resolution.
    """
    rows = ledger.records_for(scope.trim_id, price_type=scope.price_type)
    if scope.campaign_id is not None or scope.option_id is not None:
        rows = [record for record in rows
                if record.campaign_id == scope.campaign_id
                and record.option_id == scope.option_id]
    started = [record for record in rows if _record_start(record) <= as_of.isoformat()]
    if not started:
        return None, ()
    latest_start = max(_record_start(record) for record in started)
    latest = [record for record in started if _record_start(record) == latest_start]
    active = [record for record in latest
              if record.active_on(as_of) and _campaign_row_open(ledger, record, as_of)]
    amounts = tuple(sorted({record.amount_thb for record in active}))
    if len(amounts) > 1:
        return None, amounts
    return (active[-1] if active else None), amounts


def _claim_live_on(claim: PriceClaim, when: date) -> bool:
    starts = _price_date(claim.effective_from)
    ends = _price_date(claim.effective_to)
    if starts and when < starts:
        return False
    if ends and when > ends:
        return False
    return True


def _explicitly_closed(claim: PriceClaim, when: date) -> bool:
    ends = _price_date(claim.effective_to)
    return bool(ends and when > ends)


def _future_start(claim: PriceClaim, when: date) -> bool:
    starts = _price_date(claim.effective_from)
    return bool(starts and starts > when)


def _role_can_drive_current(observation: ReconcileObservation) -> bool:
    """Whether this document role can automatically move this price stream."""
    role = observation.target_role
    price_type = observation.claim.price_type
    if role in {TargetRole.CURRENT_MODEL_PAGE, TargetRole.PRICE_LIST}:
        return True
    if role is TargetRole.PROMOTION:
        # A promotion's struck/reference MSRP is context, not a current MSRP
        # authority.  Promotion pages only drive explicitly scoped offers.
        return price_type in {PriceType.CAMPAIGN_PRICE, PriceType.FINANCE_PRICE}
    if role in {TargetRole.PRESS_RELEASE, TargetRole.LAUNCH_PAGE, TargetRole.BLOG}:
        # Publication/first-seen date is not an effective date. Announcement or
        # archive-like documents need a literal effective_from to replace a
        # current row automatically.
        return bool(observation.claim.effective_from)
    return False


def _role_review_reason(observation: ReconcileObservation) -> ReconcileReason:
    if observation.target_role is TargetRole.PROMOTION and observation.claim.price_type not in {
            PriceType.CAMPAIGN_PRICE, PriceType.FINANCE_PRICE}:
        return ReconcileReason.PROMOTION_REFERENCE_ONLY
    return ReconcileReason.NON_CURRENT_ROLE_NEEDS_DATE


def _has_type_transition(ledger: PriceLedger, scope: PriceScope, when: date) -> bool:
    if scope.price_type is not PriceType.LIST_PRICE:
        return False
    for record in ledger.records_for(scope.trim_id):
        if record.price_type not in {PriceType.ESTIMATED_PRICE, PriceType.INTRODUCTORY_PRICE}:
            continue
        if record.active_on(when):
            return True
    return False


def _candidate_id(scope: PriceScope, observation: ReconcileObservation,
                  first_seen: datetime) -> str:
    seed = json.dumps({
        "scope": scope.key(),
        "source_id": observation.claim.source_id,
        "target_id": observation.target_id,
        "amount_thb": observation.claim.amount_thb,
        "first_seen_at": _iso_timestamp(first_seen),
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "pcand:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def _new_candidate(scope: PriceScope, observation: ReconcileObservation,
                   observed_at: datetime, *, state: CandidateState,
                   replaces_amount_thb: Optional[int],
                   historical_only: bool = False) -> PriceCandidate:
    claim = observation.claim
    candidate = PriceCandidate(
        candidate_id=_candidate_id(scope, observation, observed_at),
        state=state,
        trim_id=scope.trim_id,
        amount_thb=claim.amount_thb,
        price_type=claim.price_type,
        source_id=claim.source_id,
        target_id=observation.target_id,
        target_role=observation.target_role,
        first_seen_at=_iso_timestamp(observed_at),
        last_seen_at=_iso_timestamp(observed_at),
        observation_count=1,
        claim_ids=(claim.claim_id,),
        campaign_id=scope.campaign_id,
        option_id=scope.option_id,
        replaces_amount_thb=replaces_amount_thb,
        effective_from=claim.effective_from,
        effective_to=claim.effective_to,
        reference_price_thb=claim.reference_price_thb,
        historical_only=historical_only,
    )
    candidate.validate()
    return candidate


def _append_claim_id(candidate: PriceCandidate, claim_id: str) -> tuple[str, ...]:
    return candidate.claim_ids if claim_id in candidate.claim_ids else (
        *candidate.claim_ids, claim_id)


def _revert(candidate: PriceCandidate, observed_at: datetime) -> PriceCandidate:
    return replace(
        candidate,
        state=CandidateState.REVERTED,
        reverted_at=_iso_timestamp(observed_at),
    )


def _latest_active(book: CandidateBook, scope: PriceScope,
                   observation: ReconcileObservation) -> Optional[PriceCandidate]:
    rows = book.active_for_stream(scope, observation.claim.source_id,
                                  observation.target_id)
    return rows[-1] if rows else None


def _observe_safe_candidate(book: CandidateBook, scope: PriceScope,
                            observation: ReconcileObservation,
                            observed_at: datetime, *, historical_only: bool = False,
                            replaces_amount_thb: Optional[int] = None) -> tuple[PriceCandidate, tuple[str, ...]]:
    active = _latest_active(book, scope, observation)
    reverted: list[str] = []
    if historical_only:
        candidate = _new_candidate(
            scope, observation, observed_at,
            state=CandidateState.NEW,
            replaces_amount_thb=replaces_amount_thb,
            historical_only=True,
        )
        book.put(candidate)
        return candidate, ()
    if active is not None:
        last = _parse_timestamp(active.last_seen_at)
        assert last is not None
        if observed_at < last:
            return active, ()
        if active.amount_thb == observation.claim.amount_thb:
            if observed_at == last:
                return active, ()
            updated = replace(
                active,
                last_seen_at=_iso_timestamp(observed_at),
                observation_count=active.observation_count + 1,
                claim_ids=_append_claim_id(active, observation.claim.claim_id),
            )
            book.put(updated)
            return updated, ()
        if observed_at > last:
            old = _revert(active, observed_at)
            book.put(old)
            reverted.append(old.candidate_id)
    candidate = _new_candidate(
        scope, observation, observed_at,
        state=CandidateState.NEW,
        replaces_amount_thb=replaces_amount_thb,
    )
    book.put(candidate)
    return candidate, tuple(reverted)


def _observe_replacement(book: CandidateBook, scope: PriceScope,
                         observation: ReconcileObservation,
                         observed_at: datetime,
                         canonical_amount: int) -> tuple[PriceCandidate, tuple[str, ...], ReconcileReason]:
    active = _latest_active(book, scope, observation)
    reverted: list[str] = []
    if active is not None:
        last = _parse_timestamp(active.last_seen_at)
        first = _parse_timestamp(active.first_seen_at)
        assert last is not None and first is not None
        if observed_at < last:
            return active, (), ReconcileReason.OUT_OF_ORDER_OBSERVATION
        if active.amount_thb != observation.claim.amount_thb:
            if observed_at == last:
                return active, (), ReconcileReason.OUT_OF_ORDER_OBSERVATION
            old = _revert(active, observed_at)
            book.put(old)
            reverted.append(old.candidate_id)
            active = None
        else:
            if observed_at == last:
                return active, (), ReconcileReason.DUPLICATE_OBSERVATION
            count = active.observation_count + 1
            confirmed = active.state is CandidateState.CONFIRMED or (
                count >= 2 and observed_at >= first + REPLACEMENT_TOLERANCE)
            updated = replace(
                active,
                state=(CandidateState.CONFIRMED if confirmed
                       else CandidateState.PENDING_24H),
                last_seen_at=_iso_timestamp(observed_at),
                observation_count=count,
                claim_ids=_append_claim_id(active, observation.claim.claim_id),
                confirmed_at=(active.confirmed_at or _iso_timestamp(observed_at)
                              if confirmed else None),
            )
            book.put(updated)
            return updated, (), (
                ReconcileReason.REPLACEMENT_PERSISTED_24H if confirmed
                else ReconcileReason.REPLACEMENT_STILL_PENDING)
    candidate = _new_candidate(
        scope, observation, observed_at,
        state=CandidateState.PENDING_24H,
        replaces_amount_thb=canonical_amount,
    )
    book.put(candidate)
    return candidate, tuple(reverted), (
        ReconcileReason.REPLACEMENT_CHANGED if reverted
        else ReconcileReason.REPLACEMENT_FIRST_SEEN)


def _revert_to_canonical(book: CandidateBook, scope: PriceScope,
                         observation: ReconcileObservation,
                         observed_at: datetime,
                         canonical_amount: int) -> tuple[str, ...]:
    reverted: list[str] = []
    for candidate in book.active_for_stream(
            scope, observation.claim.source_id, observation.target_id):
        if candidate.amount_thb == canonical_amount:
            continue
        last = _parse_timestamp(candidate.last_seen_at)
        assert last is not None
        if observed_at > last:
            updated = _revert(candidate, observed_at)
            book.put(updated)
            reverted.append(updated.candidate_id)
    return tuple(reverted)


def _preflight(observation: ReconcileObservation) -> Optional[ReconcileDecision]:
    claim = observation.claim
    match = observation.match
    if match.state is TrimMatchState.AMBIGUOUS:
        return ReconcileDecision(
            ReconcileDisposition.REVIEW,
            (ReconcileReason.AMBIGUOUS_TRIM,), claim.claim_id,
            trim_id=None,
        )
    if match.state is not TrimMatchState.EXACT or not match.trim_id:
        return ReconcileDecision(
            ReconcileDisposition.REVIEW,
            (ReconcileReason.UNMAPPED_TRIM,), claim.claim_id,
            trim_id=None,
        )
    if claim.price_type is PriceType.UNKNOWN:
        return ReconcileDecision(
            ReconcileDisposition.REVIEW,
            (ReconcileReason.PRICE_TYPE_UNKNOWN,), claim.claim_id,
            trim_id=match.trim_id,
        )
    if observation.observed_at() is None:
        return ReconcileDecision(
            ReconcileDisposition.REVIEW,
            (ReconcileReason.OBSERVATION_TIME_MISSING,), claim.claim_id,
            trim_id=match.trim_id,
        )
    if claim.price_type in (PriceType.CAMPAIGN_PRICE, PriceType.FINANCE_PRICE) and not (
            observation.campaign_id and observation.option_id):
        reasons = [ReconcileReason.CAMPAIGN_SCOPE_REQUIRED]
        observed = observation.observed_at()
        if observed is not None and _explicitly_closed(claim, observed.date()):
            reasons.append(ReconcileReason.EXPLICIT_WINDOW_CLOSED)
        return ReconcileDecision(
            ReconcileDisposition.REVIEW,
            tuple(reasons), claim.claim_id,
            trim_id=match.trim_id,
        )
    return None


def reconcile_one(observation: ReconcileObservation, ledger: PriceLedger, *,
                  candidate_book: Optional[CandidateBook] = None,
                  forced_conflict_amounts: tuple[int, ...] = ()) -> ReconcileDecision:
    """Reconcile one observation and advance only staging candidate state."""
    book = candidate_book or CandidateBook()
    preflight = _preflight(observation)
    if preflight is not None:
        return preflight
    claim = observation.claim
    assert observation.match.trim_id is not None
    observed_at = observation.observed_at()
    assert observed_at is not None
    when = observed_at.date()
    scope = replacement_scope(observation)
    assert scope is not None

    if forced_conflict_amounts:
        return ReconcileDecision(
            ReconcileDisposition.CONFLICT,
            (ReconcileReason.SOURCE_CONFLICT,), claim.claim_id,
            trim_id=scope.trim_id, scope=scope,
            conflicting_amounts=forced_conflict_amounts,
        )

    current, canonical_conflicts = current_record_for_scope(ledger, scope, as_of=when)
    if canonical_conflicts and current is None:
        return ReconcileDecision(
            ReconcileDisposition.CONFLICT,
            (ReconcileReason.CANONICAL_CONFLICT,), claim.claim_id,
            trim_id=scope.trim_id, scope=scope,
            conflicting_amounts=canonical_conflicts,
        )

    # Literal explicit window beats every inference about document age/role.
    if _explicitly_closed(claim, when):
        candidate, reverted = _observe_safe_candidate(
            book, scope, observation, observed_at,
            historical_only=True,
            replaces_amount_thb=current.amount_thb if current else None,
        )
        return ReconcileDecision(
            ReconcileDisposition.HISTORICAL_ONLY,
            (ReconcileReason.EXPLICIT_WINDOW_CLOSED,), claim.claim_id,
            trim_id=scope.trim_id, scope=scope,
            canonical_amount_thb=current.amount_thb if current else None,
            candidate_id=candidate.candidate_id,
            reverted_candidate_ids=reverted,
        )

    if current is not None and current.amount_thb == claim.amount_thb:
        reverted = _revert_to_canonical(
            book, scope, observation, observed_at, current.amount_thb)
        reasons = [ReconcileReason.SAME_CANONICAL_PRICE]
        if reverted:
            reasons.append(ReconcileReason.REPLACEMENT_REVERTED)
        return ReconcileDecision(
            ReconcileDisposition.NO_CHANGE,
            tuple(reasons), claim.claim_id,
            trim_id=scope.trim_id, scope=scope,
            canonical_amount_thb=current.amount_thb,
            reverted_candidate_ids=reverted,
        )

    can_drive = _role_can_drive_current(observation)
    if not can_drive:
        return ReconcileDecision(
            ReconcileDisposition.REVIEW,
            (_role_review_reason(observation),), claim.claim_id,
            trim_id=scope.trim_id, scope=scope,
            canonical_amount_thb=current.amount_thb if current else None,
        )

    if current is None:
        candidate, reverted = _observe_safe_candidate(
            book, scope, observation, observed_at)
        reasons: list[ReconcileReason] = []
        if _future_start(claim, when):
            reasons.append(ReconcileReason.FUTURE_SCHEDULED)
        if _has_type_transition(ledger, scope, when):
            reasons.append(ReconcileReason.TYPE_TRANSITION)
        if not reasons:
            reasons.append(ReconcileReason.NEW_PRICE_STREAM)
        return ReconcileDecision(
            ReconcileDisposition.SAFE_CANDIDATE,
            tuple(reasons), claim.claim_id,
            trim_id=scope.trim_id, scope=scope,
            candidate_id=candidate.candidate_id,
            reverted_candidate_ids=reverted,
        )

    # Different amount in the same canonical stream: protect the old value for
    # at least 24h and require a later actual observation of the new value.
    candidate, reverted, reason = _observe_replacement(
        book, scope, observation, observed_at, current.amount_thb)
    if reason is ReconcileReason.OUT_OF_ORDER_OBSERVATION:
        return ReconcileDecision(
            ReconcileDisposition.REVIEW,
            (reason,), claim.claim_id,
            trim_id=scope.trim_id, scope=scope,
            canonical_amount_thb=current.amount_thb,
            candidate_id=candidate.candidate_id,
        )
    disposition = (
        ReconcileDisposition.CONFIRMED_REPLACEMENT
        if candidate.state is CandidateState.CONFIRMED
        else ReconcileDisposition.PENDING_REPLACEMENT
    )
    return ReconcileDecision(
        disposition,
        (reason,), claim.claim_id,
        trim_id=scope.trim_id, scope=scope,
        canonical_amount_thb=current.amount_thb,
        candidate_id=candidate.candidate_id,
        reverted_candidate_ids=reverted,
    )


def _conflict_key(observation: ReconcileObservation) -> Optional[tuple]:
    """Current-role same-source conflicts in one fetch batch.

    Cross-source consensus remains ``pricefeed.decide``'s job.  P5 only blocks
    one source contradicting itself inside the same automatic replacement scope.
    Future/historical windows are not current conflicts.
    """
    if _preflight(observation) is not None:
        return None
    observed = observation.observed_at()
    if observed is None:
        return None
    when = observed.date()
    if not _claim_live_on(observation.claim, when):
        return None
    if not _role_can_drive_current(observation):
        return None
    scope = replacement_scope(observation)
    if scope is None:
        return None
    return (observation.claim.source_id, *scope.key())


def reconcile_batch(observations: Iterable[ReconcileObservation],
                    ledger: PriceLedger, *,
                    candidate_book: Optional[CandidateBook] = None) -> ReconcileBatchResult:
    """Reconcile a fetch batch, preserving input order and candidate history."""
    rows = list(observations)
    book = candidate_book or CandidateBook()

    grouped: dict[tuple, list[ReconcileObservation]] = {}
    for observation in rows:
        key = _conflict_key(observation)
        if key is not None:
            grouped.setdefault(key, []).append(observation)
    conflicts: dict[str, tuple[int, ...]] = {}
    for group in grouped.values():
        amounts = tuple(sorted({observation.claim.amount_thb for observation in group}))
        if len(amounts) > 1:
            for observation in group:
                conflicts[observation.claim.claim_id] = amounts

    # Candidate transitions are chronological even if a caller hands us a batch
    # in arbitrary row order. Decisions are mapped back to original order.
    indexed = list(enumerate(rows))
    indexed.sort(key=lambda pair: (
        pair[1].observed_at() or datetime.max.astimezone(),
        pair[0],
    ))
    decisions: dict[int, ReconcileDecision] = {}
    for index, observation in indexed:
        decisions[index] = reconcile_one(
            observation, ledger, candidate_book=book,
            forced_conflict_amounts=conflicts.get(observation.claim.claim_id, ()),
        )
    ordered = tuple(decisions[index] for index in range(len(rows)))
    return ReconcileBatchResult(ordered, book)
