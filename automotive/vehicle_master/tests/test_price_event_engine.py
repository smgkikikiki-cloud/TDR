"""PEE-1 acceptance tests: rule-first, event-based AI price extraction.

No test touches the network or a real model.  Every AI response is scripted
through ``FakeProvider``; pages are inline fixtures.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os

import pytest

from vehreg.catalog import Catalog, DATA_DIR, DEFAULT_YEAR
from vehreg.price_event import (
    ChangeKind,
    EventState,
    EventStateError,
    EventStatus,
    PriceEventConfig,
    PriceEventEngine,
    diff_fingerprints,
    fingerprint_segments,
    price_segments,
    visible_text,
)
from vehreg.price_event_validate import EventReviewReason, extract_dates
from vehreg.price_fetch import FetchResult, FetchState
from vehreg.price_llm import (
    LLMProviderError,
    LLMResponse,
    register_provider,
    resolve_provider,
    unregister_provider,
)
from vehreg.price_match import TrimMatchState, match_trim_diagnostic
from vehreg.price_reconcile import (
    ReconcileDisposition,
    ReconcileObservation,
    ReconcileReason,
    reconcile_one,
)
from vehreg.price_sources import SourceTarget, TargetRole
from vehreg.pricefeed import SourceDocument, content_id
from vehreg.pricing import PriceLedger, PriceType

SOURCE = "official_jaecoo_th"
NOW = datetime(2026, 10, 12, 3, 0, tzinfo=timezone.utc)
FILLER = ("Lorem ipsum dolor sit amet consectetur adipiscing elit sed eiusmod "
          "tempor incididunt ut labore et dolore magna aliqua ") * 8


def target(role: TargetRole = TargetRole.CURRENT_MODEL_PAGE, *,
           source_id: str = SOURCE, tid: str = "t1") -> SourceTarget:
    return SourceTarget(id=tid, source_id=source_id,
                        url="https://www.omodajaecoo.co.th/th", role=role)


def page(body: str, noise: str = "") -> str:
    # Nav/footer/script noise sits >> window_chars away from the price block.
    return (f"<html><head><title>JAECOO</title><script>var t='{noise}'</script></head>"
            f"<body><nav>Home Models {noise}</nav><main>{FILLER}{body}{FILLER}</main>"
            f"<footer>Copyright {noise}</footer></body></html>")


def fetched(html: str, tgt: SourceTarget) -> FetchResult:
    raw = html.encode("utf-8")
    digest = content_id(raw)
    doc = SourceDocument(
        document_id=digest, source_id=tgt.source_id, url=tgt.url, content_hash=digest,
        first_seen_at=NOW.isoformat(), fetched_at=NOW.isoformat())
    return FetchResult(
        target_id=tgt.id, target_role=tgt.role, source_id=tgt.source_id, document=doc,
        raw_body=raw, text=html,
        state=FetchState(target_id=tgt.id, content_hash=digest,
                         first_seen_at=NOW.isoformat()))


class FakeProvider:
    """Scripted provider; counts calls so tests can prove "zero AI calls"."""

    def __init__(self, *replies, input_tokens=900, output_tokens=100) -> None:
        self.replies = list(replies)
        self.calls = 0
        self.requests = []
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens

    def complete(self, request):
        self.calls += 1
        self.requests.append(request)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        text = reply if isinstance(reply, str) else json.dumps({"claims": reply},
                                                               ensure_ascii=False)
        return LLMResponse(text, self.input_tokens, self.output_tokens, "fake-model")


def ai_claim(**over) -> dict:
    base = {
        "price_type": "LIST_PRICE", "amount_thb": 789000, "brand_raw": "JAECOO",
        "model_raw": "JAECOO 5 EV", "trim_raw": "ULTRA",
        "effective_from": None, "effective_to": None, "reference_price_thb": None,
        "conditions": None,
        "evidence_text": "JAECOO 5 EV ULTRA ราคาขายปลีกแนะนำ 789,000 บาท",
        "evidence_segment": 0,
    }
    base.update(over)
    return base


def engine(provider=None, *, state=None, catalog=None, clock=None, **cfg):
    config = PriceEventConfig(enabled=cfg.pop("enabled", True), max_output_tokens=500,
                              **cfg)
    return PriceEventEngine(config, provider=provider, state=state, catalog=catalog,
                            clock=clock or (lambda: NOW), sleep=lambda _s: None)


MIXED_BODY = (
    "<p>JAECOO 5 EV ULTRA ราคาขายปลีกแนะนำ 789,000 บาท</p>"
    "<p>JAECOO 5 EV MAX+ ราคาพิเศษ 599,000 บาท (จากราคา 699,000 บาท) 21–30 กันยายน 2569</p>"
    "<p>JAECOO 5 EV LONG RANGE MAX ราคาเมื่อใช้สินเชื่อ 649,000 บาท</p>"
    "<p>ผ่อนเริ่มต้น 12,900 บาท/เดือน เงินดาวน์ 199,000 บาท</p>"
)

PROMO_V1 = (
    "<h1>MORE RAIN, MORE GAIN</h1>"
    "<p>JAECOO 5 EV MAX+ Special Price THB 599,000 (from THB 699,000)</p>"
    "<p>Conditions: booking and delivery by 30 September 2026.</p>"
)


# ----------------------------------------------------------- feature flag / compat

def test_flag_is_off_by_default_and_engine_is_inert() -> None:
    assert PriceEventConfig().enabled is False
    assert PriceEventConfig.from_env({}).enabled is False
    assert PriceEventConfig.from_env({"TDR_PRICE_EVENT_ENGINE": "1"}).enabled is True

    provider = FakeProvider([ai_claim()])
    state = EventState()
    tgt = target()
    off = engine(provider, state=state, enabled=False)
    outcome = off.process(tgt, fetched(page(MIXED_BODY), tgt))

    assert outcome.status is EventStatus.DISABLED
    assert provider.calls == 0
    assert state.data["fingerprints"] == {} and state.data["usage"] == {}


def test_other_sources_are_left_to_the_existing_pipeline() -> None:
    provider = FakeProvider([ai_claim()])
    tgt = target(source_id="media_example")
    outcome = engine(provider).process(tgt, fetched(page(MIXED_BODY), tgt))
    assert outcome.status is EventStatus.SOURCE_NOT_ENABLED
    assert provider.calls == 0 and not outcome.ai_claims


def test_not_modified_fetch_is_a_no_op() -> None:
    tgt = target()
    result = FetchResult(target_id=tgt.id, target_role=tgt.role, source_id=SOURCE,
                         document=None, raw_body=b"", text="",
                         state=FetchState(target_id=tgt.id), not_modified=True)
    provider = FakeProvider([])
    assert engine(provider).process(tgt, result).status is EventStatus.NOT_MODIFIED
    assert provider.calls == 0


def test_invalid_config_is_rejected() -> None:
    with pytest.raises(ValueError):
        PriceEventEngine(PriceEventConfig(max_input_tokens=0))
    on = {"TDR_PRICE_EVENT_ENGINE": "1"}
    with pytest.raises(ValueError):
        PriceEventConfig.from_env({**on, "TDR_PRICE_EVENT_MAX_RETRIES": "-1"})
    # Flag off: malformed tuning values are never even parsed.
    assert PriceEventConfig.from_env({"TDR_PRICE_EVENT_MAX_RETRIES": "oops"}).enabled is False


# ------------------------------------------------------------- change detection

def test_unchanged_page_makes_zero_ai_calls_even_when_noise_changes() -> None:
    provider = FakeProvider([])
    eng = engine(provider)
    tgt = target(TargetRole.PROMOTION)

    first = eng.process(tgt, fetched(page(PROMO_V1, "build-1"), tgt))
    second = eng.process(tgt, fetched(page(PROMO_V1, "build-2 tracking-xyz"), tgt))

    assert first.status is EventStatus.DETERMINISTIC
    assert second.status is EventStatus.UNCHANGED and second.changes == ()
    assert provider.calls == 0


def test_fingerprint_distinguishes_amounts_dates_conditions_and_labels() -> None:
    def fp(body: str):
        return fingerprint_segments(price_segments(
            " ".join(f"{body}".split()), 140))

    base = ("JAECOO 5 EV MAX+ Special Price THB 599,000. "
            "Conditions: booking by 30 September 2026.")
    cases = {
        ChangeKind.AMOUNTS: base.replace("599,000", "589,000"),
        ChangeKind.DATES: base.replace("30 September 2026", "31 October 2026"),
        ChangeKind.CONDITIONS: base.replace("booking by", "booking and delivery by"),
        ChangeKind.LABELS: base.replace("MAX+", "MAX PLUS"),
    }
    for kind, changed in cases.items():
        kinds = diff_fingerprints(fp(base), fp(changed))
        assert kind in kinds, (kind, kinds)
    assert diff_fingerprints(fp(base), fp(base)) == ()
    assert diff_fingerprints(None, fp(base)) == (ChangeKind.FIRST_SEEN,)
    # Only the amount moved: conditions/dates/labels must not be blamed.
    assert diff_fingerprints(fp(base), fp(cases[ChangeKind.AMOUNTS])) == (
        ChangeKind.AMOUNTS,)


# ----------------------------------------------------- deterministic-first path

def test_deterministic_extraction_success_makes_zero_ai_calls() -> None:
    provider = FakeProvider([])
    eng = engine(provider)
    tgt = target(TargetRole.PROMOTION)
    eng.process(tgt, fetched(page(PROMO_V1), tgt))

    cheaper = PROMO_V1.replace("599,000", "589,000")
    outcome = eng.process(tgt, fetched(page(cheaper), tgt))

    assert outcome.status is EventStatus.DETERMINISTIC
    assert ChangeKind.AMOUNTS in outcome.changes
    assert provider.calls == 0 and outcome.ai_calls == 0 and not outcome.review


def test_changed_conditions_with_unchanged_amount_triggers_one_ai_call() -> None:
    campaign_quote = "JAECOO 5 EV MAX+ Special Price THB 599,000 (from THB 699,000)"
    provider = FakeProvider([ai_claim(
        price_type="CAMPAIGN_PRICE", amount_thb=599000, trim_raw="MAX+",
        reference_price_thb=699000, evidence_text=campaign_quote,
        conditions=["trade-in of any old car required"])])
    eng = engine(provider)
    tgt = target(TargetRole.PROMOTION)

    assert eng.process(tgt, fetched(page(PROMO_V1), tgt)).status is EventStatus.DETERMINISTIC
    changed = PROMO_V1.replace(
        "Conditions: booking",
        "Conditions: trade-in of any old car required; booking")
    outcome = eng.process(tgt, fetched(page(changed), tgt))

    assert ChangeKind.CONDITIONS in outcome.changes
    assert ChangeKind.AMOUNTS not in outcome.changes
    assert "CONDITIONS_CHANGED" in outcome.fallback_reasons
    assert provider.calls == 1 and outcome.status is EventStatus.AI_EXTRACTED
    # The AI restates a claim rules already produced: no duplicate claim, but the
    # conditions the rules cannot read are attached to the rule claim's id.
    assert outcome.ai_claims == ()
    detail, = outcome.details
    assert detail.origin == "rules+ai"
    assert detail.conditions == ("trade-in of any old car required",)


# ------------------------------------------------------------- AI path semantics

def run_ai(replies, *, body: str = MIXED_BODY, catalog=None, **cfg):
    provider = FakeProvider(replies)
    eng = engine(provider, catalog=catalog, **cfg)
    tgt = target()
    return eng, provider, tgt, eng.process(tgt, fetched(page(body), tgt))


def reasons(outcome) -> list[str]:
    return [item.reason.value for item in outcome.review]


def test_msrp_vs_campaign_vs_finance_classification() -> None:
    good = [
        ai_claim(),
        ai_claim(price_type="CAMPAIGN_PRICE", amount_thb=599000, trim_raw="MAX+",
                 reference_price_thb=699000,
                 effective_from="2026-09-21", effective_to="2026-09-30",
                 evidence_text="JAECOO 5 EV MAX+ ราคาพิเศษ 599,000 บาท (จากราคา 699,000 บาท)"),
        ai_claim(price_type="FINANCE_PRICE", amount_thb=649000, trim_raw="LONG RANGE MAX",
                 evidence_text="JAECOO 5 EV LONG RANGE MAX ราคาเมื่อใช้สินเชื่อ 649,000 บาท"),
    ]
    campaign_text = "JAECOO 5 EV MAX+ ราคาพิเศษ 599,000 บาท (จากราคา 699,000 บาท)"
    bad = [
        # campaign price presented as MSRP
        ai_claim(amount_thb=599000, trim_raw="MAX+", evidence_text=campaign_text),
        # financing price presented as a plain campaign
        ai_claim(price_type="CAMPAIGN_PRICE", amount_thb=649000, trim_raw="LONG RANGE MAX",
                 evidence_text="JAECOO 5 EV LONG RANGE MAX ราคาเมื่อใช้สินเชื่อ 649,000 บาท"),
        # MSRP wording dressed up as a campaign
        ai_claim(price_type="CAMPAIGN_PRICE"),
        # a down payment is not a vehicle price
        ai_claim(amount_thb=199000, trim_raw="ULTRA",
                 evidence_text="เงินดาวน์ 199,000 บาท"),
        ai_claim(price_type="UNKNOWN"),
        ai_claim(price_type="DEALER_PRICE"),
    ]
    _eng, provider, _tgt, outcome = run_ai(good + bad)

    assert provider.calls == 1
    got = {(c.trim_raw, c.price_type) for c in outcome.ai_claims}
    assert got == {("ULTRA", PriceType.LIST_PRICE), ("MAX+", PriceType.CAMPAIGN_PRICE),
                   ("LONG RANGE MAX", PriceType.FINANCE_PRICE)}
    assert reasons(outcome) == [
        "PRICE_TYPE_CONFLICT", "PRICE_TYPE_CONFLICT", "PRICE_TYPE_UNSUPPORTED",
        "NOT_VEHICLE_PRICE", "PRICE_TYPE_UNKNOWN", "PRICE_TYPE_NOT_ALLOWED"]
    campaign = next(c for c in outcome.ai_claims if c.price_type is PriceType.CAMPAIGN_PRICE)
    assert (campaign.effective_from, campaign.effective_to) == ("2026-09-21", "2026-09-30")
    assert campaign.reference_price_thb == 699000
    assert campaign.extraction_method == "ai_event:pee-1:price-event-v1"


def test_claims_are_evidence_only_no_invented_identity() -> None:
    _eng, _p, _t, outcome = run_ai([ai_claim(
        trim_id="jaecoo.jaecoo_5_ev.j5.trim.ultra_bev", campaign_id="camp-1",
        option_id="opt-1")])
    claim, = outcome.ai_claims
    assert claim.trim_id is None and claim.trim_candidates == ()
    assert claim.campaign_hint == "" and claim.option_hint == ""
    detail, = outcome.details
    assert set(detail.ignored_fields) == {"trim_id", "campaign_id", "option_id"}
    assert detail.conditions is None                       # UNKNOWN, not []
    # The recorded location points at the exact quote inside the sent excerpt.
    sent = price_segments(visible_text(fetched(page(MIXED_BODY), _t)), 140)
    assert sent[detail.evidence_segment][detail.evidence_start:detail.evidence_end] \
        == claim.evidence_text


def test_ambiguous_trim_names_go_to_review() -> None:
    body = ("<p>JAECOO 5 EV MAX+ ราคาขายปลีกแนะนำ 699,000 บาท</p>"
            "<p>JAECOO 5 EV LONG RANGE ราคาขายปลีกแนะนำ 629,000 บาท</p>"
            "<p>JAECOO 5 EV LONG RANGE MAX ราคาขายปลีกแนะนำ 679,000 บาท</p>")
    _e, _p, _t, outcome = run_ai([
        # wrong grade: "MAX" is not "MAX+"
        ai_claim(trim_raw="MAX", amount_thb=699000,
                 evidence_text="JAECOO 5 EV MAX+ ราคาขายปลีกแนะนำ 699,000 บาท"),
        # "LONG RANGE" is a prefix of "LONG RANGE MAX" in the same batch
        ai_claim(trim_raw="LONG RANGE", amount_thb=629000,
                 evidence_text="JAECOO 5 EV LONG RANGE ราคาขายปลีกแนะนำ 629,000 บาท"),
        ai_claim(trim_raw="LONG RANGE MAX", amount_thb=679000,
                 evidence_text="JAECOO 5 EV LONG RANGE MAX ราคาขายปลีกแนะนำ 679,000 บาท"),
        # grade not stated at all
        ai_claim(trim_raw=None, amount_thb=699000,
                 evidence_text="JAECOO 5 EV MAX+ ราคาขายปลีกแนะนำ 699,000 บาท"),
    ], body=body)

    assert [c.trim_raw for c in outcome.ai_claims] == ["LONG RANGE MAX"]
    assert reasons(outcome) == [
        "TRIM_NOT_IN_EVIDENCE", "TRIM_UNKNOWN", "TRIM_AMBIGUOUS"]


def test_p4_ambiguity_is_reused_for_bare_grade_names() -> None:
    catalog = Catalog.load(DATA_DIR, DEFAULT_YEAR)
    body = "<p>JAECOO 5 EV MAX ราคาขายปลีกแนะนำ 659,000 บาท</p>"
    _e, _p, _t, outcome = run_ai([ai_claim(
        trim_raw="MAX", amount_thb=659000,
        evidence_text="JAECOO 5 EV MAX ราคาขายปลีกแนะนำ 659,000 บาท")],
        body=body, catalog=catalog)
    assert outcome.ai_claims == ()
    assert reasons(outcome) == ["TRIM_AMBIGUOUS"]
    assert "P4" in outcome.review[0].detail


def test_missing_dates_stay_unknown_and_invented_dates_are_rejected() -> None:
    body = ("<p>JAECOO 5 EV MAX+ ราคาพิเศษ 599,000 บาท (จากราคา 699,000 บาท) "
            "ถึงวันที่ 30 กันยายน</p>")
    quote = "JAECOO 5 EV MAX+ ราคาพิเศษ 599,000 บาท (จากราคา 699,000 บาท)"
    common = dict(price_type="CAMPAIGN_PRICE", amount_thb=599000, trim_raw="MAX+",
                  reference_price_thb=699000, evidence_text=quote)
    _e, _p, _t, outcome = run_ai([
        ai_claim(**common),                                           # silent -> null
        ai_claim(**common, effective_to="2026-09-30"),                # year invented
        ai_claim(**common, effective_from="2026-09-30", effective_to="2026-09-01"),
    ], body=body)

    claim, = outcome.ai_claims
    assert claim.effective_from is None and claim.effective_to is None
    assert reasons(outcome) == ["DATE_NOT_IN_EVIDENCE", "DATE_NOT_IN_EVIDENCE"]


def test_date_order_and_literal_date_formats() -> None:
    assert extract_dates("21–30 สิงหาคม 2569") == {"2026-08-21", "2026-08-30"}
    assert extract_dates("21-30 August 2026") == {"2026-08-21", "2026-08-30"}
    assert extract_dates("valid until 30 กันยายน") == set()          # no year: not a date
    assert extract_dates("30/09/2569 and 2026-10-01") == {"2026-09-30", "2026-10-01"}
    body = "<p>JAECOO 5 EV MAX+ ราคาพิเศษ 599,000 บาท 30 กันยายน 2569 – 1 กันยายน 2569</p>"
    _e, _p, _t, outcome = run_ai([ai_claim(
        price_type="CAMPAIGN_PRICE", amount_thb=599000, trim_raw="MAX+",
        effective_from="2026-09-30", effective_to="2026-09-01",
        evidence_text="JAECOO 5 EV MAX+ ราคาพิเศษ 599,000 บาท")], body=body)
    assert reasons(outcome) == ["DATE_ORDER"]


def test_hallucinated_evidence_is_rejected() -> None:
    _e, _p, _t, outcome = run_ai([
        ai_claim(evidence_text="JAECOO 5 EV ULTRA ราคาขายปลีกแนะนำ 599,000 บาท"),
        ai_claim(amount_thb=589000),                       # amount not in the quote
        ai_claim(price_type="CAMPAIGN_PRICE", reference_price_thb=809000,
                 evidence_text="JAECOO 5 EV ULTRA ราคาพิเศษ 789,000 บาท"),
        ai_claim(conditions=["free charger for life"]),    # invented condition
        ai_claim(brand_raw="BYD", model_raw="SEAL"),       # wording not on the page
        ai_claim(evidence_text="x" * 201),
        "not an object",
    ])
    assert outcome.ai_claims == ()
    assert reasons(outcome) == [
        "EVIDENCE_NOT_FOUND", "AMOUNT_NOT_IN_EVIDENCE", "EVIDENCE_NOT_FOUND",
        "CONDITION_NOT_IN_EVIDENCE", "MODEL_UNKNOWN", "EVIDENCE_TOO_LONG",
        "MALFORMED_CLAIM"]
    assert outcome.status is EventStatus.AI_EXTRACTED       # processed, sent to review


# ------------------------------------------------------------------------ cache

def test_cache_hit_avoids_a_second_call_and_survives_a_baseline_reset() -> None:
    state = EventState()
    provider = FakeProvider([ai_claim()])
    eng = engine(provider, state=state)
    tgt = target()

    first = eng.process(tgt, fetched(page(MIXED_BODY, "a"), tgt))
    assert provider.calls == 1 and not first.cache_hit
    state.data["fingerprints"] = {}                        # forget the baseline
    second = eng.process(tgt, fetched(page(MIXED_BODY, "b"), tgt))

    assert provider.calls == 1 and second.cache_hit and second.ai_calls == 0
    assert [c.trim_raw for c in second.ai_claims] == ["ULTRA"]
    assert second.details[0].cache_hit is True
    # Validation is re-run against the new document, never trusted from cache.
    assert second.ai_claims[0].document_id != first.ai_claims[0].document_id


def test_unchanged_page_reemits_cached_ai_claims_without_a_call() -> None:
    provider = FakeProvider([ai_claim()])
    eng = engine(provider)
    tgt = target()
    eng.process(tgt, fetched(page(MIXED_BODY, "a"), tgt))
    again = eng.process(tgt, fetched(page(MIXED_BODY, "b"), tgt))

    assert again.status is EventStatus.UNCHANGED and provider.calls == 1
    assert [c.trim_raw for c in again.ai_claims] == ["ULTRA"]


def test_cache_key_includes_extractor_and_prompt_version() -> None:
    state = EventState()
    tgt = target()
    html = page(MIXED_BODY)
    provider = FakeProvider([ai_claim()])
    engine(provider, state=state).process(tgt, fetched(html, tgt))
    state.data["fingerprints"] = {}

    engine(provider, state=state, extractor_version="pee-2").process(
        tgt, fetched(html, tgt))
    assert provider.calls == 2
    state.data["fingerprints"] = {}
    engine(provider, state=state, extractor_version="pee-2").process(
        tgt, fetched(html, tgt))
    assert provider.calls == 2                              # pee-2 now cached


# ------------------------------------------------------------ limits and retries

def test_token_budget_exhaustion_blocks_calls_and_keeps_the_change_pending() -> None:
    probe = engine(FakeProvider([ai_claim()]))
    tgt = target()
    html1, html2 = page(MIXED_BODY), page(MIXED_BODY.replace("789,000", "779,000"))
    first_request = probe._request(tgt, probe._payload(
        tgt, price_segments(visible_text(fetched(html1, tgt)), 140), "full"))
    reserve = probe.estimate_tokens(first_request.system + first_request.user) + 500

    state = EventState()
    provider = FakeProvider([ai_claim()], input_tokens=reserve - 500, output_tokens=100)
    eng = engine(provider, state=state, daily_token_budget=reserve * 2 - 500)

    assert eng.process(tgt, fetched(html1, tgt)).status is EventStatus.AI_EXTRACTED
    exhausted = eng.process(tgt, fetched(html2, tgt))

    assert provider.calls == 1                              # second call never made
    assert exhausted.status is EventStatus.REVIEW
    assert reasons(exhausted) == ["TOKEN_BUDGET_EXHAUSTED"]
    # The old baseline is kept, so the change is retried, not lost.
    assert eng.process(tgt, fetched(html1, tgt)).status is EventStatus.UNCHANGED
    # Next Thailand business day the budget has reset.
    tomorrow = engine(provider, state=state, daily_token_budget=reserve * 2 - 500,
                      clock=lambda: NOW + timedelta(days=1))
    assert tomorrow.process(tgt, fetched(html2, tgt)).status is EventStatus.AI_EXTRACTED
    assert provider.calls == 2


def test_budgets_are_per_source_and_call_capped() -> None:
    tgt = target()
    provider = FakeProvider([ai_claim()])
    low = engine(provider, source_token_budgets={SOURCE: 10})
    assert reasons(low.process(tgt, fetched(page(MIXED_BODY), tgt))) == [
        "TOKEN_BUDGET_EXHAUSTED"]
    capped = engine(provider, source_call_budgets={SOURCE: 1})
    capped.process(tgt, fetched(page(MIXED_BODY), tgt))
    assert reasons(capped.process(
        tgt, fetched(page(MIXED_BODY.replace("789,000", "769,000")), tgt))) == [
        "TOKEN_BUDGET_EXHAUSTED"]
    assert provider.calls == 1


def test_input_token_limit_is_enforced_before_any_call() -> None:
    provider = FakeProvider([ai_claim()])
    tgt = target()
    outcome = engine(provider, max_input_tokens=50).process(
        tgt, fetched(page(MIXED_BODY), tgt))
    assert provider.calls == 0 and outcome.status is EventStatus.REVIEW
    assert reasons(outcome) == ["TOKEN_LIMIT_EXCEEDED"]


def test_retries_are_bounded() -> None:
    tgt = target()
    flaky = FakeProvider(LLMProviderError("503", retryable=True))
    out = engine(flaky, max_retries=2).process(tgt, fetched(page(MIXED_BODY), tgt))
    assert flaky.calls == 3 and reasons(out) == ["PROVIDER_FAILED"]
    assert out.status is EventStatus.REVIEW

    fatal = FakeProvider(LLMProviderError("401", retryable=False))
    engine(fatal, max_retries=2).process(tgt, fetched(page(MIXED_BODY), tgt))
    assert fatal.calls == 1

    garbled = FakeProvider("sorry, no JSON here")
    out = engine(garbled, max_retries=1).process(tgt, fetched(page(MIXED_BODY), tgt))
    assert garbled.calls == 2 and reasons(out) == ["MALFORMED_OUTPUT"]

    recovers = FakeProvider("```json\nnot json\n```", [ai_claim()])
    out = engine(recovers, max_retries=1).process(tgt, fetched(page(MIXED_BODY), tgt))
    assert recovers.calls == 2 and out.status is EventStatus.AI_EXTRACTED
    assert [c.trim_raw for c in out.ai_claims] == ["ULTRA"]


def test_no_provider_means_review_not_a_crash() -> None:
    tgt = target()
    out = engine(None).process(tgt, fetched(page(MIXED_BODY), tgt))
    assert out.status is EventStatus.REVIEW and reasons(out) == ["AI_UNAVAILABLE"]
    register_provider("fake-reg", lambda: FakeProvider([ai_claim()]))
    try:
        assert resolve_provider("fake-reg") is not None
        assert resolve_provider("nope") is None
        out = PriceEventEngine(PriceEventConfig(enabled=True, provider="fake-reg"),
                               clock=lambda: NOW).process(tgt, fetched(page(MIXED_BODY), tgt))
        assert out.status is EventStatus.AI_EXTRACTED
    finally:
        unregister_provider("fake-reg")


def test_prompt_is_token_lean_and_sends_only_price_excerpts() -> None:
    provider = FakeProvider([ai_claim()])
    tgt = target()
    engine(provider).process(tgt, fetched(page(MIXED_BODY, "NAVNOISE"), tgt))
    sent = provider.requests[0].user
    assert "NAVNOISE" not in sent
    assert sent.count("Lorem") <= 4                  # of ~16 on the page
    assert "[S0]" in sent and "789,000" in sent
    assert len(sent) < 1_500


# ------------------------------------------------------- persistence / P4 / P5

def test_state_round_trips_and_corruption_fails_closed(tmp_path) -> None:
    path = tmp_path / "event_state.json"
    provider = FakeProvider([ai_claim()])
    tgt = target()
    engine(provider, state=EventState(path)).process(tgt, fetched(page(MIXED_BODY), tgt))

    reloaded = EventState(path)
    assert reloaded.baseline(tgt.id) is not None and reloaded.data["cache"]
    assert reloaded.usage(SOURCE, "2026-10-12")[1] == 1
    again = engine(provider, state=reloaded).process(
        tgt, fetched(page(MIXED_BODY, "other"), tgt))
    assert again.status is EventStatus.UNCHANGED and provider.calls == 1

    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(EventStateError):
        EventState(path)


def test_ai_claims_flow_through_p4_and_p5_unchanged() -> None:
    catalog = Catalog.load(DATA_DIR, DEFAULT_YEAR)
    body = ("<p>JAECOO 5 EV MAX+ ราคาขายปลีกแนะนำ 699,000 บาท</p>"
            "<p>JAECOO 5 EV MAX+ ราคาพิเศษ 599,000 บาท (จากราคา 699,000 บาท)</p>")
    claims = [
        ai_claim(trim_raw="MAX+", amount_thb=699000,
                 evidence_text="JAECOO 5 EV MAX+ ราคาขายปลีกแนะนำ 699,000 บาท"),
        ai_claim(price_type="CAMPAIGN_PRICE", trim_raw="MAX+", amount_thb=599000,
                 reference_price_thb=699000,
                 evidence_text="JAECOO 5 EV MAX+ ราคาพิเศษ 599,000 บาท (จากราคา 699,000 บาท)"),
    ]
    _e, _p, tgt, outcome = run_ai(claims, body=body, catalog=catalog)
    assert len(outcome.ai_claims) == 2 and not outcome.review
    assert {d.p4_state for d in outcome.details} == {"EXACT"}

    document = fetched(page(body), tgt).document
    ledger = PriceLedger(2026)
    decisions = {}
    for claim in outcome.ai_claims:
        match = match_trim_diagnostic(catalog, claim)
        assert match.state is TrimMatchState.EXACT
        decisions[claim.price_type] = reconcile_one(ReconcileObservation(
            claim=claim, match=match, target_id=tgt.id,
            target_role=TargetRole.PRICE_LIST, document=document), ledger)

    # LIST: a normal P5 candidate.  CAMPAIGN: P5 still demands explicit
    # campaign + option scope; the engine supplied none and P5 did not guess.
    assert decisions[PriceType.LIST_PRICE].disposition is ReconcileDisposition.SAFE_CANDIDATE
    campaign = decisions[PriceType.CAMPAIGN_PRICE]
    assert campaign.disposition is ReconcileDisposition.REVIEW
    assert ReconcileReason.CAMPAIGN_SCOPE_REQUIRED in campaign.reasons
    assert ledger.records == []                                  # nothing written


# ------------------------------------------------------------------- CLI wiring

class _FakeAdapter:
    def __init__(self, html: str) -> None:
        self.html = html

    def fetch(self, tgt, *, previous=None, refetch_not_modified=False, **_kw):
        return fetched(self.html, tgt)


def _run_cli(monkeypatch, tmp_path, html: str, env: dict, name: str) -> dict:
    from tools import pricefetch_targets as cli

    monkeypatch.setattr(cli, "adapter_for", lambda registry, tgt, **kw: _FakeAdapter(html))
    monkeypatch.setattr(cli, "_robots_allowed", lambda url, cache: True)
    for key in [k for k in os.environ if k.startswith("TDR_PRICE_EVENT")]:
        monkeypatch.delenv(key)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    out = tmp_path / f"{name}.json"
    assert cli.main([
        "--source", SOURCE, "--target", "jaecoo_th_home_price_cards",
        "--extract-prices", "--out", str(out),
        "--event-state", str(tmp_path / f"{name}-state.json"),
    ]) == 0
    return json.loads(out.read_text(encoding="utf-8"))


def test_cli_hook_is_flag_gated_and_adds_validated_ai_claims(monkeypatch, tmp_path,
                                                             capsys) -> None:
    # A grade P3's homepage-card rules do not know: rules find nothing, the
    # amount is uncovered, so the AI fallback is the only way to read it.
    html = page("<p>JAECOO 5 EV LONG RANGE MAX ราคาขายปลีกแนะนำ 679,000 บาท</p>")
    reply = [ai_claim(trim_raw="LONG RANGE MAX", amount_thb=679000,
                      evidence_text="JAECOO 5 EV LONG RANGE MAX ราคาขายปลีกแนะนำ 679,000 บาท")]
    provider = FakeProvider(reply)
    register_provider("cli-fake", lambda: provider)
    try:
        off = _run_cli(monkeypatch, tmp_path, html, {}, "off")
        assert provider.calls == 0
        assert "price_event" not in off["results"][0]
        assert off["results"][0]["claims"] == []

        on = _run_cli(monkeypatch, tmp_path, html, {
            "TDR_PRICE_EVENT_ENGINE": "1", "TDR_PRICE_EVENT_PROVIDER": "cli-fake"}, "on")
    finally:
        unregister_provider("cli-fake")

    row = on["results"][0]
    assert provider.calls == 1
    claim, = row["claims"]
    assert (claim["trim_raw"], claim["amount_thb"], claim["price_type"]) == (
        "LONG RANGE MAX", 679000, "LIST_PRICE")
    assert claim["extraction_method"].startswith("ai_event:")
    assert claim["campaign_hint"] == "" and "trim_id" not in claim
    assert row["price_event"]["status"] == "AI_EXTRACTED"
    assert (tmp_path / "on-state.json").exists()
    capsys.readouterr()
