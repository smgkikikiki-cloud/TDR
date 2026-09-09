from __future__ import annotations

from datetime import datetime, timedelta, timezone

from vehreg.price_match import TrimMatchMethod, TrimMatchResult, TrimMatchState
from vehreg.price_reconcile import (
    CandidateBook,
    CandidateState,
    ReconcileDisposition,
    ReconcileObservation,
    ReconcileReason,
    reconcile_batch,
    reconcile_one,
)
from vehreg.price_sources import TargetRole
from vehreg.pricefeed import PriceClaim, SourceDocument
from vehreg.pricing import PriceLedger, PriceRecord, PriceType


TRIM = "test.brand.model.gen.trim.grade"
SOURCE = "official_test_th"
TARGET = "test_current_price"
T0 = datetime(2026, 9, 9, 1, 0, tzinfo=timezone.utc)


def _match(*, state: TrimMatchState = TrimMatchState.EXACT,
           trim_id: str | None = TRIM) -> TrimMatchResult:
    return TrimMatchResult(
        state=state,
        model_id="test.brand.model" if state is not TrimMatchState.UNMAPPED else None,
        trim_id=trim_id if state is TrimMatchState.EXACT else None,
        candidate_ids=((trim_id,) if state is TrimMatchState.EXACT and trim_id else
                       ("a", "b") if state is TrimMatchState.AMBIGUOUS else ()),
        method=(TrimMatchMethod.EXACT_NAME if state is TrimMatchState.EXACT
                else TrimMatchMethod.AMBIGUOUS_PARTIAL if state is TrimMatchState.AMBIGUOUS
                else TrimMatchMethod.NO_MODEL),
        reason="fixture",
        normalized_trim_raw="GRADE",
    )


def _claim(amount: int, *, price_type: PriceType = PriceType.LIST_PRICE,
           effective_from: str | None = None,
           effective_to: str | None = None,
           claim_id: str | None = None) -> PriceClaim:
    return PriceClaim(
        claim_id=claim_id or f"claim-{price_type.value}-{amount}",
        document_id="sha256:" + "a" * 64,
        source_id=SOURCE,
        brand_raw="TEST",
        model_raw="MODEL",
        trim_raw="GRADE",
        amount_thb=amount,
        price_type=price_type,
        effective_from=effective_from,
        effective_to=effective_to,
    )


def _document(at: datetime, *, published_at: str | None = None) -> SourceDocument:
    stamp = at.isoformat()
    return SourceDocument(
        document_id="sha256:" + "a" * 64,
        source_id=SOURCE,
        url="https://example.com/price",
        content_hash="sha256:" + "a" * 64,
        published_at=published_at,
        first_seen_at=stamp,
        fetched_at=stamp,
    )


def _obs(amount: int, *, at: datetime = T0,
         price_type: PriceType = PriceType.LIST_PRICE,
         role: TargetRole = TargetRole.PRICE_LIST,
         effective_from: str | None = None,
         effective_to: str | None = None,
         state: TrimMatchState = TrimMatchState.EXACT,
         campaign_id: str | None = None,
         option_id: str | None = None,
         target_id: str = TARGET,
         claim_id: str | None = None,
         published_at: str | None = None) -> ReconcileObservation:
    return ReconcileObservation(
        claim=_claim(
            amount,
            price_type=price_type,
            effective_from=effective_from,
            effective_to=effective_to,
            claim_id=claim_id,
        ),
        match=_match(state=state),
        target_id=target_id,
        target_role=role,
        document=_document(at, published_at=published_at),
        campaign_id=campaign_id,
        option_id=option_id,
    )


def _ledger(amount: int | None = None, *,
            price_type: PriceType = PriceType.LIST_PRICE,
            campaign_id: str | None = None,
            option_id: str | None = None) -> PriceLedger:
    ledger = PriceLedger(2026)
    if amount is not None:
        ledger.records.append(PriceRecord(
            trim_id=TRIM,
            amount_thb=amount,
            price_type=price_type,
            observed_at="2026-09-01",
            source="official",
            campaign_id=campaign_id,
            option_id=option_id,
        ))
    return ledger


