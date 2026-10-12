"""PEE2-F1 / PEE2-F2: one price fact must bind model, trim, amount and type.

Pure validator tests (no engine, no network).  Each row is a quoted fact in an
excerpt plus the claim a model might make about it.  ACCEPT rows are legitimate
prices that must keep working; REJECT rows are the failure classes the shadow
evaluation found and must fail closed.
"""

from __future__ import annotations

import pytest

from vehreg.price_event_validate import (
    EventReviewReason as R,
    normalize_text,
    validate_ai_claims,
)
from vehreg.price_sources import TargetRole

J5 = "JAECOO 5 EV"
ANY_PAGE = TargetRole.CURRENT_MODEL_PAGE
PRICE_LIST = TargetRole.PRICE_LIST


def run(segment: str, claim: dict, role: TargetRole = ANY_PAGE):
    segment = normalize_text(segment)
    base = {"price_type": "LIST_PRICE", "brand_raw": "JAECOO", "model_raw": J5,
            "effective_from": None, "effective_to": None, "reference_price_thb": None,
            "conditions": None, "evidence_segment": 0}
    base.update(claim)
    return validate_ai_claims(
        [base], segments=[segment], document_text=segment, document_id="sha256:" + "a" * 64,
        source_id="official_jaecoo_th", evidence_hash="h", extraction_method="m",
        target_role=role)


def c(trim: str, amount: int, quote: str, **extra) -> dict:
    return {"trim_raw": trim, "amount_thb": amount, "evidence_text": quote, **extra}


MSRP_Q = f"{J5} MAX+ ราคาขายปลีกแนะนำ 699,000 บาท"
ROW_Q = f"{MSRP_Q} {J5} ULTRA ราคาขายปลีกแนะนำ 789,000 บาท"
SHARED_Q = f"{J5} MAX+ ราคาขายปลีกแนะนำ 699,000 บาท ULTRA ราคาขายปลีกแนะนำ 789,000 บาท"
CHAIN_Q = f"{J5} MAX+ ราคาขายปลีกแนะนำ 699,000 บาท (ราคาพิเศษ 579,000 บาท)"
FROM_Q = f"{J5} MAX+ Special Price THB 599,000 (from THB 699,000)"
CARD_Q = f"{J5} ULTRA NEW {J5} Estimated Price THB 809,000"

ACCEPT = [
    ("thai msrp wording", MSRP_Q, c("MAX+", 699000, MSRP_Q), ANY_PAGE),
    ("english recommended retail", f"{J5} MAX+ Recommended Retail Price THB 699,000",
     c("MAX+", 699000, f"{J5} MAX+ Recommended Retail Price THB 699,000"), ANY_PAGE),
    ("msrp abbreviation", f"{J5} MAX+ MSRP: THB 699,000",
     c("MAX+", 699000, f"{J5} MAX+ MSRP: THB 699,000"), ANY_PAGE),
    ("campaign wording", f"{J5} MAX+ ราคาพิเศษ 599,000 บาท",
     c("MAX+", 599000, f"{J5} MAX+ ราคาพิเศษ 599,000 บาท", price_type="CAMPAIGN_PRICE"),
     ANY_PAGE),
    ("finance wording", f"{J5} MAX+ ราคาเมื่อใช้สินเชื่อ 649,000 บาท",
     c("MAX+", 649000, f"{J5} MAX+ ราคาเมื่อใช้สินเชื่อ 649,000 บาท",
       price_type="FINANCE_PRICE"), ANY_PAGE),
    ("estimated wording", f"{J5} ULTRA ราคาคาดการณ์ 809,000 บาท",
     c("ULTRA", 809000, f"{J5} ULTRA ราคาคาดการณ์ 809,000 บาท",
       price_type="ESTIMATED_PRICE"), ANY_PAGE),
    ("introductory wording", f"{J5} ULTRA ราคาเปิดตัว 799,000 บาท",
     c("ULTRA", 799000, f"{J5} ULTRA ราคาเปิดตัว 799,000 บาท",
       price_type="INTRODUCTORY_PRICE"), ANY_PAGE),
    ("bare Price on a registered price-list card (mirrors P3)",
     f"{J5} MAX+ Price THB 699,000", c("MAX+", 699000, f"{J5} MAX+ Price THB 699,000"),
     PRICE_LIST),
    ("list price then promo in one row, promo claimed with its reference", CHAIN_Q,
     c("MAX+", 579000, CHAIN_Q, price_type="CAMPAIGN_PRICE", reference_price_thb=699000),
     ANY_PAGE),
    ("campaign with 'from' reference", FROM_Q,
     c("MAX+", 599000, FROM_Q, price_type="CAMPAIGN_PRICE", reference_price_thb=699000),
     ANY_PAGE),
    ("card that repeats the same model", CARD_Q,
     c("ULTRA", 809000, CARD_Q, price_type="ESTIMATED_PRICE"), PRICE_LIST),
    ("multi-word trim", f"{J5} LONG RANGE MAX ราคาขายปลีกแนะนำ 679,000 บาท",
     c("LONG RANGE MAX", 679000, f"{J5} LONG RANGE MAX ราคาขายปลีกแนะนำ 679,000 บาท"),
     ANY_PAGE),
    ("harmless text after the price", f"{MSRP_Q} รวมภาษีมูลค่าเพิ่ม ดูรายละเอียด",
     c("MAX+", 699000, MSRP_Q), ANY_PAGE),
    ("each item of a row, model repeated per fact: first", ROW_Q,
     c("MAX+", 699000, ROW_Q), ANY_PAGE),
    ("each item of a row, model repeated per fact: second", ROW_Q,
     c("ULTRA", 789000, ROW_Q), ANY_PAGE),
    ("a neighbour's finance wording does not leak into an MSRP",
     f"{MSRP_Q} {J5} ULTRA ราคาเมื่อใช้สินเชื่อ 649,000 บาท เมื่อจัดไฟแนนซ์",
     c("MAX+", 699000, MSRP_Q), ANY_PAGE),
    ("a neighbour's promo label in front of the next amount does not leak",
     f"{MSRP_Q} ราคาพิเศษ 599,000 บาท", c("MAX+", 699000, MSRP_Q), ANY_PAGE),
]

