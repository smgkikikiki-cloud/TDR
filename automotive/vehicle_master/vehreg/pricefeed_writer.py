"""Turn resolver-accepted price observations into canonical price commands.

``pricefeed.run`` decides which harvested claims are canonical and which
are not; everything it did not accept never reaches here. What is left is
a set of observations about prices, and this converts them into the same
APPEND_PRICE / CORRECT_PRICE commands the owner's own Save produces --
one writer, one ledger, one history, whether a price was typed in or
harvested.

Precedence is decided here, deterministically, and never by asking a
person:

  the same amount again              no command; a repeat is not a change
  nothing held for that scope        appended
  a newer price than the one held    supersedes it, keeping the old row
                                     readable over the period it covered
  an observation of the same day as
  or older than a price somebody
  else put there                     ignored -- the owner outranks the feed
  an observation older than a price
  the feed itself wrote              stale, dropped
  two feed observations claiming the
  same starting day                  an exception, not a review queue

"Newer" is by the day the price starts (``effective_from``, falling back
to the observation date), and a tie goes to whoever is already there, so
a feed re-reading the same page cannot flip a value back and forth.

Nothing here touches the filesystem or the network: it takes what the
ledger currently holds and returns commands. ``tools/pricefeed_write.py``
is what loads, applies and publishes them.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Iterable, Optional

#: What the feed itself writes. Everything else in the ledger was put
#: there by somebody or by another source, and the feed never outranks
#: that for the same effective state -- only a strictly newer price does.
FEED_SOURCE = "price_harvest"
FEED_ACTORS = frozenset({"", "price-feed", "price_harvest"})

WRITTEN = "WRITTEN"
UNCHANGED = "UNCHANGED"
SUPERSEDED_BY_MANUAL = "SUPERSEDED_BY_MANUAL"
STALE = "STALE"
EXCEPTION = "EXCEPTION"

STATUSES = (WRITTEN, UNCHANGED, SUPERSEDED_BY_MANUAL, STALE, EXCEPTION)


@dataclass(frozen=True)
class HeldPrice:
    """What the ledger currently resolves for one price scope.

    This is the *resolved* current row, not every row ever recorded: the
    feed's decision is about what is being served, and the history behind
    it is the ledger's business.
    """

    trim_id: str
    price_type: str
    amount_thb: int
    observed_at: Optional[str] = None
    effective_from: Optional[str] = None
    source: Optional[str] = None
    reviewed_by: Optional[str] = None
    campaign_id: Optional[str] = None
    option_id: Optional[str] = None

    @property
    def starts(self) -> str:
        return self.effective_from or self.observed_at or ""

    @property
    def own(self) -> bool:
        """True only for a row this feed wrote itself."""
        return ((self.source or "").strip().lower() == FEED_SOURCE
                and (self.reviewed_by or "").strip().lower() in FEED_ACTORS)


@dataclass
class OfferOutcome:
    offer: dict
    status: str
    command: Optional[dict] = None
    reason: str = ""


def _key(trim_id: str, price_type: str,
         campaign_id: Optional[str], option_id: Optional[str]) -> tuple:
    return (trim_id, price_type, campaign_id or "", option_id or "")


def held_index(held: Iterable[HeldPrice]) -> dict[tuple, HeldPrice]:
    index: dict[tuple, HeldPrice] = {}
    for row in held:
        index[_key(row.trim_id, row.price_type, row.campaign_id, row.option_id)] = row
    return index


def plan_offers(
    offers: Iterable[dict],
    held: Iterable[HeldPrice],
    *,
    observed_at: str,
    source: str = FEED_SOURCE,
) -> list[OfferOutcome]:
    """Decide, per accepted offer, whether anything should be written."""
    index = held_index(held)
    outcomes: list[OfferOutcome] = []
    for offer in offers:
        trim_id = str(offer.get("trim_id") or "")
        price_type = str(offer.get("price_type") or "")
        amount = offer.get("amount_thb")
        if not trim_id or not price_type or not isinstance(amount, int) or amount <= 0:
            outcomes.append(OfferOutcome(
                offer=offer, status=EXCEPTION,
                reason="offer carries no resolved trim, price type or positive amount"))
            continue

        campaign_id = (offer.get("campaign_hint") or "").strip() or None
        option_id = (offer.get("option_hint") or "").strip() or None
        if campaign_id and not option_id:
            option_id = "default"
        if price_type in ("CAMPAIGN_PRICE", "FINANCE_PRICE") and not campaign_id:
            outcomes.append(OfferOutcome(
                offer=offer, status=EXCEPTION,
                reason=f"{price_type} with no campaign to belong to"))
            continue

        starts = str(offer.get("effective_from") or observed_at)
        current = index.get(_key(trim_id, price_type, campaign_id, option_id))

        if current is not None and current.amount_thb == amount:
            outcomes.append(OfferOutcome(
                offer=offer, status=UNCHANGED,
                reason="the source still says what the ledger already holds"))
            continue

        if current is not None and current.starts >= starts:
            if not current.own:
                # Somebody, or another source, put this price here and the
                # feed is not looking at anything newer. It stands.
                outcomes.append(OfferOutcome(
                    offer=offer, status=SUPERSEDED_BY_MANUAL,
                    reason=(f"{current.amount_thb:,} THB starting {current.starts} "
                            f"from {current.reviewed_by or current.source or 'another source'} "
                            f"outranks this observation")))
            elif current.starts > starts:
                outcomes.append(OfferOutcome(
                    offer=offer, status=STALE,
                    reason=(f"the ledger already holds a price starting {current.starts}; "
                            f"this observation starts {starts}")))
            else:
                # Two automatic prices for the same starting day. Which one
                # was ever true is not something a rule can settle.
                outcomes.append(OfferOutcome(
                    offer=offer, status=EXCEPTION,
                    reason=(f"the source says {amount:,} THB from {starts} but the feed "
                            f"already wrote {current.amount_thb:,} THB for the same day")))
            continue

        payload: dict[str, Any] = {
            "trim_id": trim_id,
            "amount_thb": amount,
            "price_type": price_type,
            "effective_from": starts,
            "observed_at": observed_at,
            "source": source,
        }
        if offer.get("effective_to"):
            payload["effective_to"] = offer["effective_to"]
        if offer.get("reference_price_thb"):
            payload["reference_price_thb"] = offer["reference_price_thb"]
        if campaign_id:
            payload["campaign_id"] = campaign_id
            payload["option_id"] = option_id
        urls = offer.get("urls") or []
        if urls:
            payload["source_ref"] = urls[0]
        document_id = offer.get("source_document_id") or ""
        if document_id:
            payload["source_document_id"] = document_id

        if current is None:
            command = {"operation": "APPEND_PRICE", "canonical_id": trim_id,
                       "payload": payload}
            reason = "nothing held for this scope"
        else:
            # The old row stays true of the period it covered; it is given an
            # end date rather than being rewritten or deleted.
            command = {"operation": "CORRECT_PRICE", "canonical_id": trim_id,
                       "payload": {**payload, "mode": "supersede", "as_of": starts}}
            reason = (f"{current.amount_thb:,} THB from {current.starts} "
                      f"superseded by {amount:,} THB from {starts}")
        outcomes.append(OfferOutcome(offer=offer, status=WRITTEN,
                                     command=command, reason=reason))
    return outcomes


def batch_id_for(commands: Iterable[dict], *, prefix: str = "pricefeed") -> str:
    """A batch id that is the content, so a repeat is a replay.

    Applying the same commands twice has to be the same batch, or the
    pipeline's replay marker cannot recognise it and the second run writes
    the same price again under a new id.
    """
    digest = hashlib.sha256(
        json.dumps(list(commands), sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]
    return f"{prefix}-{digest}"


def batch_from_outcomes(
    outcomes: Iterable[OfferOutcome],
    *,
    year: int,
    submitted_at: str,
    batch_id: Optional[str] = None,
    actor: str = "price-feed",
) -> Optional[dict]:
    commands = [o.command for o in outcomes if o.status == WRITTEN and o.command]
    if not commands:
        return None
    batch_id = batch_id or batch_id_for(commands)
    return {
        "schema_version": 1,
        "batch_id": batch_id,
        "year": year,
        "submitted_at": submitted_at,
        "source": {"kind": "PRICE_HARVEST", "ref": "tools/pricefeed_harvest.py"},
        "actor": actor,
        "reason": "automated price observation",
        "commands": [
            {**command, "command_id": f"{batch_id}-{index}"}
            for index, command in enumerate(commands, start=1)
        ],
    }


def exception_rows(outcomes: Iterable[OfferOutcome],
                   review_items: Iterable[dict] = ()) -> list[dict]:
    """What the feed could not settle: unresolved identity, or a real conflict.

    Everything the resolver rejected is here too. A price nobody can place
    is work somebody has to do, and it is durable work: it belongs in the
    exception store, not in a log line of a workflow run that scrolls away.
    """
    rows = [_exception_row(outcome.offer, outcome.reason, "PRICE_CONFLICT")
            for outcome in outcomes if outcome.status == EXCEPTION]
    rows.extend(
        _exception_row(item, ", ".join(item.get("reasons") or ["unresolved"]),
                       "PRICE_IDENTITY")
        for item in review_items)
    return rows


def _exception_row(item: dict, reason: str, kind: str) -> dict:
    return {
        "kind": kind,
        "reason": reason,
        "source_identity": {
            "trim_id": item.get("trim_id"),
            "trim_candidates": item.get("trim_candidates"),
            "amount_thb": item.get("amount_thb"),
            "price_type": item.get("price_type"),
            "effective_from": item.get("effective_from"),
            "campaign_id": (item.get("campaign_hint") or None),
            "urls": item.get("urls"),
            "claim_ids": item.get("claim_ids"),
        },
    }


def summarize(outcomes: Iterable[OfferOutcome]) -> dict[str, int]:
    counts = {status: 0 for status in STATUSES}
    for outcome in outcomes:
        counts[outcome.status] = counts.get(outcome.status, 0) + 1
    return counts