def test_unmapped_and_ambiguous_p4_results_never_get_rematched() -> None:
    ledger = _ledger()

    unmapped = reconcile_one(
        _obs(699000, state=TrimMatchState.UNMAPPED), ledger)
    ambiguous = reconcile_one(
        _obs(699000, state=TrimMatchState.AMBIGUOUS), ledger)

    assert unmapped.disposition is ReconcileDisposition.REVIEW
    assert unmapped.reasons == (ReconcileReason.UNMAPPED_TRIM,)
    assert ambiguous.disposition is ReconcileDisposition.REVIEW
    assert ambiguous.reasons == (ReconcileReason.AMBIGUOUS_TRIM,)


def test_new_current_price_stream_is_safe_candidate_not_canonical_write() -> None:
    book = CandidateBook()
    decision = reconcile_one(_obs(699000), _ledger(), candidate_book=book)

    assert decision.disposition is ReconcileDisposition.SAFE_CANDIDATE
    assert decision.reasons == (ReconcileReason.NEW_PRICE_STREAM,)
    candidate = book.candidates[decision.candidate_id]
    assert candidate.state is CandidateState.NEW
    assert candidate.amount_thb == 699000
    assert candidate.replaces_amount_thb is None


def test_same_canonical_price_is_no_change() -> None:
    decision = reconcile_one(_obs(699000), _ledger(699000))

    assert decision.disposition is ReconcileDisposition.NO_CHANGE
    assert decision.reasons == (ReconcileReason.SAME_CANONICAL_PRICE,)
    assert decision.canonical_amount_thb == 699000


def test_replacement_first_seen_stays_pending_and_old_price_remains_current() -> None:
    book = CandidateBook()
    ledger = _ledger(699000)

    decision = reconcile_one(_obs(719000), ledger, candidate_book=book)

    assert decision.disposition is ReconcileDisposition.PENDING_REPLACEMENT
    assert decision.reasons == (ReconcileReason.REPLACEMENT_FIRST_SEEN,)
    candidate = book.candidates[decision.candidate_id]
    assert candidate.state is CandidateState.PENDING_24H
    assert candidate.replaces_amount_thb == 699000
    assert candidate.confirmed_at is None
    # P5 never mutates canonical truth.
    assert ledger.current_list_amount(TRIM) == 699000


def test_second_observation_before_24h_remains_pending() -> None:
    book = CandidateBook()
    ledger = _ledger(699000)
    first = reconcile_one(_obs(719000), ledger, candidate_book=book)

    second = reconcile_one(
        _obs(719000, at=T0 + timedelta(hours=23, minutes=59)),
        ledger, candidate_book=book)

    assert second.candidate_id == first.candidate_id
    assert second.disposition is ReconcileDisposition.PENDING_REPLACEMENT
    assert second.reasons == (ReconcileReason.REPLACEMENT_STILL_PENDING,)
    assert book.candidates[first.candidate_id].observation_count == 2


def test_second_real_observation_at_24h_confirms_replacement() -> None:
    book = CandidateBook()
    ledger = _ledger(699000)
    first = reconcile_one(_obs(719000), ledger, candidate_book=book)

    second = reconcile_one(
        _obs(719000, at=T0 + timedelta(hours=24)),
        ledger, candidate_book=book)

    candidate = book.candidates[first.candidate_id]
    assert second.disposition is ReconcileDisposition.CONFIRMED_REPLACEMENT
    assert second.reasons == (ReconcileReason.REPLACEMENT_PERSISTED_24H,)
    assert candidate.state is CandidateState.CONFIRMED
    assert candidate.observation_count == 2
    assert candidate.confirmed_at == (T0 + timedelta(hours=24)).isoformat()
    assert ledger.current_list_amount(TRIM) == 699000


def test_replaying_same_observation_never_confirms_by_clock_passage() -> None:
    book = CandidateBook()
    ledger = _ledger(699000)
    first = reconcile_one(_obs(719000), ledger, candidate_book=book)

    replay = reconcile_one(_obs(719000), ledger, candidate_book=book)

    assert replay.candidate_id == first.candidate_id
    assert replay.disposition is ReconcileDisposition.PENDING_REPLACEMENT
    assert replay.reasons == (ReconcileReason.DUPLICATE_OBSERVATION,)
    assert book.candidates[first.candidate_id].observation_count == 1
    assert book.candidates[first.candidate_id].confirmed_at is None