REJECT = [
    # -- F2: attribution -------------------------------------------------------------
    ("swapped: trim MAX+ with the ULTRA amount", ROW_Q, c("MAX+", 789000, ROW_Q), R.FACT_NOT_BOUND),
    ("swapped: trim ULTRA with the MAX+ amount", ROW_Q, c("ULTRA", 699000, ROW_Q), R.FACT_NOT_BOUND),
    ("another model's price under this model", "OMODA C5 EV MAX+ ราคาขายปลีกแนะนำ 709,000 บาท "
     + J5 + " ULTRA ราคาขายปลีกแนะนำ 809,000 บาท",
     c("MAX+", 709000, "OMODA C5 EV MAX+ ราคาขายปลีกแนะนำ 709,000 บาท"), R.FACT_NOT_BOUND),
    ("same trim name on two models", f"{MSRP_Q} OMODA C5 EV MAX+ ราคาขายปลีกแนะนำ 709,000 บาท",
     c("MAX+", 709000, f"{MSRP_Q} OMODA C5 EV MAX+ ราคาขายปลีกแนะนำ 709,000 บาท"),
     R.FACT_NOT_BOUND),
    ("model named once for several prices: second trim", SHARED_Q,
     c("ULTRA", 789000, SHARED_Q), R.FACT_NOT_BOUND),
    ("a reference amount claimed as its own price", FROM_Q,
     c("MAX+", 699000, FROM_Q), R.FACT_NOT_BOUND),
    ("trim only appears before an earlier price", f"{J5} ULTRA ราคาขายปลีกแนะนำ 789,000 บาท MAX+ 699,000 บาท",
     c("ULTRA", 699000, f"{J5} ULTRA ราคาขายปลีกแนะนำ 789,000 บาท MAX+ 699,000 บาท"),
     R.FACT_NOT_BOUND),
    ("stray words in front of the model", f"Test drive {MSRP_Q}",
     c("MAX+", 699000, f"Test drive {MSRP_Q}"), R.FACT_NOT_BOUND),
    # -- F1: price type ----------------------------------------------------------------
    ("promo wording after the amount, claimed LIST", f"{MSRP_Q.replace('699', '599')} (โปรโมชัน)",
     c("MAX+", 599000, MSRP_Q.replace("699", "599")), R.PRICE_TYPE_CONFLICT),
    ("promo wording after the amount (english)",
     f"{J5} MAX+ Recommended Retail Price THB 599,000 promotion",
     c("MAX+", 599000, f"{J5} MAX+ Recommended Retail Price THB 599,000"), R.PRICE_TYPE_CONFLICT),
    ("restricted audience (english)", f"{J5} MAX+ MSRP THB 599,000 for students and teachers",
     c("MAX+", 599000, f"{J5} MAX+ MSRP THB 599,000"), R.PRICE_TYPE_UNSUPPORTED),
    ("restricted audience (thai)", f"{MSRP_Q.replace('699', '599')} สำหรับลูกค้าเดิม",
     c("MAX+", 599000, MSRP_Q.replace("699", "599")), R.PRICE_TYPE_UNSUPPORTED),
    ("restricted audience after unrecognised words",
     f"{MSRP_Q.replace('699', '599')} (ผ่านบริษัทลิสซิ่ง) สำหรับลูกค้าเดิม",
     c("MAX+", 599000, MSRP_Q.replace("699", "599")), R.PRICE_TYPE_UNSUPPORTED),
    ("eco sticker", f"{J5} MAX+ ราคาป้ายอีโคสติกเกอร์ 689,000 บาท",
     c("MAX+", 689000, f"{J5} MAX+ ราคาป้ายอีโคสติกเกอร์ 689,000 บาท"), R.PRICE_TYPE_CONFLICT),
    ("dealer price (thai)", f"{J5} MAX+ ราคาดีลเลอร์ 650,000 บาท",
     c("MAX+", 650000, f"{J5} MAX+ ราคาดีลเลอร์ 650,000 บาท"), R.PRICE_TYPE_CONFLICT),
    ("dealer price (english)", f"{J5} MAX+ dealer price THB 650,000",
     c("MAX+", 650000, f"{J5} MAX+ dealer price THB 650,000"), R.PRICE_TYPE_CONFLICT),
    ("previous price", f"{J5} MAX+ ราคาเดิม 699,000 บาท",
     c("MAX+", 699000, f"{J5} MAX+ ราคาเดิม 699,000 บาท"), R.PRICE_TYPE_UNSUPPORTED),
    ("bare thai 'ราคา' is not MSRP evidence", f"{J5} MAX+ ราคา 699,000 บาท",
     c("MAX+", 699000, f"{J5} MAX+ ราคา 699,000 บาท"), R.PRICE_TYPE_UNSUPPORTED),
    ("bare english 'Price' off a price list", f"{J5} MAX+ Price THB 699,000",
     c("MAX+", 699000, f"{J5} MAX+ Price THB 699,000"), R.PRICE_TYPE_UNSUPPORTED),
    ("unrecognised word between trim and amount", f"{J5} MAX+ ราคาขายปลีกแนะนำ รุ่นสะสม 699,000 บาท",
     c("MAX+", 699000, f"{J5} MAX+ ราคาขายปลีกแนะนำ รุ่นสะสม 699,000 บาท"),
     R.PRICE_TYPE_UNSUPPORTED),
    ("'starting from' price", f"{J5} MAX+ ราคาเริ่มต้น 599,000 บาท",
     c("MAX+", 599000, f"{J5} MAX+ ราคาเริ่มต้น 599,000 บาท"), R.PRICE_TYPE_UNSUPPORTED),
    ("campaign wording claimed as LIST", f"{J5} MAX+ ราคาพิเศษ 599,000 บาท",
     c("MAX+", 599000, f"{J5} MAX+ ราคาพิเศษ 599,000 บาท"), R.PRICE_TYPE_CONFLICT),
    ("finance wording after the amount, claimed LIST",
     f"{MSRP_Q.replace('699', '599')} เมื่อจัดไฟแนนซ์",
     c("MAX+", 599000, MSRP_Q.replace("699", "599")), R.PRICE_TYPE_CONFLICT),
    ("conditional wording after the amount",
     f"{MSRP_Q.replace('699', '599')} เมื่อเทิร์นรถเก่า",
     c("MAX+", 599000, MSRP_Q.replace("699", "599")), R.PRICE_TYPE_UNSUPPORTED),
    ("estimated wording claimed as LIST", f"{J5} ULTRA ราคาคาดการณ์ 809,000 บาท",
     c("ULTRA", 809000, f"{J5} ULTRA ราคาคาดการณ์ 809,000 บาท"), R.PRICE_TYPE_CONFLICT),
]


