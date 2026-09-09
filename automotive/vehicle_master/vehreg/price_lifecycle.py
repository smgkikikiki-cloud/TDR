"""Price-intelligence lifecycle semantics.

This module deliberately keeps *observations* separate from canonical
:class:`vehreg.pricing.PriceRecord` rows.  A crawler may observe a new number,
but that number does not become canonical merely because time passed.

Core invariants:

* no explicit end date means open-ended;
* absence, article age and page age never imply expiry;
* replacement happens only inside the same replacement scope;
* a newly observed replacement must still be observed after 24 hours before it
  is eligible for automatic confirmation;
* campaign/finance offers without an explicit campaign/option scope never
  auto-replace another offer;
* candidate state is staging state, never canonical price truth.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Optional

from .pricing import PriceRecord, PriceType


REPLACEMENT_TOLERANCE = timedelta(hours=24)


class PriceValidityMode(str, Enum):
    """How the canonical record knows when it stops being applicable."""

    OPEN_ENDED = "OPEN_ENDED"
    EXPLICIT_WINDOW = "EXPLICIT_WINDOW"


class CanonicalPriceState(str, Enum):
    """State derived from canonical evidence, not persisted as a second truth."""

    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    RETRACTED = "RETRACTED"


class CandidateState(str, Enum):
    """Staging state for an observed price before canonical publication."""

    NEW = "NEW"
    PENDING_24H = "PENDING_24H"
    CONFIRMED = "CONFIRMED"
    REVERTED = "REVERTED"
    REVIEW = "REVIEW"


def _aware_timestamp(raw: str, field_name: str) -> datetime:
    """Parse one offset-aware ISO-8601 timestamp.

    The replacement SLA is measured in hours, so date-only values and naive
    local datetimes are intentionally rejected.
    """

    text = str(raw or "").strip().replace("Z", "+00:00")
    if not text:
        raise ValueError(f"{field_name} is required")
    try:
        value = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be ISO-8601, got {raw!r}") from exc
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone offset")
    return value


def validity_mode(record: PriceRecord) -> PriceValidityMode:
    """No explicit ``effective_to`` means open-ended, forever until evidence says otherwise."""

    return (PriceValidityMode.EXPLICIT_WINDOW
            if record.effective_to else PriceValidityMode.OPEN_ENDED)


def canonical_state(record: PriceRecord, *, as_of: date) -> CanonicalPriceState:
    """Derive the record's state without adding a duplicate persisted status field."""

    if record.retracted_at and record.retracted_at <= as_of.isoformat():
        return CanonicalPriceState.RETRACTED
    starts = record.effective_from or record.observed_at
    if starts and starts > as_of.isoformat():
        return CanonicalPriceState.SCHEDULED
    if record.effective_to and record.effective_to < as_of.isoformat():
        return CanonicalPriceState.CLOSED
    return CanonicalPriceState.ACTIVE


def replacement_scope(*, trim_id: str, price_type: PriceType,
                      campaign_id: Optional[str] = None,
                      option_id: Optional[str] = None) -> Optional[tuple[str, ...]]:
    """Return the scope inside which one observed price may replace another.

    LIST/INTRODUCTORY/ESTIMATED/etc. are single timelines per trim and type.
    Campaign and finance prices can coexist as alternatives, so they are never
    considered safe automatic replacements without an explicit campaign/option
    identity.  A future reconciler may map a new campaign to an old one via a
    human or evidence-backed decision; this primitive deliberately refuses to
    guess that relationship.
    """

    trim_id = str(trim_id or "").strip()
    if not trim_id:
        return None
    if price_type in (PriceType.CAMPAIGN_PRICE, PriceType.FINANCE_PRICE):
        campaign_id = str(campaign_id or "").strip()
        option_id = str(option_id or "").strip()
        if not campaign_id or not option_id:
            return None
        return (trim_id, price_type.value, campaign_id, option_id)
    return (trim_id, price_type.value)


