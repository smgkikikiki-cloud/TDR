"""P3 deterministic OEM price extraction and semantic classification.

The fetch layer in :mod:`vehreg.price_fetch` creates immutable page evidence.
This module reads that evidence and emits :class:`vehreg.pricefeed.PriceClaim`
objects.  A claim is still only evidence: nothing here matches a canonical trim,
reconciles against PriceLedger, or publishes a price.

P3 deliberately keeps the first pilot narrow.  OMODA & JAECOO Thailand has a
small set of first-party page shapes that exercise the semantics we care about:

* homepage price cards: LIST vs ESTIMATED;
* buyer-guide tables: LIST plus an adjacent promotional figure;
* promotion details: CAMPAIGN plus its reference price, with explicit campaign
  windows only when the page literally states them.

No age-based expiry is manufactured here.  No end date in the document means
``effective_to=None``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re
from typing import Iterable, Optional

from .price_fetch import FetchResult, parse_page_metadata
from .price_sources import SourceTarget, TargetRole
from .pricefeed import PriceClaim, content_id
from .pricing import PriceType


class ExtractionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    claims: tuple[PriceClaim, ...] = ()
    warnings: tuple[str, ...] = ()


_AMOUNT = r"(\d{1,3}(?:,\d{3})+)"
_J5_TRIM = r"(LONG\s+RANGE\s+DYNAMIC|LONG\s+RANGE\s+MAX|MAX\+|ULTRA)"
_J5_MODEL_HINT = "jaecoo.jaecoo_5_ev"
_THAI_MONTHS = {
    "มกราคม": 1,
    "กุมภาพันธ์": 2,
    "มีนาคม": 3,
    "เมษายน": 4,
    "พฤษภาคม": 5,
    "มิถุนายน": 6,
    "กรกฎาคม": 7,
    "สิงหาคม": 8,
    "กันยายน": 9,
    "ตุลาคม": 10,
    "พฤศจิกายน": 11,
    "ธันวาคม": 12,
}
_EN_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def _amount(raw: str) -> int:
    return int(raw.replace(",", ""))


def _clean_trim(raw: str) -> str:
    return " ".join(raw.upper().split())


def _visible_text(result: FetchResult) -> str:
    if not result.text:
        return ""
    return parse_page_metadata(result.text).visible_text


def _claim(*, document_id: str, source_id: str, trim_raw: str,
           amount_thb: int, price_type: PriceType,
           evidence_text: str, effective_from: Optional[str] = None,
           effective_to: Optional[str] = None,
           reference_price_thb: Optional[int] = None) -> PriceClaim:
    semantic = (
        f"{document_id}|JAECOO|JAECOO 5 EV|{_clean_trim(trim_raw)}|"
        f"{amount_thb}|{price_type.value}|{effective_from or ''}|"
        f"{effective_to or ''}|{reference_price_thb or ''}"
    )
    claim = PriceClaim(
        claim_id=content_id(semantic)[7:23],
        document_id=document_id,
        source_id=source_id,
        brand_raw="JAECOO",
        model_raw="JAECOO 5 EV",
        trim_raw=_clean_trim(trim_raw),
        amount_thb=amount_thb,
        price_type=price_type,
        evidence_text=" ".join(evidence_text.split())[:200],
        extraction_method="oem_rule:jaecoo_p3",
        effective_from=effective_from,
        effective_to=effective_to,
        reference_price_thb=reference_price_thb,
    )
    problems = claim.validate()
    if problems:
        raise ExtractionError("; ".join(problems))
    return claim


def _dedupe(claims: Iterable[PriceClaim]) -> tuple[PriceClaim, ...]:
    by_key: dict[tuple, PriceClaim] = {}
    for claim in claims:
        key = (
            claim.trim_raw,
            claim.amount_thb,
            claim.price_type,
            claim.effective_from,
            claim.effective_to,
            claim.reference_price_thb,
        )
        by_key.setdefault(key, claim)
    return tuple(sorted(
        by_key.values(),
        key=lambda c: (c.trim_raw, c.price_type.value, c.amount_thb,
                       c.effective_from or "", c.effective_to or ""),
    ))


def _explicit_window(text: str) -> tuple[Optional[str], Optional[str]]:
    """Return a literal same-month campaign window when the page states one.

    P3 intentionally understands only unambiguous ranges such as
    ``21–30 สิงหาคม 2569`` / ``21–30 August 2026``.  Unknown wording returns
    ``(None, None)`` rather than inventing dates.
    """
    thai_months = "|".join(map(re.escape, _THAI_MONTHS))
    thai = re.search(
        rf"\b(\d{{1,2}})\s*[–—-]\s*(\d{{1,2}})\s+({thai_months})\s+(\d{{4}})\b",
        text,
    )
    if thai:
        start_day, end_day = int(thai.group(1)), int(thai.group(2))
        month, year = _THAI_MONTHS[thai.group(3)], int(thai.group(4))
        if year >= 2400:
            year -= 543
        try:
            return (date(year, month, start_day).isoformat(),
                    date(year, month, end_day).isoformat())
        except ValueError:
            return None, None

    months = "|".join(name.title() for name in _EN_MONTHS)
    english = re.search(
        rf"\b(\d{{1,2}})\s*[–—-]\s*(\d{{1,2}})\s+({months})\s+(\d{{4}})\b",
        text,
        flags=re.I,
    )
    if english:
        start_day, end_day = int(english.group(1)), int(english.group(2))
        month = _EN_MONTHS[english.group(3).lower()]
        year = int(english.group(4))
        try:
            return (date(year, month, start_day).isoformat(),
                    date(year, month, end_day).isoformat())
        except ValueError:
            return None, None
    return None, None


def _extract_homepage(result: FetchResult, text: str) -> list[PriceClaim]:
    """Read JAECOO 5 price cards from the multi-model Thailand homepage."""
    claims: list[PriceClaim] = []
    # Bound each card by the next J5 trim card or a known neighbouring model.
    card_re = re.compile(
        rf"JAECOO\s+5\s+EV\s+(ULTRA|MAX\+)(?P<body>.*?)"
        rf"(?=JAECOO\s+5\s+EV\s+(?:ULTRA|MAX\+)|OMODA\s+C5|JAECOO\s+6|$)",
        flags=re.I | re.S,
    )
    for match in card_re.finditer(text):
        trim = match.group(1)
        block = match.group(0)
        estimated = re.search(
            rf"(?:ราคาคาดการณ์\s*{_AMOUNT}|Estimated\s+Price\s*(?:THB)?\s*{_AMOUNT})",
            block,
            flags=re.I,
        )
        if estimated:
            raw = estimated.group(1) or estimated.group(2)
            claims.append(_claim(
                document_id=result.document.document_id,
                source_id=result.source_id,
                trim_raw=trim,
                amount_thb=_amount(raw),
                price_type=PriceType.ESTIMATED_PRICE,
                evidence_text=estimated.group(0),
            ))
            continue
        listed = re.search(
            rf"(?:ราคาขายปลีกแนะนำ\s*{_AMOUNT}|Price\s*(?:THB\s*)?{_AMOUNT}\s*(?:THB)?)",
            block,
            flags=re.I,
        )
        if listed:
            raw = listed.group(1) or listed.group(2)
            claims.append(_claim(
                document_id=result.document.document_id,
                source_id=result.source_id,
                trim_raw=trim,
                amount_thb=_amount(raw),
                price_type=PriceType.LIST_PRICE,
                evidence_text=listed.group(0),
            ))
    return claims


def _extract_blog(result: FetchResult, text: str) -> list[PriceClaim]:
    """Read first-party J5 variant/price table rows from Thai or English guide."""
    claims: list[PriceClaim] = []
    row_re = re.compile(
        rf"{_J5_TRIM}\s*(?:\|\s*)?{_AMOUNT}"
        rf"(?:\s*\(\s*(?:โปรโมชัน|promo|Special\s+Price|ราคาพิเศษ)\s*{_AMOUNT}\s*\*?\s*\))?",
        flags=re.I,
    )
    for match in row_re.finditer(text):
        trim, list_raw, promo_raw = match.group(1), match.group(2), match.group(3)
        claims.append(_claim(
            document_id=result.document.document_id,
            source_id=result.source_id,
            trim_raw=trim,
            amount_thb=_amount(list_raw),
            price_type=PriceType.LIST_PRICE,
            evidence_text=match.group(0),
        ))
        if promo_raw:
            claims.append(_claim(
                document_id=result.document.document_id,
                source_id=result.source_id,
                trim_raw=trim,
                amount_thb=_amount(promo_raw),
                price_type=PriceType.CAMPAIGN_PRICE,
                evidence_text=match.group(0),
                reference_price_thb=_amount(list_raw),
            ))
    return claims


def _extract_promotion(result: FetchResult, text: str) -> list[PriceClaim]:
    """Read J5 campaign blocks and literal reference-price semantics."""
    claims: list[PriceClaim] = []
    start, end = _explicit_window(text)
    anchor_re = re.compile(r"JAECOO\s+5\s+EV\s+(MAX\+|ULTRA)", flags=re.I)
    anchors = list(anchor_re.finditer(text))
    for index, anchor in enumerate(anchors):
        stop = anchors[index + 1].start() if index + 1 < len(anchors) else len(text)
        block = text[anchor.start():stop]
        trim = anchor.group(1)
        thai = re.search(
            rf"ราคาพิเศษ\s*{_AMOUNT}\s*บาท.*?\(\s*จากราคา(คาดการณ์)?\s*{_AMOUNT}\s*บาท?\s*\)",
            block,
            flags=re.I | re.S,
        )
        english = re.search(
            rf"Special\s+Price\s*(?:THB)?\s*{_AMOUNT}.*?\(\s*from\s+(Estimated\s+Price\s*)?(?:THB)?\s*{_AMOUNT}\s*\)",
            block,
            flags=re.I | re.S,
        )
        if thai:
            campaign_raw, estimated_marker, reference_raw = (
                thai.group(1), thai.group(2), thai.group(3))
            evidence = thai.group(0)
        elif english:
            campaign_raw, estimated_marker, reference_raw = (
                english.group(1), english.group(2), english.group(3))
            evidence = english.group(0)
        else:
            continue
        campaign = _amount(campaign_raw)
        reference = _amount(reference_raw)
        claims.append(_claim(
            document_id=result.document.document_id,
            source_id=result.source_id,
            trim_raw=trim,
            amount_thb=campaign,
            price_type=PriceType.CAMPAIGN_PRICE,
            evidence_text=evidence,
            effective_from=start,
            effective_to=end,
            reference_price_thb=reference,
        ))
        claims.append(_claim(
            document_id=result.document.document_id,
            source_id=result.source_id,
            trim_raw=trim,
            amount_thb=reference,
            price_type=(PriceType.ESTIMATED_PRICE
                        if estimated_marker else PriceType.LIST_PRICE),
            evidence_text=evidence,
        ))
    return claims


def extract_oem_price_claims(target: SourceTarget,
                             result: FetchResult) -> ExtractionResult:
    """Extract classified price evidence from one fetched OEM target.

    The function is intentionally pure.  It does not use the catalog or ledger,
    and therefore cannot turn a raw grade string into canonical truth.
    """
    if result.not_modified or result.document is None:
        return ExtractionResult()
    if result.source_id != target.source_id:
        raise ExtractionError(
            f"{target.id}: fetch result source {result.source_id!r} does not match target")
    if result.source_id != "official_jaecoo_th":
        return ExtractionResult(warnings=(f"unsupported OEM source {result.source_id}",))

    text = " ".join(_visible_text(result).split())
    if not text:
        return ExtractionResult(warnings=(f"{target.id}: no visible text",))

    if target.role is TargetRole.PRICE_LIST:
        claims = _extract_homepage(result, text)
    elif target.role is TargetRole.BLOG:
        # This parser knows the dedicated J5 buyer-guide shape.  A naked grade
        # such as MAX+ on an arbitrary OEM blog is not enough to invent J5.
        if target.model_hint != _J5_MODEL_HINT:
            return ExtractionResult(warnings=(
                f"{target.id}: BLOG extraction requires model_hint {_J5_MODEL_HINT}",))
        claims = _extract_blog(result, text)
    elif target.role is TargetRole.PROMOTION:
        claims = _extract_promotion(result, text)
    else:
        return ExtractionResult()

    deduped = _dedupe(claims)
    warnings: tuple[str, ...] = ()
    if "JAECOO 5 EV" in text.upper() and not deduped and target.role in {
        TargetRole.PRICE_LIST, TargetRole.BLOG, TargetRole.PROMOTION,
    }:
        warnings = (f"{target.id}: JAECOO 5 present but no price claims extracted",)
    return ExtractionResult(claims=deduped, warnings=warnings)