@pytest.mark.parametrize("name,segment,claim,role", ACCEPT, ids=[a[0] for a in ACCEPT])
def test_legitimate_facts_are_still_accepted(name, segment, claim, role) -> None:
    result = run(segment, claim, role)
    assert result.accepted, [(r.reason.value, r.detail) for r in result.review]
    assert result.review == ()


@pytest.mark.parametrize("name,segment,claim,reason", REJECT, ids=[r[0] for r in REJECT])
def test_unbound_or_unproven_facts_fail_closed(name, segment, claim, reason) -> None:
    result = run(segment, claim)
    assert result.accepted == (), name
    assert [r.reason for r in result.review] == [reason], (
        [(r.reason.value, r.detail) for r in result.review])


def test_rejections_keep_the_raw_proposal_for_review_and_never_assign_ids() -> None:
    result = run(ROW_Q, c("MAX+", 789000, ROW_Q, trim_id="x.y.z", campaign_id="c1"))
    item, = result.review
    assert item.proposal["trim_id"] == "x.y.z"          # shown to the reviewer as-is
    assert result.accepted_raw == ()                    # but never kept as a validated proposal


def test_a_correct_pair_is_bound_even_when_the_row_also_holds_a_wrong_one() -> None:
    both = [
        {"price_type": "LIST_PRICE", "brand_raw": "JAECOO", "model_raw": J5,
         "effective_from": None, "effective_to": None, "reference_price_thb": None,
         "conditions": None, "evidence_segment": 0, **c(trim, amount, ROW_Q)}
        for trim, amount in (("MAX+", 699000), ("ULTRA", 699000), ("MAX+", 789000))]
    seg = normalize_text(ROW_Q)
    result = validate_ai_claims(
        both, segments=[seg], document_text=seg, document_id="sha256:" + "a" * 64,
        source_id="s", evidence_hash="h", extraction_method="m", target_role=ANY_PAGE)
    assert [(cl.trim_raw, cl.amount_thb) for cl, _ in result.accepted] == [("MAX+", 699000)]
    assert [r.reason for r in result.review] == [R.FACT_NOT_BOUND, R.FACT_NOT_BOUND]