@dataclass(frozen=True, slots=True)
class PriceCandidate:
    """One observed price awaiting reconciliation or confirmation.

    ``first_seen_at`` starts the 24-hour tolerance window.  Passing the clock is
    not enough: ``last_seen_at`` must itself be at or after
    ``confirmation_due_at``.  This forces a fresh observation after the window
    and prevents a candidate from confirming merely because the scheduler was
    asleep for a day.
    """

    candidate_id: str
    trim_id: str
    amount_thb: int
    price_type: PriceType
    first_seen_at: str
    last_seen_at: str
    state: CandidateState = CandidateState.NEW
    confirmation_due_at: Optional[str] = None
    campaign_id: Optional[str] = None
    option_id: Optional[str] = None

    def validate(self) -> list[str]:
        problems: list[str] = []
        if not self.candidate_id:
            problems.append("candidate_id is required")
        if not self.trim_id:
            problems.append("trim_id is required")
        if type(self.amount_thb) is not int or self.amount_thb <= 0:
            problems.append("amount_thb must be a positive integer")
        if not isinstance(self.price_type, PriceType):
            problems.append("price_type must be a PriceType")
        if not isinstance(self.state, CandidateState):
            problems.append("state must be a CandidateState")

        first = last = due = None
        for field_name in ("first_seen_at", "last_seen_at"):
            try:
                parsed = _aware_timestamp(getattr(self, field_name), field_name)
                if field_name == "first_seen_at":
                    first = parsed
                else:
                    last = parsed
            except ValueError as exc:
                problems.append(str(exc))
        if self.confirmation_due_at:
            try:
                due = _aware_timestamp(self.confirmation_due_at,
                                       "confirmation_due_at")
            except ValueError as exc:
                problems.append(str(exc))

        if first is not None and last is not None and last < first:
            problems.append("last_seen_at is before first_seen_at")
        if self.state in (CandidateState.PENDING_24H, CandidateState.CONFIRMED):
            if due is None:
                problems.append(f"{self.state.value} requires confirmation_due_at")
            elif first is not None and due != first + REPLACEMENT_TOLERANCE:
                problems.append("confirmation_due_at must be exactly 24h after first_seen_at")
        if self.state is CandidateState.CONFIRMED and due is not None and last is not None \
                and last < due:
            problems.append("CONFIRMED requires an observation at or after confirmation_due_at")
        return problems

    @property
    def scope(self) -> Optional[tuple[str, ...]]:
        return replacement_scope(
            trim_id=self.trim_id,
            price_type=self.price_type,
            campaign_id=self.campaign_id,
            option_id=self.option_id,
        )

    def begin_confirmation(self) -> "PriceCandidate":
        """Start the fixed 24-hour replacement tolerance from first observation."""

        first = _aware_timestamp(self.first_seen_at, "first_seen_at")
        due = first + REPLACEMENT_TOLERANCE
        return replace(
            self,
            state=CandidateState.PENDING_24H,
            confirmation_due_at=due.isoformat(),
        )

    def observed_again(self, observed_at: str) -> "PriceCandidate":
        """Record a later sighting without making any publication decision."""

        stamp = _aware_timestamp(observed_at, "observed_at")
        first = _aware_timestamp(self.first_seen_at, "first_seen_at")
        last = _aware_timestamp(self.last_seen_at, "last_seen_at")
        if stamp < first:
            raise ValueError("observed_at is before first_seen_at")
        if stamp < last:
            raise ValueError("observed_at is before last_seen_at")
        return replace(self, last_seen_at=stamp.isoformat())

    def survived_tolerance(self) -> bool:
        """True only after a fresh observation at or beyond the 24-hour mark."""

        if self.state is not CandidateState.PENDING_24H or not self.confirmation_due_at:
            return False
        due = _aware_timestamp(self.confirmation_due_at, "confirmation_due_at")
        last = _aware_timestamp(self.last_seen_at, "last_seen_at")
        return last >= due

    def confirm(self) -> "PriceCandidate":
        if not self.survived_tolerance():
            raise ValueError("candidate has not been re-observed after the 24h tolerance")
        return replace(self, state=CandidateState.CONFIRMED)

    def revert(self) -> "PriceCandidate":
        """Mark a transient/reverted observation; it never becomes canonical."""

        return replace(self, state=CandidateState.REVERTED)