def test_return_to_canonical_price_reverts_pending_candidate() -> None:
    book = CandidateBook()
    ledger = _ledger(699000)
    pending = reconcile_one(_obs(719000), ledger, candidate_book=book)

    reverted = reconcile_one(
        _obs(699000, at=T0 + timedelta(hours=12)),
        ledger, candidate_book=book)

    candidate = book.candidates[pending.candidate_id]
    assert reverted.disposition is ReconcileDisposition.NO_CHANGE
    assert reverted.reasons == (
        ReconcileReason.SAME_CANONICAL_PRICE,
        ReconcileReason.REPLACEMENT_REVERTED,
    )
    assert candidate.state is CandidateState.REVERTED
    assert candidate.reverted_at == (T0 + timedelta(hours=12)).isoformat()


def test_different_replacement_restarts_24h_window() -> None:
    book = CandidateBook()
    ledger = _ledger(699000)
    first = reconcile_one(_obs(719000), ledger, candidate_book=book)

    changed = reconcile_one(
        _obs(729000, at=T0 + timedelta(hours=10)),
        ledger, candidate_book=book)

    assert changed.disposition is ReconcileDisposition.PENDING_REPLACEMENT
    assert changed.reasons == (ReconcileReason.REPLACEMENT_CHANGED,)
    assert first.candidate_id in changed.reverted_candidate_ids
    assert book.candidates[first.candidate_id].state is CandidateState.REVERTED
    assert book.candidates[changed.candidate_id].first_seen_at == (
        T0 + timedelta(hours=10)).isoformat()

    still_pending = reconcile_one(
        _obs(729000, at=T0 + timedelta(hours=30)),
        ledger, candidate_book=book)
    assert still_pending.disposition is ReconcileDisposition.PENDING_REPLACEMENT


def test_campaign_needs_explicit_campaign_and_option_scope() -> None:
    decision = reconcile_one(
        _obs(579000, price_type=PriceType.CAMPAIGN_PRICE,
             role=TargetRole.PROMOTION),
        _ledger())

    assert decision.disposition is ReconcileDisposition.REVIEW
    assert decision.reasons == (ReconcileReason.CAMPAIGN_SCOPE_REQUIRED,)


def test_bound_campaign_replacement_gets_its_own_24h_stream() -> None:
    ledger = _ledger(
        579000,
        price_type=PriceType.CAMPAIGN_PRICE,
        campaign_id="rain",
        option_id="cash",
    )
    book = CandidateBook()

    first = reconcile_one(
        _obs(599000, price_type=PriceType.CAMPAIGN_PRICE,
             role=TargetRole.PROMOTION,
             campaign_id="rain", option_id="cash"),
        ledger, candidate_book=book)
    second = reconcile_one(
        _obs(599000, at=T0 + timedelta(hours=24),
             price_type=PriceType.CAMPAIGN_PRICE,
             role=TargetRole.PROMOTION,
             campaign_id="rain", option_id="cash"),
        ledger, candidate_book=book)

    assert first.disposition is ReconcileDisposition.PENDING_REPLACEMENT
    assert second.disposition is ReconcileDisposition.CONFIRMED_REPLACEMENT
    assert second.scope.campaign_id == "rain"
    assert second.scope.option_id == "cash"


def test_campaign_options_do_not_conflict_with_each_other() -> None:
    ledger = _ledger()
    observations = [
        _obs(579000, price_type=PriceType.CAMPAIGN_PRICE,
             role=TargetRole.PROMOTION,
             campaign_id="motor-show", option_id="cash",
             claim_id="cash"),
        _obs(599000, price_type=PriceType.CAMPAIGN_PRICE,
             role=TargetRole.PROMOTION,
             campaign_id="motor-show", option_id="finance",
             claim_id="finance"),
    ]

    result = reconcile_batch(observations, ledger)

    assert all(decision.disposition is ReconcileDisposition.SAFE_CANDIDATE
               for decision in result.decisions)
    assert all(ReconcileReason.SOURCE_CONFLICT not in decision.reasons
               for decision in result.decisions)


def test_estimated_to_list_is_type_transition_not_conflict_or_retraction() -> None:
    ledger = _ledger(809000, price_type=PriceType.ESTIMATED_PRICE)

    decision = reconcile_one(_obs(789000, price_type=PriceType.LIST_PRICE), ledger)

    assert decision.disposition is ReconcileDisposition.SAFE_CANDIDATE
    assert decision.reasons == (ReconcileReason.TYPE_TRANSITION,)
    assert ledger.latest(TRIM, price_type=PriceType.ESTIMATED_PRICE).amount_thb == 809000
    assert not ledger.latest(TRIM, price_type=PriceType.ESTIMATED_PRICE).retracted


