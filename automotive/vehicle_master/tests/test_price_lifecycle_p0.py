from datetime import date

import pytest

from vehreg.price_lifecycle import (
    CandidateState,
    CanonicalPriceState,
    PriceCandidate,
    PriceValidityMode,
    canonical_state,
    replacement_scope,
    validity_mode,
)
from vehreg.pricing import PriceRecord, PriceType


TRIM = "jaecoo.jaecoo_5_ev.j5.trim.max_plus_bev"


def _record(**changes):
    payload = {
        "trim_id": TRIM,
        "amount_thb": 699_000,
        "price_type": PriceType.LIST_PRICE,
        "observed_at": "2026-09-08",
        "source": "official_jaecoo_th",
    }
    payload.update(changes)
    return PriceRecord(**payload)


def _candidate(**changes):
    payload = {
        "candidate_id": "candidate-1",
        "trim_id": TRIM,
        "amount_thb": 719_000,
        "price_type": PriceType.LIST_PRICE,
        "first_seen_at": "2026-09-09T14:00:00+07:00",
        "last_seen_at": "2026-09-09T14:00:00+07:00",
    }
    payload.update(changes)
    return PriceCandidate(**payload)


def test_no_explicit_end_is_open_ended_and_does_not_expire_from_age():
    row = _record()
    assert validity_mode(row) is PriceValidityMode.OPEN_ENDED
    assert canonical_state(row, as_of=date(2036, 9, 8)) is CanonicalPriceState.ACTIVE


def test_explicit_end_is_the_only_calendar_expiry():
    row = _record(effective_to="2026-09-30")
    assert validity_mode(row) is PriceValidityMode.EXPLICIT_WINDOW
    assert canonical_state(row, as_of=date(2026, 9, 30)) is CanonicalPriceState.ACTIVE
    assert canonical_state(row, as_of=date(2026, 10, 1)) is CanonicalPriceState.CLOSED


def test_future_price_is_scheduled_not_active():
    row = _record(observed_at="2026-09-08", effective_from="2026-10-01")
    assert canonical_state(row, as_of=date(2026, 9, 9)) is CanonicalPriceState.SCHEDULED
    assert canonical_state(row, as_of=date(2026, 10, 1)) is CanonicalPriceState.ACTIVE


def test_retraction_outranks_open_ended_validity():
    row = _record(retracted_at="2026-09-10", retraction_reason="source corrected typo")
    assert canonical_state(row, as_of=date(2026, 9, 9)) is CanonicalPriceState.ACTIVE
    assert canonical_state(row, as_of=date(2026, 9, 10)) is CanonicalPriceState.RETRACTED


def test_replacement_scope_never_crosses_price_type():
    list_scope = replacement_scope(trim_id=TRIM, price_type=PriceType.LIST_PRICE)
    estimate_scope = replacement_scope(trim_id=TRIM, price_type=PriceType.ESTIMATED_PRICE)
    campaign_scope = replacement_scope(
        trim_id=TRIM,
        price_type=PriceType.CAMPAIGN_PRICE,
        campaign_id="j5-sep",
        option_id="cash",
    )
    assert list_scope != estimate_scope
    assert list_scope != campaign_scope


def test_campaign_without_explicit_offer_scope_cannot_auto_replace():
    assert replacement_scope(
        trim_id=TRIM,
        price_type=PriceType.CAMPAIGN_PRICE,
    ) is None
    assert replacement_scope(
        trim_id=TRIM,
        price_type=PriceType.CAMPAIGN_PRICE,
        campaign_id="j5-sep",
    ) is None


def test_24h_clock_alone_is_not_confirmation():
    pending = _candidate().begin_confirmation()
    assert pending.state is CandidateState.PENDING_24H
    assert pending.confirmation_due_at == "2026-09-10T14:00:00+07:00"
    assert not pending.survived_tolerance()
    with pytest.raises(ValueError, match="re-observed"):
        pending.confirm()


def test_candidate_must_be_observed_again_after_24h():
    pending = _candidate().begin_confirmation()
    before_due = pending.observed_again("2026-09-10T13:59:59+07:00")
    assert not before_due.survived_tolerance()

    after_due = before_due.observed_again("2026-09-10T14:00:01+07:00")
    assert after_due.survived_tolerance()
    confirmed = after_due.confirm()
    assert confirmed.state is CandidateState.CONFIRMED
    assert confirmed.validate() == []


def test_reverted_candidate_never_becomes_confirmed_by_time():
    reverted = _candidate().begin_confirmation().revert()
    later = reverted.observed_again("2026-09-11T14:00:00+07:00")
    assert later.state is CandidateState.REVERTED
    assert not later.survived_tolerance()


def test_naive_timestamps_are_rejected_for_24h_sla():
    candidate = _candidate(first_seen_at="2026-09-09T14:00:00")
    problems = candidate.validate()
    assert any("timezone offset" in problem for problem in problems)
