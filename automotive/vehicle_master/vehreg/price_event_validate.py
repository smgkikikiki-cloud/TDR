"""Evidence validation for AI-proposed price claims (PEE-1).

An AI proposal is *untrusted text*.  This module turns it into a
:class:`vehreg.pricefeed.PriceClaim` only when every load-bearing field can be
found, literally, in the evidence that was sent to the model:

* the quote exists in the cited excerpt (otherwise: hallucinated evidence);
* the amount, reference amount, raw trim, dates and conditions appear in it;
* the price type is consistent with the words immediately in front of the amount
  (the same MSRP / campaign / finance / estimate vocabulary P3 relies on);
* deposits, down payments and monthly instalments are never vehicle prices.

Anything ambiguous or unsupported becomes a :class:`ReviewItem` instead of a
claim.  Nothing here assigns ``trim_id`` / ``campaign_id`` / ``option_id`` --
identity stays the job of P4 (matching) and P5 (reconciliation).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
import re
import unicodedata
from typing import Iterable, Mapping, Optional, Sequence

from .catalog import Catalog
from .price_llm import CLAIM_FIELDS, FORBIDDEN_IDENTITY_KEYS
from .price_match import TrimMatchState, match_trim_diagnostic
from .pricefeed import (
    MAX_PLAUSIBLE_THB,
    MIN_PLAUSIBLE_THB,
    PriceClaim,
    content_id,
)
from .pricing import PriceType


class EventReviewReason(str, Enum):
    """Why an AI proposal (or a whole change event) went to REVIEW."""

    # Per-claim, from evidence validation.
    MALFORMED_CLAIM = "MALFORMED_CLAIM"
    EVIDENCE_NOT_FOUND = "EVIDENCE_NOT_FOUND"
    EVIDENCE_TOO_LONG = "EVIDENCE_TOO_LONG"
    AMOUNT_NOT_IN_EVIDENCE = "AMOUNT_NOT_IN_EVIDENCE"
    REFERENCE_NOT_IN_EVIDENCE = "REFERENCE_NOT_IN_EVIDENCE"
    IMPLAUSIBLE_AMOUNT = "IMPLAUSIBLE_AMOUNT"
    NOT_VEHICLE_PRICE = "NOT_VEHICLE_PRICE"
    PRICE_TYPE_UNKNOWN = "PRICE_TYPE_UNKNOWN"
    PRICE_TYPE_NOT_ALLOWED = "PRICE_TYPE_NOT_ALLOWED"
    PRICE_TYPE_UNSUPPORTED = "PRICE_TYPE_UNSUPPORTED"
    PRICE_TYPE_CONFLICT = "PRICE_TYPE_CONFLICT"
    MODEL_UNKNOWN = "MODEL_UNKNOWN"
    TRIM_UNKNOWN = "TRIM_UNKNOWN"
    TRIM_NOT_IN_EVIDENCE = "TRIM_NOT_IN_EVIDENCE"
    TRIM_AMBIGUOUS = "TRIM_AMBIGUOUS"
    DATE_NOT_IN_EVIDENCE = "DATE_NOT_IN_EVIDENCE"
    DATE_ORDER = "DATE_ORDER"
    CONDITION_NOT_IN_EVIDENCE = "CONDITION_NOT_IN_EVIDENCE"
    # Per-event, from the engine.
    AI_UNAVAILABLE = "AI_UNAVAILABLE"
    TOKEN_LIMIT_EXCEEDED = "TOKEN_LIMIT_EXCEEDED"
    TOKEN_BUDGET_EXHAUSTED = "TOKEN_BUDGET_EXHAUSTED"
    PROVIDER_FAILED = "PROVIDER_FAILED"
    MALFORMED_OUTPUT = "MALFORMED_OUTPUT"


@dataclass(frozen=True, slots=True)
class ReviewItem:
    reason: EventReviewReason
    detail: str = ""
    #: The raw AI proposal exactly as returned (never normalised or repaired).
    proposal: Optional[Mapping] = None

    def as_dict(self) -> dict:
        return {"reason": self.reason.value, "detail": self.detail,
                "proposal": dict(self.proposal) if self.proposal is not None else None}


@dataclass(frozen=True, slots=True)
class ClaimDetail:
    """Sidecar for facts a ``PriceClaim`` has no field for."""

    claim_id: str
    origin: str                                   # "ai" | "rules+ai"
    #: ``None`` = UNKNOWN (page silent); ``()`` = looked, none stated.
    conditions: Optional[tuple[str, ...]] = None
    evidence_segment: Optional[int] = None
    evidence_start: Optional[int] = None
    evidence_end: Optional[int] = None
    evidence_hash: str = ""
    cache_hit: bool = False
    ignored_fields: tuple[str, ...] = ()
    p4_state: str = ""

    def as_dict(self) -> dict:
        return {
            "claim_id": self.claim_id,
            "origin": self.origin,
            "conditions": list(self.conditions) if self.conditions is not None else None,
            "evidence_location": {
                "segment": self.evidence_segment,
                "start": self.evidence_start,
                "end": self.evidence_end,
            },
            "evidence_hash": self.evidence_hash,
            "cache_hit": self.cache_hit,
            "ignored_fields": list(self.ignored_fields),
            "p4_state": self.p4_state,
        }


@dataclass(frozen=True, slots=True)
class ValidationResult:
    accepted: tuple[tuple[PriceClaim, ClaimDetail], ...] = ()
    review: tuple[ReviewItem, ...] = ()


# ---------------------------------------------------------------- text helpers

_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿"))

AMOUNT_RE = re.compile(r"(?<![\d,])(\d{1,3}(?:,\d{3})+|\d{6,9})(?![\d,])")

MAX_EVIDENCE_CHARS = 200


def normalize_text(text: str) -> str:
    """NFKC, zero-width removed, whitespace collapsed.  Case is preserved."""
    value = unicodedata.normalize("NFKC", text or "").translate(_ZERO_WIDTH)
    return " ".join(value.split())


def amounts_in(text: str) -> list[int]:
    return [int(m.group(1).replace(",", "")) for m in AMOUNT_RE.finditer(text or "")]


_THAI_MONTHS = {
    "มกราคม": 1, "กุมภาพันธ์": 2, "มีนาคม": 3, "เมษายน": 4, "พฤษภาคม": 5,
    "มิถุนายน": 6, "กรกฎาคม": 7, "สิงหาคม": 8, "กันยายน": 9, "ตุลาคม": 10,
    "พฤศจิกายน": 11, "ธันวาคม": 12,
    "ม.ค.": 1, "ก.พ.": 2, "มี.ค.": 3, "เม.ย.": 4, "พ.ค.": 5, "มิ.ย.": 6,
    "ก.ค.": 7, "ส.ค.": 8, "ก.ย.": 9, "ต.ค.": 10, "พ.ย.": 11, "ธ.ค.": 12,
}
_EN_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12, "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTHS = {**_THAI_MONTHS, **_EN_MONTHS}
_MONTH_ALT = "|".join(
    re.escape(name) for name in sorted(_MONTHS, key=len, reverse=True))
_MONTH_PAT = rf"(?:{_MONTH_ALT})(?![A-Za-z])"
_DASH = r"(?:\s*[–—\-~]\s*|\s+(?:ถึง|to|until|-)\s+)"

_RANGE_RE = re.compile(
    rf"(?<!\d)(?P<d1>\d{{1,2}})(?:\s*(?P<m1>{_MONTH_PAT})\.?)?(?:\s*(?P<y1>\d{{4}}))?"
    rf"{_DASH}(?P<d2>\d{{1,2}})\s*(?P<m2>{_MONTH_PAT})\.?\s*(?P<y2>\d{{4}})(?!\d)",
    re.I,
)
_SINGLE_RE = re.compile(
    rf"(?<!\d)(?P<d>\d{{1,2}})\s*(?P<m>{_MONTH_PAT})\.?\s*(?P<y>\d{{4}})(?!\d)", re.I)
_ISO_RE = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
_SLASH_RE = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{4})(?!\d)")
#: Looser than the strict parsers: used only to *notice* that a date was written.
DATE_TOKEN_RE = re.compile(
    rf"\d{{1,2}}(?:\s*[–—\-~]\s*\d{{1,2}})?\s*{_MONTH_PAT}\.?(?:\s*\d{{4}})?"
    rf"|\d{{4}}-\d{{2}}-\d{{2}}|\d{{1,2}}/\d{{1,2}}/\d{{4}}", re.I)


def _month(raw: str) -> Optional[int]:
    return _MONTHS.get(raw.casefold()) or _MONTHS.get(raw)


def _iso(year: int, month: int, day: int) -> Optional[str]:
    if year >= 2400:               # Buddhist Era
        year -= 543
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def extract_dates(text: str) -> set[str]:
    """Every fully-specified (day, month, year) date literally written in text.

    A day/month without a year is *not* a date here: filling the year in is
    exactly the invention the engine forbids.
    """
    found: set[str] = set()
    text = normalize_text(text)
    for m in _RANGE_RE.finditer(text):
        m2, y2 = _month(m["m2"]), int(m["y2"])
        m1 = _month(m["m1"]) if m["m1"] else m2
        if m1 is None or m2 is None:
            continue
        y1 = int(m["y1"]) if m["y1"] else (y2 - 1 if m1 > m2 else y2)
        for value in (_iso(y1, m1, int(m["d1"])), _iso(y2, m2, int(m["d2"]))):
            if value:
                found.add(value)
    for m in _SINGLE_RE.finditer(text):
        month = _month(m["m"])
        value = _iso(int(m["y"]), month, int(m["d"])) if month else None
        if value:
            found.add(value)
    for m in _ISO_RE.finditer(text):
        value = _iso(int(m[1]), int(m[2]), int(m[3]))
        if value:
            found.add(value)
    for m in _SLASH_RE.finditer(text):
        value = _iso(int(m[3]), int(m[2]), int(m[1]))
        if value:
            found.add(value)
    return found


def date_tokens(text: str) -> list[str]:
    return sorted({normalize_text(m.group(0)).casefold()
                   for m in DATE_TOKEN_RE.finditer(text or "")})


# ------------------------------------------------------------ price semantics

#: Words that make a nearby number *not* a vehicle price.
_NON_PRICE_BEFORE = re.compile(
    r"(เงินดาวน์|ดาวน์|ค่างวด|ผ่อน|งวดละ|เงินจอง|ค่าจอง|มัดจำ|"
    r"down\s*payment|deposit|instal+ment|monthly|booking\s*fee|reservation)\s*"
    r"(?:ขั้นต่ำ|เริ่มต้น|เพียง|only|from|starting|of|:)?\s*(?:THB|฿|บาท)?\s*$",
    re.I)
_NON_PRICE_AFTER = re.compile(
    r"^\s*(?:THB|฿|บาท)?\s*(?:/|ต่อ|per\s|a\s)\s*"
    r"(เดือน|งวด|month|mo\b|ปี|year)", re.I)

_REF_FROM = re.compile(
    r"(?:จากราคา|from)\s*(?P<est>คาดการณ์|estimated\s+price|estimated)?\s*"
    r"(?:THB|฿|บาท)?\s*$", re.I)
_ESTIMATED = re.compile(r"(ราคาคาดการณ์|คาดการณ์|estimated|expected\s+price|approx)", re.I)
_FINANCE = re.compile(
    r"(สินเชื่อ|ไฟแนนซ์|ผ่านการเงิน|ใช้บริการ.*?(?:ไฟแนนซ์|สินเชื่อ)|"
    r"with\s+financing|finance|financing|loan)", re.I)
_CAMPAIGN = re.compile(
    r"(ราคาพิเศษ|ราคาโปรโมชัน|ราคาโปรโมชั่น|โปรโมชัน|โปรโมชั่น|ส่วนลด|ลดเหลือ|"
    r"special\s+price|promo(?:tion(?:al)?)?(?:\s+price)?|discount|sale\s+price|"
    r"deal\s+price|campaign)", re.I)
_INTRO = re.compile(r"(ราคาเปิดตัว|เปิดตัว|introductory|launch\s+price|intro\s+price)", re.I)

#: Marker families that make a quote *campaign-bearing* for type checking.
CAMPAIGN_FAMILY = frozenset({PriceType.CAMPAIGN_PRICE, PriceType.FINANCE_PRICE})


def _amount_spans(text: str) -> list[tuple[int, int, int]]:
    return [(m.start(1), m.end(1), int(m.group(1).replace(",", "")))
            for m in AMOUNT_RE.finditer(text)]


def _label_before(text: str, start: int) -> str:
    """Words that label the number at ``start``: back to the previous number."""
    window = text[max(0, start - 70):start]
    last_end = 0
    for m in AMOUNT_RE.finditer(window):
        last_end = m.end()
    window = window[last_end:]
    if ")" in window:
        window = window[window.rfind(")") + 1:]
    return window


def price_context_class(text: str, amount: int) -> Optional[str]:
    """Classify the *first* occurrence of ``amount`` in ``text``.

    Returns one of ``NON_PRICE | LIST | ESTIMATED | CAMPAIGN | FINANCE |
    INTRODUCTORY`` or ``None`` if the amount is not in the text.
    """
    for start, end, value in _amount_spans(text):
        if value != amount:
            continue
        before = _label_before(text, start)
        after = text[end:end + 24]
        if _NON_PRICE_BEFORE.search(before) or _NON_PRICE_AFTER.search(after):
            return "NON_PRICE"
        ref = _REF_FROM.search(before)
        if ref:                                  # "(from 699,000)" / "(จากราคาคาดการณ์ 809,000)"
            return "ESTIMATED" if ref.group("est") else "LIST"
        if _ESTIMATED.search(before):
            return "ESTIMATED"
        if _FINANCE.search(before):
            return "FINANCE"
        if _CAMPAIGN.search(before):
            return "CAMPAIGN"
        if _INTRO.search(before):
            return "INTRODUCTORY"
        return "LIST"
    return None


_CLASS_TO_TYPE = {
    "LIST": PriceType.LIST_PRICE,
    "ESTIMATED": PriceType.ESTIMATED_PRICE,
    "CAMPAIGN": PriceType.CAMPAIGN_PRICE,
    "FINANCE": PriceType.FINANCE_PRICE,
    "INTRODUCTORY": PriceType.INTRODUCTORY_PRICE,
}

#: What an OEM page can say.  Dealer and eco-sticker prices are other sources'.
DEFAULT_ALLOWED_TYPES = frozenset(_CLASS_TO_TYPE.values())


def uncovered_amounts(text: str, covered: Iterable[int]) -> list[int]:
    """Plausible vehicle-price amounts in ``text`` that no claim accounts for."""
    covered = set(covered)
    out: list[int] = []
    for _start, _end, value in _amount_spans(text):
        if not MIN_PLAUSIBLE_THB <= value <= MAX_PLAUSIBLE_THB or value in covered:
            continue
        if price_context_class(text, value) == "NON_PRICE":
            continue
        if value not in out:
            out.append(value)
    return out


# ------------------------------------------------------------------ validation

def _int_field(raw: object) -> Optional[int]:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float) and raw.is_integer():
        return int(raw)
    if isinstance(raw, str) and re.fullmatch(r"\d{1,3}(?:,\d{3})+|\d+", raw.strip()):
        return int(raw.strip().replace(",", ""))
    return None


def _str_field(raw: object) -> Optional[str]:
    if raw is None:
        return None
    if not isinstance(raw, str):
        return ""
    return normalize_text(raw) or None


def _find(haystack: str, needle: str) -> Optional[tuple[int, int]]:
    """Case-insensitive, whitespace-flexible literal search."""
    pattern = r"\s+".join(re.escape(part) for part in needle.split())
    match = re.search(pattern, haystack, re.I)
    return (match.start(), match.end()) if match else None


def _find_grade(haystack: str, trim: str) -> bool:
    """A grade must appear as a whole token; ``MAX`` is not ``MAX+``."""
    body = r"\s+".join(re.escape(part) for part in trim.split())
    tail = r"(?![A-Za-z0-9])" if trim.endswith("+") else r"(?![A-Za-z0-9+])"
    return re.search(rf"(?<![A-Za-z0-9]){body}{tail}", haystack, re.I) is not None


def _clean_trim(raw: str) -> str:
    return " ".join(raw.upper().split())


def _is_token_prefix(short: str, long: str) -> bool:
    a, b = short.split(), long.split()
    return len(a) < len(b) and b[:len(a)] == a


def validate_ai_claims(
        raw_claims: Sequence[object], *, segments: Sequence[str], document_text: str,
        document_id: str, source_id: str, evidence_hash: str, extraction_method: str,
        allowed_types: frozenset[PriceType] = DEFAULT_ALLOWED_TYPES,
        catalog: Optional[Catalog] = None, cache_hit: bool = False,
) -> ValidationResult:
    """Validate raw model proposals against the payload that was sent.

    ``segments`` are the payload-indexed excerpts the model saw; ``document_text``
    is the whole normalised visible page (only used to confirm brand/model
    wording).  Returns accepted ``(claim, detail)`` pairs and review items.
    """
    review: list[ReviewItem] = []
    staged: list[dict] = []
    doc_text = normalize_text(document_text)

    def reject(reason: EventReviewReason, detail: str, raw: object) -> None:
        review.append(ReviewItem(
            reason, detail, raw if isinstance(raw, Mapping) else {"raw": repr(raw)[:300]}))

    for raw in raw_claims:
        if not isinstance(raw, Mapping):
            reject(EventReviewReason.MALFORMED_CLAIM, "claim is not an object", raw)
            continue
        ignored = tuple(sorted(
            key for key in raw if key in FORBIDDEN_IDENTITY_KEYS or key not in CLAIM_FIELDS))

        # -- price type ---------------------------------------------------
        try:
            price_type = PriceType.parse(raw.get("price_type"))
        except Exception:
            reject(EventReviewReason.PRICE_TYPE_UNKNOWN, "unrecognised price_type", raw)
            continue
        if price_type is PriceType.UNKNOWN:
            reject(EventReviewReason.PRICE_TYPE_UNKNOWN,
                   "model could not classify the price", raw)
            continue
        if price_type not in allowed_types:
            reject(EventReviewReason.PRICE_TYPE_NOT_ALLOWED,
                   f"{price_type.value} is not an OEM page price type", raw)
            continue

        # -- numbers ------------------------------------------------------
        amount = _int_field(raw.get("amount_thb"))
        if amount is None or amount <= 0:
            reject(EventReviewReason.MALFORMED_CLAIM, "amount_thb is not a positive integer", raw)
            continue
        if not MIN_PLAUSIBLE_THB <= amount <= MAX_PLAUSIBLE_THB:
            reject(EventReviewReason.IMPLAUSIBLE_AMOUNT,
                   f"{amount} outside plausible vehicle price range", raw)
            continue
        reference: Optional[int] = None
        if raw.get("reference_price_thb") is not None:
            reference = _int_field(raw.get("reference_price_thb"))
            if reference is None or reference <= 0:
                reject(EventReviewReason.MALFORMED_CLAIM,
                       "reference_price_thb is not a positive integer", raw)
                continue

        # -- evidence quote -----------------------------------------------
        quote = _str_field(raw.get("evidence_text"))
        if not quote:
            reject(EventReviewReason.EVIDENCE_NOT_FOUND, "no evidence_text supplied", raw)
            continue
        if len(quote) > MAX_EVIDENCE_CHARS:
            reject(EventReviewReason.EVIDENCE_TOO_LONG,
                   f"evidence_text exceeds {MAX_EVIDENCE_CHARS} characters", raw)
            continue
        cited = _int_field(raw.get("evidence_segment"))
        order = ([cited] if cited is not None and 0 <= cited < len(segments) else [])
        order += [i for i in range(len(segments)) if i not in order]
        location: Optional[tuple[int, int, int]] = None
        for index in order:
            hit = _find(segments[index], quote)
            if hit:
                location = (index, hit[0], hit[1])
                break
        if location is None:
            reject(EventReviewReason.EVIDENCE_NOT_FOUND,
                   "quoted evidence does not appear in the supplied excerpts", raw)
            continue
        segment_text = segments[location[0]]

        if amount not in amounts_in(quote):
            reject(EventReviewReason.AMOUNT_NOT_IN_EVIDENCE,
                   f"{amount} is not in the quoted evidence", raw)
            continue
        if reference is not None and reference not in amounts_in(quote):
            reject(EventReviewReason.REFERENCE_NOT_IN_EVIDENCE,
                   f"{reference} is not in the quoted evidence", raw)
            continue

        # -- price type vs. the words in front of the number ---------------
        local = price_context_class(quote, amount)
        if local == "NON_PRICE":
            reject(EventReviewReason.NOT_VEHICLE_PRICE,
                   "amount is labelled as a deposit/down payment/instalment", raw)
            continue
        implied = _CLASS_TO_TYPE.get(local or "")
        if implied is not price_type:
            if price_type is PriceType.LIST_PRICE:
                reject(EventReviewReason.PRICE_TYPE_CONFLICT,
                       f"evidence labels this amount {local}, not LIST_PRICE", raw)
            elif implied is PriceType.LIST_PRICE:
                reject(EventReviewReason.PRICE_TYPE_UNSUPPORTED,
                       f"evidence has no {price_type.value} wording before the amount", raw)
            else:
                reject(EventReviewReason.PRICE_TYPE_CONFLICT,
                       f"evidence labels this amount {local}, not {price_type.value}", raw)
            continue

        # -- identity wording ---------------------------------------------
        brand = _str_field(raw.get("brand_raw"))
        model = _str_field(raw.get("model_raw"))
        if not brand or not model or _find(doc_text, brand) is None \
                or _find(doc_text, model) is None:
            reject(EventReviewReason.MODEL_UNKNOWN,
                   "brand/model wording is missing from the page", raw)
            continue
        trim = _str_field(raw.get("trim_raw"))
        if not trim:
            reject(EventReviewReason.TRIM_UNKNOWN, "no trim stated for this price", raw)
            continue
        if not _find_grade(quote, trim):
            reject(EventReviewReason.TRIM_NOT_IN_EVIDENCE,
                   f"trim {trim!r} is not written in the quoted evidence", raw)
            continue

        # -- dates ---------------------------------------------------------
        dates: list[Optional[str]] = []
        bad_date = False
        supported = extract_dates(segment_text) | extract_dates(quote)
        for name in ("effective_from", "effective_to"):
            value = raw.get(name)
            if value is None:
                dates.append(None)
                continue
            text = value.strip() if isinstance(value, str) else ""
            try:
                iso = date.fromisoformat(text).isoformat() if re.fullmatch(
                    r"\d{4}-\d{2}-\d{2}", text) else None
            except ValueError:
                iso = None
            if iso is None or iso not in supported:
                reject(EventReviewReason.DATE_NOT_IN_EVIDENCE,
                       f"{name}={value!r} is not a date written in the excerpt", raw)
                bad_date = True
                break
            dates.append(iso)
        if bad_date:
            continue
        if dates[0] and dates[1] and dates[0] > dates[1]:
            reject(EventReviewReason.DATE_ORDER, "effective_from is after effective_to", raw)
            continue

        # -- conditions ----------------------------------------------------
        conditions: Optional[tuple[str, ...]] = None
        raw_conditions = raw.get("conditions")
        if raw_conditions is not None:
            if not isinstance(raw_conditions, list):
                reject(EventReviewReason.MALFORMED_CLAIM, "conditions must be an array", raw)
                continue
            kept: list[str] = []
            bad = False
            for item in raw_conditions:
                text = _str_field(item)
                if not text or len(text) > MAX_EVIDENCE_CHARS or not any(
                        _find(seg, text) for seg in segments):
                    reject(EventReviewReason.CONDITION_NOT_IN_EVIDENCE,
                           f"condition {str(item)[:80]!r} is not a verbatim quote", raw)
                    bad = True
                    break
                kept.append(text)
            if bad:
                continue
            conditions = tuple(kept)

        staged.append({
            "raw": raw, "ignored": ignored, "price_type": price_type, "amount": amount,
            "reference": reference, "brand": brand, "model": model,
            "trim": _clean_trim(trim), "from": dates[0], "to": dates[1],
            "quote": quote, "location": location, "conditions": conditions,
        })

    # -- batch-level trim ambiguity: "LONG RANGE" next to "LONG RANGE MAX" ----
    # With a catalog, P4 decides exact-vs-ambiguous precisely; this cheap
    # heuristic only guards the catalog-less case.
    trims = {row["trim"] for row in staged}
    survivors: list[dict] = []
    for row in staged:
        longer = ([] if catalog is not None else
                  sorted(t for t in trims if _is_token_prefix(row["trim"], t)))
        if longer:
            reject(EventReviewReason.TRIM_AMBIGUOUS,
                   f"trim {row['trim']!r} is a prefix of {longer}; grade not distinguishable",
                   row["raw"])
        else:
            survivors.append(row)

    accepted: list[tuple[PriceClaim, ClaimDetail]] = []
    seen: set[tuple] = set()
    for row in survivors:
        key = (row["trim"], row["amount"], row["price_type"], row["from"],
               row["to"], row["reference"])
        if key in seen:
            continue
        seen.add(key)
        semantic = (f"{document_id}|ai|{row['brand']}|{row['model']}|{row['trim']}|"
                    f"{row['amount']}|{row['price_type'].value}|{row['from'] or ''}|"
                    f"{row['to'] or ''}|{row['reference'] or ''}")
        claim = PriceClaim(
            claim_id=content_id(semantic)[7:23],
            document_id=document_id,
            source_id=source_id,
            brand_raw=row["brand"],
            model_raw=row["model"],
            trim_raw=row["trim"],
            amount_thb=row["amount"],
            price_type=row["price_type"],
            evidence_text=row["quote"],
            extraction_method=extraction_method,
            effective_from=row["from"],
            effective_to=row["to"],
            reference_price_thb=row["reference"],
        )
        problems = claim.validate()
        if problems:
            reject(EventReviewReason.MALFORMED_CLAIM, "; ".join(problems), row["raw"])
            continue
        p4_state = ""
        if catalog is not None:
            verdict = match_trim_diagnostic(catalog, claim)
            p4_state = verdict.state.value
            if verdict.state is TrimMatchState.AMBIGUOUS:
                reject(EventReviewReason.TRIM_AMBIGUOUS,
                       f"P4: {verdict.reason} ({', '.join(verdict.candidate_ids)})", row["raw"])
                continue
        index, start, end = row["location"]
        accepted.append((claim, ClaimDetail(
            claim_id=claim.claim_id, origin="ai", conditions=row["conditions"],
            evidence_segment=index, evidence_start=start, evidence_end=end,
            evidence_hash=evidence_hash, cache_hit=cache_hit,
            ignored_fields=row["ignored"], p4_state=p4_state)))
    return ValidationResult(tuple(accepted), tuple(review))