def test_explicit_end_date_is_literal_historical_only() -> None:
    book = CandidateBook()
    decision = reconcile_one(
        _obs(579000, effective_from="2026-08-21", effective_to="2026-08-30"),
        _ledger(), candidate_book=book)

    assert decision.disposition is ReconcileDisposition.HISTORICAL_ONLY
    assert decision.reasons == (ReconcileReason.EXPLICIT_WINDOW_CLOSED,)
    assert book.candidates[decision.candidate_id].historical_only is True


def test_old_publication_date_alone_does_not_expire_open_ended_bound_campaign() -> None:
    ledger = _ledger(
        579000,
        price_type=PriceType.CAMPAIGN_PRICE,
        campaign_id="open-ended",
        option_id="cash",
    )
    observation = _obs(
        599000,
        price_type=PriceType.CAMPAIGN_PRICE,
        role=TargetRole.PROMOTION,
        campaign_id="open-ended",
        option_id="cash",
        published_at="2025-01-01T00:00:00+00:00",
    )

    decision = reconcile_one(observation, ledger)

    assert decision.disposition is ReconcileDisposition.PENDING_REPLACEMENT
    assert ReconcileReason.EXPLICIT_WINDOW_CLOSED not in decision.reasons


def test_promotion_reference_msrp_cannot_replace_list_stream() -> None:
    decision = reconcile_one(
        _obs(699000, role=TargetRole.PROMOTION),
        _ledger(719000))

    assert decision.disposition is ReconcileDisposition.REVIEW
    assert decision.reasons == (ReconcileReason.PROMOTION_REFERENCE_ONLY,)


def test_blog_without_literal_effective_date_cannot_replace_current_price() -> None:
    decision = reconcile_one(
        _obs(719000, role=TargetRole.BLOG,
             published_at="2026-09-09T00:00:00+00:00"),
        _ledger(699000))

    assert decision.disposition is ReconcileDisposition.REVIEW
    assert decision.reasons == (ReconcileReason.NON_CURRENT_ROLE_NEEDS_DATE,)


def test_press_release_with_literal_new_effective_date_may_enter_24h_replacement() -> None:
    decision = reconcile_one(
        _obs(719000, role=TargetRole.PRESS_RELEASE,
             effective_from="2026-09-09"),
        _ledger(699000))

    assert decision.disposition is ReconcileDisposition.PENDING_REPLACEMENT


def test_same_source_current_pages_with_two_live_amounts_are_conflict() -> None:
    observations = [
        _obs(699000, target_id="home", claim_id="home-699"),
        _obs(719000, target_id="price-list", claim_id="list-719"),
    ]

    result = reconcile_batch(observations, _ledger(699000))

    assert all(decision.disposition is ReconcileDisposition.CONFLICT
               for decision in result.decisions)
    assert all(decision.reasons == (ReconcileReason.SOURCE_CONFLICT,)
               for decision in result.decisions)
    assert all(decision.conflicting_amounts == (699000, 719000)
               for decision in result.decisions)


def test_future_scheduled_new_stream_is_not_current_truth() -> None:
    decision = reconcile_one(
        _obs(719000, effective_from="2026-10-01"),
        _ledger())

    assert decision.disposition is ReconcileDisposition.SAFE_CANDIDATE
    assert decision.reasons == (ReconcileReason.FUTURE_SCHEDULED,)


def test_candidate_book_round_trip_preserves_confirmation_audit_fields() -> None:
    ledger = _ledger(699000)
    book = CandidateBook()
    first = reconcile_one(_obs(719000), ledger, candidate_book=book)
    reconcile_one(
        _obs(719000, at=T0 + timedelta(hours=24)),
        ledger, candidate_book=book)

    restored = CandidateBook.from_payload(book.to_payload())
    candidate = restored.candidates[first.candidate_id]

    assert candidate.state is CandidateState.CONFIRMED
    assert candidate.observation_count == 2
    assert candidate.first_seen_at == T0.isoformat()
    assert candidate.confirmed_at == (T0 + timedelta(hours=24)).isoformat()
