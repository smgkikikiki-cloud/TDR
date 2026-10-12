"""Price Event Engine, chunk 1 (PEE-1): rule-first, event-based AI extraction.

Sits *beside* P2 (fetch) / P3 (rules) / P4 (match) / P5 (reconcile) and reuses
them; it does not replace or reimplement any of them and never writes
PriceLedger, the catalog or serving data::

    FetchResult
      -> price-relevant fingerprint            (is there a meaningful change?)
      -> unchanged?  ........................ zero AI calls
      -> P3 deterministic extraction            (can rules interpret the change?)
      -> reliable?   ........................ zero AI calls
      -> optional LLM fallback (provider adapter, cache, token limits, budgets)
      -> evidence validation  (price_event_validate)
      -> PriceClaim[] for P4/P5   +   ReviewItem[] for humans

The whole engine is inert unless ``PriceEventConfig.enabled`` is true (default
false), and the AI fallback is additionally limited to ``ai_sources`` (default:
the official JAECOO source only).  State (fingerprints, cache, budgets) is a
small JSON file that exists only when the caller supplies a path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
import math
import os
from pathlib import Path
import re
import time
from typing import Callable, Mapping, Optional

from .catalog import Catalog
from .price_event_validate import (
    AMOUNT_RE,
    DATE_TOKEN_RE,
    ClaimDetail,
    EventReviewReason,
    ReviewItem,
    ValidationResult,
    amounts_in,
    date_tokens,
    extract_dates,
    normalize_text,
    uncovered_amounts,
    validate_ai_claims,
)
from .price_extract import (
    ExtractionError,
    ExtractionResult,
    _EvidenceTextParser,
    extract_oem_price_claims,
)
from .price_fetch import FetchResult
from .price_llm import (
    LLMProvider,
    LLMProviderError,
    MalformedOutputError,
    PROMPT_VERSION,
    build_request,
    parse_llm_claims,
    resolve_provider,
)
from .price_sources import SourceTarget
from .price_time import thailand_business_date
from .pricefeed import PriceClaim, content_id

STATE_SCHEMA_VERSION = 1
FINGERPRINT_VERSION = 2
JAECOO_SOURCE = "official_jaecoo_th"


class EventStateError(RuntimeError):
    pass


# --------------------------------------------------------------------- config

def _env_bool(raw: Optional[str]) -> bool:
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class PriceEventConfig:
    #: Master feature flag.  OFF unless explicitly turned on.
    enabled: bool = False
    #: Sources whose changed pages may use the AI fallback.  Everything else is
    #: left entirely to the existing rule-based pipeline.
    ai_sources: frozenset[str] = frozenset({JAECOO_SOURCE})
    #: Name registered with :func:`vehreg.price_llm.register_provider`.
    provider: str = ""
    extractor_version: str = "pee-1"
    prompt_version: str = PROMPT_VERSION
    max_input_tokens: int = 3_000
    max_output_tokens: int = 1_200
    #: Conservative (Thai-heavy) estimate used when no tokenizer is available.
    chars_per_token: float = 2.0
    daily_token_budget: int = 60_000
    daily_call_budget: int = 200
    #: Per-source overrides of the two daily budgets above.
    source_token_budgets: Mapping[str, int] = field(default_factory=dict)
    source_call_budgets: Mapping[str, int] = field(default_factory=dict)
    #: Extra attempts after the first (so total attempts = 1 + max_retries).
    max_retries: int = 2
    retry_backoff_seconds: float = 0.0
    #: Characters of context kept either side of each price-related anchor.
    window_chars: int = 140
    cache_entries: int = 500
    #: Provider calls are only made when usage is persisted to a file, so a
    #: daily cap cannot be evaded by starting a fresh process.  Tests and
    #: local simulations without a state path simply make zero calls.
    require_durable_state: bool = True

    def validate(self) -> list[str]:
        problems = []
        for name in ("max_input_tokens", "max_output_tokens", "daily_token_budget",
                     "daily_call_budget", "cache_entries"):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                problems.append(f"{name} must be a positive integer")
        if type(self.max_retries) is not int or self.max_retries < 0:
            problems.append("max_retries must be >= 0")
        if self.chars_per_token <= 0:
            problems.append("chars_per_token must be positive")
        if self.retry_backoff_seconds < 0:
            problems.append("retry_backoff_seconds must be >= 0")
        return problems

    def token_budget(self, source_id: str) -> int:
        return int(self.source_token_budgets.get(source_id, self.daily_token_budget))

    def call_budget(self, source_id: str) -> int:
        return int(self.source_call_budgets.get(source_id, self.daily_call_budget))

    @classmethod
    def from_env(cls, environ: Optional[Mapping[str, str]] = None) -> "PriceEventConfig":
        env = os.environ if environ is None else environ
        if not _env_bool(env.get("TDR_PRICE_EVENT_ENGINE")):
            # Flag off: do not even parse the other variables, so a malformed
            # tuning value can never break the existing pipeline.
            return cls()
        defaults = cls()

        def number(name: str, fallback):
            raw = env.get(name)
            return type(fallback)(raw) if raw not in (None, "") else fallback

        sources = env.get("TDR_PRICE_EVENT_AI_SOURCES")
        config = cls(
            enabled=True,
            ai_sources=(frozenset(s.strip() for s in sources.split(",") if s.strip())
                        if sources else defaults.ai_sources),
            provider=env.get("TDR_PRICE_EVENT_PROVIDER", ""),
            extractor_version=env.get("TDR_PRICE_EVENT_EXTRACTOR_VERSION",
                                      defaults.extractor_version),
            max_input_tokens=number("TDR_PRICE_EVENT_MAX_INPUT_TOKENS",
                                    defaults.max_input_tokens),
            max_output_tokens=number("TDR_PRICE_EVENT_MAX_OUTPUT_TOKENS",
                                     defaults.max_output_tokens),
            daily_token_budget=number("TDR_PRICE_EVENT_DAILY_TOKENS",
                                      defaults.daily_token_budget),
            daily_call_budget=number("TDR_PRICE_EVENT_DAILY_CALLS",
                                     defaults.daily_call_budget),
            max_retries=number("TDR_PRICE_EVENT_MAX_RETRIES", defaults.max_retries),
        )
        problems = config.validate()
        if problems:
            raise ValueError("invalid price-event config: " + "; ".join(problems))
        return config


# ---------------------------------------------------------------- fingerprint

_CONDITION_WORDS = re.compile(
    r"(เงื่อนไข|จอง|ส่งมอบ|เทิร์น|ผ่อน|ดาวน์|ดอกเบี้ย|ภายใน|ตั้งแต่|ถึงวันที่|"
    r"เฉพาะ|จำนวนจำกัด|สิทธิ|เมื่อ|conditions?|terms|booking|book\b|deliver|"
    r"trade-?in|interest|financ|valid|until|limited|only|eligible|subject\s+to|"
    r"while\s+stocks)", re.I)
_PRICE_WORDS = re.compile(
    r"(ราคา|โปรโมชัน|โปรโมชั่น|ส่วนลด|price|promo|discount|special|msrp)", re.I)
_PROXIMITY = 300
_CLAUSE_SPLIT = re.compile(r"[.;|•*]+")


@dataclass(frozen=True, slots=True)
class Fingerprint:
    """Hashes of the price-relevant parts of one page, per kind of change."""

    price_hash: str
    amounts_hash: str
    dates_hash: str
    conditions_hash: str
    labels_hash: str
    segment_hashes: tuple[str, ...]
    #: The masked condition clauses and the fully-written ISO dates themselves
    #: (not just hashes): a later fallback must prove a *new* condition/date was
    #: interpreted, so it needs to know what the last resolved page already said.
    conditions_text: str = ""
    dates: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {"version": FINGERPRINT_VERSION, "price_hash": self.price_hash,
                "amounts_hash": self.amounts_hash, "dates_hash": self.dates_hash,
                "conditions_hash": self.conditions_hash, "labels_hash": self.labels_hash,
                "segment_hashes": list(self.segment_hashes),
                "conditions_text": self.conditions_text, "dates": list(self.dates)}

    @classmethod
    def from_dict(cls, raw: Mapping) -> "Fingerprint":
        return cls(raw["price_hash"], raw["amounts_hash"], raw["dates_hash"],
                   raw["conditions_hash"], raw["labels_hash"],
                   tuple(raw["segment_hashes"]), str(raw["conditions_text"]),
                   tuple(raw["dates"]))


class ChangeKind(str, Enum):
    FIRST_SEEN = "FIRST_SEEN"
    AMOUNTS = "AMOUNTS"
    DATES = "DATES"
    CONDITIONS = "CONDITIONS"
    LABELS = "LABELS"          # trim names / wording around the prices


def _hash(items) -> str:
    return content_id(json.dumps(items, ensure_ascii=False, sort_keys=True))


def visible_text(result: FetchResult) -> str:
    """Whole-page visible text in DOM order (script/style excluded)."""
    if not result.text:
        return ""
    parser = _EvidenceTextParser()
    parser.feed(result.text)
    return normalize_text(" ".join(parser.parts))


def _anchors(text: str) -> list[tuple[int, int]]:
    amounts = [(m.start(), m.end()) for m in AMOUNT_RE.finditer(text)]
    words = [(m.start(), m.end()) for m in _PRICE_WORDS.finditer(text)]
    conds = [(m.start(), m.end()) for m in _CONDITION_WORDS.finditer(text)]
    dates = [(m.start(), m.end()) for m in DATE_TOKEN_RE.finditer(text)]

    def near(span, others) -> bool:
        return any(abs(span[0] - o[1]) <= _PROXIMITY and abs(o[0] - span[1]) <= _PROXIMITY
                   for o in others)

    keep = list(amounts)
    keep += [d for d in dates if near(d, amounts) or near(d, conds)]
    keep += [c for c in conds if near(c, amounts)]
    keep += [w for w in words if near(w, amounts)]
    return sorted(set(keep))


def price_segments(text: str, window: int) -> list[str]:
    """Merge a window around every price-related anchor into excerpts."""
    spans: list[list[int]] = []
    for start, end in _anchors(text):
        lo, hi = max(0, start - window), min(len(text), end + window)
        if spans and lo <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], hi)
        else:
            spans.append([lo, hi])
    return [text[lo:hi].strip() for lo, hi in spans if text[lo:hi].strip()]


def mask_text(text: str) -> str:
    """Casefold, mask amounts/dates, collapse whitespace (fingerprint form)."""
    masked = DATE_TOKEN_RE.sub("@", AMOUNT_RE.sub("#", text.casefold()))
    return " ".join(masked.split())


def fingerprint_segments(segments: list[str]) -> Fingerprint:
    folded = [s.casefold() for s in segments]
    joined = " ".join(segments)
    conditions: list[str] = []
    labels: list[str] = []
    for segment in folded:
        for clause in _CLAUSE_SPLIT.split(segment):
            masked = mask_text(clause)
            if not masked:
                continue
            (conditions if _CONDITION_WORDS.search(masked) else labels).append(masked)
    return Fingerprint(
        price_hash=_hash(folded),
        amounts_hash=_hash(sorted(amounts_in(joined))),
        dates_hash=_hash(date_tokens(joined)),
        conditions_hash=_hash(sorted(set(conditions))),
        labels_hash=_hash(sorted(set(labels))),
        segment_hashes=tuple(_hash(s) for s in folded),
        conditions_text=" | ".join(sorted(set(conditions))),
        dates=tuple(sorted(extract_dates(joined))),
    )


def diff_fingerprints(previous: Optional[Fingerprint],
                      current: Fingerprint) -> tuple[ChangeKind, ...]:
    if previous is None:
        return (ChangeKind.FIRST_SEEN,)
    if previous.price_hash == current.price_hash:
        return ()
    kinds = []
    if previous.amounts_hash != current.amounts_hash:
        kinds.append(ChangeKind.AMOUNTS)
    if previous.dates_hash != current.dates_hash:
        kinds.append(ChangeKind.DATES)
    if previous.conditions_hash != current.conditions_hash:
        kinds.append(ChangeKind.CONDITIONS)
    if previous.labels_hash != current.labels_hash or not kinds:
        # Either the non-price wording changed, or the segments moved/merged in
        # a way no component hash explains.  Both are real changes.
        kinds.append(ChangeKind.LABELS)
    return tuple(kinds)


# ---------------------------------------------------------------------- state

class EventState:
    """Fingerprint baselines + extraction cache + usage ledger.

    In-memory unless ``path`` is given.  A corrupt file raises instead of
    resetting: silently forgetting usage would defeat the budgets.
    """

    def __init__(self, path: Optional[Path | str] = None, *,
                 cache_entries: int = 500) -> None:
        self.path = Path(path) if path else None
        self.cache_entries = cache_entries
        self.data: dict = {"schema_version": STATE_SCHEMA_VERSION,
                           "fingerprints": {}, "cache": {}, "usage": {},
                           "interpretations": {}}
        if self.path is not None and self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise EventStateError(f"{self.path}: unreadable event state: {exc}") from exc
            if loaded.get("schema_version") != STATE_SCHEMA_VERSION:
                raise EventStateError(f"{self.path}: unsupported event state schema")
            loaded.setdefault("interpretations", {})
            for key in ("fingerprints", "cache", "usage", "interpretations"):
                if not isinstance(loaded.get(key), dict):
                    raise EventStateError(f"{self.path}: {key} must be an object")
            self.data = loaded

    @property
    def durable(self) -> bool:
        return self.path is not None

    def baseline(self, target_id: str) -> Optional[Fingerprint]:
        raw = self.data["fingerprints"].get(target_id)
        if not raw or raw.get("version") != FINGERPRINT_VERSION:
            return None          # a new fingerprint scheme restarts the baseline
        return Fingerprint.from_dict(raw)

    def set_baseline(self, target_id: str, fingerprint: Fingerprint) -> None:
        self.data["fingerprints"][target_id] = fingerprint.as_dict()

    def cache_get(self, key: str) -> Optional[list]:
        entry = self.data["cache"].get(key)
        return list(entry["claims"]) if entry else None

    def cache_put(self, key: str, claims: list) -> None:
        cache = self.data["cache"]
        cache.pop(key, None)
        cache[key] = {"claims": claims}
        while len(cache) > self.cache_entries:
            cache.pop(next(iter(cache)))

    def interpretation(self, target_id: str, price_hash: str,
                       versions: str) -> Optional[list]:
        """Validated proposals for exactly this full-page price fingerprint."""
        entry = self.data["interpretations"].get(target_id)
        if not entry or entry.get("price_hash") != price_hash \
                or entry.get("versions") != versions:
            return None
        return list(entry["claims"])

    def set_interpretation(self, target_id: str, price_hash: str, versions: str,
                           claims: list) -> None:
        self.data["interpretations"][target_id] = {
            "price_hash": price_hash, "versions": versions, "claims": claims}

    def usage(self, source_id: str, day: str) -> tuple[int, int]:
        row = self.data["usage"].get(day, {}).get(source_id, {})
        return int(row.get("tokens", 0)), int(row.get("calls", 0))

    def charge(self, source_id: str, day: str, tokens: int, calls: int = 1) -> None:
        usage = self.data["usage"]
        for old in sorted(usage)[:-3]:        # keep only the last few days
            if old != day:
                usage.pop(old, None)
        row = usage.setdefault(day, {}).setdefault(source_id, {"tokens": 0, "calls": 0})
        row["tokens"] = max(0, row["tokens"] + int(tokens))
        row["calls"] += calls

    def save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2,
                                  sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)


# -------------------------------------------------------------------- outcome

class EventStatus(str, Enum):
    DISABLED = "DISABLED"
    NOT_MODIFIED = "NOT_MODIFIED"
    SOURCE_NOT_ENABLED = "SOURCE_NOT_ENABLED"
    UNCHANGED = "UNCHANGED"
    DETERMINISTIC = "DETERMINISTIC"
    #: The AI interpretation fully resolved the change: nothing was rejected and
    #: every plausible price is covered.  Only then does the baseline advance.
    AI_EXTRACTED = "AI_EXTRACTED"
    #: The change is NOT resolved (AI unavailable/over budget/failed, a proposal
    #: was rejected, or a price is left uncovered).  The baseline is *not*
    #: advanced, so the change is retried; validated claims, if any, are still
    #: returned and every unresolved item is in ``review``.
    REVIEW = "REVIEW"


@dataclass(frozen=True, slots=True)
class EventOutcome:
    target_id: str
    status: EventStatus
    changes: tuple[ChangeKind, ...] = ()
    #: Claims the engine itself contributes (never includes the caller's own
    #: deterministic claims, which the existing pipeline already emits).
    ai_claims: tuple[PriceClaim, ...] = ()
    details: tuple[ClaimDetail, ...] = ()
    review: tuple[ReviewItem, ...] = ()
    ai_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cache_hit: bool = False
    fallback_reasons: tuple[str, ...] = ()
    evidence_hash: str = ""

    def as_dict(self) -> dict:
        return {
            "target_id": self.target_id,
            "status": self.status.value,
            "changes": [k.value for k in self.changes],
            "ai_claim_ids": [c.claim_id for c in self.ai_claims],
            "details": [d.as_dict() for d in self.details],
            "review": [r.as_dict() for r in self.review],
            "ai_calls": self.ai_calls,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cache_hit": self.cache_hit,
            "fallback_reasons": list(self.fallback_reasons),
            "evidence_hash": self.evidence_hash,
        }


# --------------------------------------------------------------------- engine

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def assess_deterministic(extracted: Optional[ExtractionResult], segments: list[str],
                         changes: tuple[ChangeKind, ...]) -> list[str]:
    """Reasons rules cannot be trusted with this change (empty = reliable)."""
    if extracted is None:
        return ["DETERMINISTIC_FAILED"]
    joined = " ".join(segments)
    claims = extracted.claims
    covered = {c.amount_thb for c in claims}
    covered |= {c.reference_price_thb for c in claims if c.reference_price_thb}
    reasons: list[str] = []
    missing = uncovered_amounts(joined, covered)
    if missing:
        reasons.append("UNCOVERED_AMOUNTS:" + ",".join(str(m) for m in missing))
    # A first sighting is a baseline, not an event: rules own it.  Conditions
    # and dates are only judged on a genuine change against a known baseline.
    if ChangeKind.FIRST_SEEN not in changes:
        if ChangeKind.CONDITIONS in changes and (claims or amounts_in(joined)):
            reasons.append("CONDITIONS_CHANGED")
        if ChangeKind.DATES in changes:
            claimed = {d for c in claims for d in (c.effective_from, c.effective_to) if d}
            if extract_dates(joined) - claimed:
                reasons.append("DATES_UNINTERPRETED")
    return reasons


def unaccounted_triggers(reasons: list[str], previous: Optional[Fingerprint],
                         current: Fingerprint, accepted, segments: list[str],
                         rule_claims) -> list[ReviewItem]:
    """Review items for fallback triggers the AI result did not actually answer.

    Covering the page's price amounts proves nothing about a changed offer
    condition or date, so each trigger is held to its own kind of evidence:

    * ``CONDITIONS_CHANGED`` needs a validated claim carrying a condition that is
      a verbatim quote from that claim's own excerpt AND is new relative to the
      last resolved page (not empty/null, not a restated old term);
    * ``DATES_UNINTERPRETED`` needs every date newly written on the page to be an
      effective date of some validated claim (rule or AI).
    """
    items: list[ReviewItem] = []
    if previous is None:
        return items
    if "CONDITIONS_CHANGED" in reasons:
        old = previous.conditions_text
        fresh = False
        for _claim, detail in accepted:
            index = detail.evidence_segment
            if index is None or not 0 <= index < len(segments):
                continue
            excerpt = segments[index].casefold()
            for condition in detail.conditions or ():
                if condition.casefold() not in excerpt:
                    continue
                pieces = [mask_text(p) for p in _CLAUSE_SPLIT.split(condition)]
                if any(piece and piece not in old for piece in pieces):
                    fresh = True
        if not fresh:
            items.append(ReviewItem(
                EventReviewReason.CONDITIONS_NOT_INTERPRETED,
                "offer conditions changed, but no validated claim carries a new "
                "quote-bound condition from the changed evidence"))
    if "DATES_UNINTERPRETED" in reasons:
        claimed = {d for c in rule_claims for d in (c.effective_from, c.effective_to) if d}
        claimed |= {d for claim, _detail in accepted
                    for d in (claim.effective_from, claim.effective_to) if d}
        missing = sorted((set(current.dates) - set(previous.dates)) - claimed)
        if missing:
            items.append(ReviewItem(
                EventReviewReason.DATE_NOT_INTERPRETED,
                "new date(s) written on the page are on no validated claim: "
                + ", ".join(missing)))
    return items


@dataclass(frozen=True, slots=True)
class _Payload:
    segments: tuple[str, ...]
    evidence_hash: str
    mode: str                      # "full" | "changed"


class PriceEventEngine:
    def __init__(self, config: Optional[PriceEventConfig] = None, *,
                 provider: Optional[LLMProvider] = None,
                 state: Optional[EventState] = None,
                 catalog: Optional[Catalog] = None,
                 clock: Callable[[], datetime] = _utc_now,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.config = config or PriceEventConfig()
        problems = self.config.validate()
        if problems:
            raise ValueError("invalid price-event config: " + "; ".join(problems))
        self.provider = provider if provider is not None else (
            resolve_provider(self.config.provider) if self.config.provider else None)
        self.state = state or EventState(cache_entries=self.config.cache_entries)
        self.catalog = catalog
        self.clock = clock
        self.sleep = sleep

    # ---- helpers -----------------------------------------------------------
    def estimate_tokens(self, text: str) -> int:
        return max(1, math.ceil(len(text) / self.config.chars_per_token))

    def _method(self) -> str:
        return f"ai_event:{self.config.extractor_version}:{self.config.prompt_version}"

    def _versions(self) -> str:
        return f"{self.config.extractor_version}|{self.config.prompt_version}"

    def _day(self) -> str:
        return thailand_business_date(self.clock()).isoformat()

    def _payload(self, target: SourceTarget, segments: list[str], mode: str) -> _Payload:
        context = f"{target.source_id}|{target.role.value}|{target.model_hint}"
        material = context + "\n" + "\n".join(segments)
        return _Payload(tuple(segments), content_id(material), mode)

    def _cache_key(self, payload: _Payload) -> str:
        return (f"{payload.evidence_hash}|{self.config.extractor_version}"
                f"|{self.config.prompt_version}")

    def _request(self, target: SourceTarget, payload: _Payload):
        return build_request(
            payload.segments, source_id=target.source_id,
            target_role=target.role.value, model_hint=target.model_hint,
            max_output_tokens=self.config.max_output_tokens,
            prompt_version=self.config.prompt_version)

    def _fits(self, target: SourceTarget, payload: _Payload) -> bool:
        request = self._request(target, payload)
        return (self.estimate_tokens(request.system + request.user)
                <= self.config.max_input_tokens)

    def _finish(self, result: ValidationResult, deterministic: Optional[ExtractionResult],
                ) -> tuple[tuple[PriceClaim, ...], tuple[ClaimDetail, ...]]:
        """Drop AI claims that merely restate a rule claim; keep their facts."""
        rule_by_key = {(c.trim_raw.upper(), c.amount_thb, c.price_type,
                        c.effective_from, c.effective_to): c
                       for c in (deterministic.claims if deterministic else ())}
        claims: list[PriceClaim] = []
        details: list[ClaimDetail] = []
        for claim, detail in result.accepted:
            twin = rule_by_key.get((claim.trim_raw.upper(), claim.amount_thb,
                                    claim.price_type, claim.effective_from,
                                    claim.effective_to))
            if twin is not None:
                details.append(ClaimDetail(
                    claim_id=twin.claim_id, origin="rules+ai",
                    conditions=detail.conditions, evidence_segment=detail.evidence_segment,
                    evidence_start=detail.evidence_start, evidence_end=detail.evidence_end,
                    evidence_hash=detail.evidence_hash, cache_hit=detail.cache_hit,
                    ignored_fields=detail.ignored_fields, p4_state=detail.p4_state))
                continue
            claims.append(claim)
            details.append(detail)
        return tuple(claims), tuple(details)

    # ---- AI call with cache, token limit, budget and bounded retries --------
    def _call_model(self, target: SourceTarget, payloads: list[_Payload]):
        """Returns ``(raw_claims, payload, cache_hit, calls, tin, tout, review)``.

        Only *validated* proposals are ever cached, so a cache hit is always a
        previously resolved interpretation.
        """
        cfg = self.config
        usable: Optional[_Payload] = None
        for payload in payloads:
            cached = self.state.cache_get(self._cache_key(payload))
            if cached is not None:
                return cached, payload, True, 0, 0, 0, ()
            if usable is None and self._fits(target, payload):
                usable = payload
        if usable is None:
            return None, payloads[-1], False, 0, 0, 0, (ReviewItem(
                EventReviewReason.TOKEN_LIMIT_EXCEEDED,
                f"evidence exceeds max_input_tokens={cfg.max_input_tokens}"),)
        if self.provider is None:
            return None, usable, False, 0, 0, 0, (ReviewItem(
                EventReviewReason.AI_UNAVAILABLE, "no LLM provider is configured"),)
        if cfg.require_durable_state and not self.state.durable:
            return None, usable, False, 0, 0, 0, (ReviewItem(
                EventReviewReason.STATE_NOT_DURABLE,
                "daily budgets need a persisted event state (--event-state); "
                "no provider call was made"),)

        request = self._request(target, usable)
        estimate_in = self.estimate_tokens(request.system + request.user)
        reserve = estimate_in + cfg.max_output_tokens
        calls = tokens_in = tokens_out = 0
        last: Optional[ReviewItem] = None
        for attempt in range(1 + cfg.max_retries):
            day = self._day()
            used_tokens, used_calls = self.state.usage(target.source_id, day)
            if (used_calls + 1 > cfg.call_budget(target.source_id)
                    or used_tokens + reserve > cfg.token_budget(target.source_id)):
                exhausted = ReviewItem(
                    EventReviewReason.TOKEN_BUDGET_EXHAUSTED,
                    f"{target.source_id} daily budget reached "
                    f"({used_tokens} tokens, {used_calls} calls today)")
                return (None, usable, False, calls, tokens_in, tokens_out,
                        ((last,) if last else ()) + (exhausted,))
            if attempt and cfg.retry_backoff_seconds:
                self.sleep(cfg.retry_backoff_seconds * (2 ** (attempt - 1)))
            # Reserve (and persist) BEFORE the call.  If the request fails, the
            # process dies, or usage is never reported, the reservation stands:
            # unknown usage is charged conservatively, never as zero.
            self.state.charge(target.source_id, day, reserve)
            self.state.save()
            calls += 1
            try:
                response = self.provider.complete(request)
            except LLMProviderError as exc:
                last = ReviewItem(EventReviewReason.PROVIDER_FAILED, str(exc))
                if exc.retryable:
                    continue
                break
            in_used = response.input_tokens if response.input_tokens is not None \
                else estimate_in
            out_used = response.output_tokens if response.output_tokens is not None \
                else self.estimate_tokens(response.text)
            # Settle the reservation to the reported usage.
            self.state.charge(target.source_id, day, in_used + out_used - reserve,
                              calls=0)
            self.state.save()
            tokens_in += in_used
            tokens_out += out_used
            try:
                raw_claims = parse_llm_claims(response.text)
            except MalformedOutputError as exc:
                last = ReviewItem(EventReviewReason.MALFORMED_OUTPUT, str(exc))
                continue
            return raw_claims, usable, False, calls, tokens_in, tokens_out, ()
        return None, usable, False, calls, tokens_in, tokens_out, (last,) if last else ()

    # ---- public entry point --------------------------------------------------
    def process(self, target: SourceTarget, result: FetchResult, *,
                deterministic: Optional[ExtractionResult] = None) -> EventOutcome:
        """Evaluate one fetched document.  Never raises for page content.

        ``deterministic`` lets a caller that already ran P3 pass its result in
        so the rules are not run twice.
        """
        cfg = self.config
        if not cfg.enabled:
            return EventOutcome(target.id, EventStatus.DISABLED)
        if result.not_modified or result.document is None:
            return EventOutcome(target.id, EventStatus.NOT_MODIFIED)
        if result.source_id not in cfg.ai_sources:
            return EventOutcome(target.id, EventStatus.SOURCE_NOT_ENABLED)

        document = result.document
        text = visible_text(result)
        segments = price_segments(text, cfg.window_chars)
        fingerprint = fingerprint_segments(segments)
        previous = self.state.baseline(target.id)
        changes = diff_fingerprints(previous, fingerprint)
        full = self._payload(target, segments, "full")

        if not changes:
            # Same price content as the last *resolved* baseline.  No model call
            # is made, but the validated interpretation of this exact full-page
            # fingerprint is re-validated against the fresh document and
            # re-emitted, so P5 still receives each new sighting.
            kept = self.state.interpretation(
                target.id, fingerprint.price_hash, self._versions())
            if not segments or kept is None:
                return EventOutcome(target.id, EventStatus.UNCHANGED, (),
                                    evidence_hash=full.evidence_hash)
            validated = validate_ai_claims(
                kept, segments=full.segments, document_text=text,
                document_id=document.document_id, source_id=result.source_id,
                evidence_hash=full.evidence_hash, extraction_method=self._method(),
                catalog=self.catalog, cache_hit=True, target_role=target.role)
            claims, details = self._finish(validated, deterministic)
            return EventOutcome(target.id, EventStatus.UNCHANGED, (), claims, details,
                                validated.review, cache_hit=True,
                                evidence_hash=full.evidence_hash)

        if deterministic is None:
            try:
                deterministic = extract_oem_price_claims(target, result)
            except ExtractionError:
                deterministic = None
        reasons = assess_deterministic(deterministic, segments, changes)
        if not reasons:
            self.state.set_baseline(target.id, fingerprint)
            self.state.save()
            return EventOutcome(target.id, EventStatus.DETERMINISTIC, changes,
                                evidence_hash=full.evidence_hash)

        payloads = [full]
        if previous is not None:
            seen = set(previous.segment_hashes)
            changed = [s for s, h in zip(segments, fingerprint.segment_hashes)
                       if h not in seen]
            if changed and len(changed) < len(segments):
                payloads.append(self._payload(target, changed, "changed"))

        raw_claims, payload, cache_hit, calls, tin, tout, problems = \
            self._call_model(target, payloads)
        if raw_claims is None:
            # Unresolved: keep the old baseline so the change is retried.
            self.state.save()
            return EventOutcome(target.id, EventStatus.REVIEW, changes, review=problems,
                                ai_calls=calls, tokens_in=tin, tokens_out=tout,
                                fallback_reasons=tuple(reasons),
                                evidence_hash=payload.evidence_hash)

        validated = validate_ai_claims(
            raw_claims, segments=payload.segments, document_text=text,
            document_id=document.document_id, source_id=result.source_id,
            evidence_hash=payload.evidence_hash, extraction_method=self._method(),
            catalog=self.catalog, cache_hit=cache_hit, target_role=target.role)
        review = list(validated.review)
        accepted_raw = list(validated.accepted_raw)
        final = validated
        if payload.mode == "changed":
            # Only the changed excerpts were sent.  Rebuild the interpretation of
            # the WHOLE page: proposals that were already resolved for the prior
            # baseline are carried over if they still validate, then everything
            # is re-validated against the full excerpt set (fresh proposals first,
            # so their facts win over a carried duplicate).
            carried = []
            if previous is not None:
                carried = self.state.interpretation(
                    target.id, previous.price_hash, self._versions()) or []
            final = validate_ai_claims(
                [*accepted_raw, *carried], segments=full.segments, document_text=text,
                document_id=document.document_id, source_id=result.source_id,
                evidence_hash=payload.evidence_hash, extraction_method=self._method(),
                catalog=self.catalog, cache_hit=cache_hit, target_role=target.role)
        claims, details = self._finish(final, deterministic)

        # Resolved = nothing was rejected, every plausible vehicle price in the
        # page's price excerpts is covered by a rule or validated AI claim, AND
        # each fallback trigger (changed conditions / dates) was answered.
        covered = {c.amount_thb for c in (deterministic.claims if deterministic else ())}
        covered |= {c.reference_price_thb for c in (deterministic.claims if deterministic else ())
                    if c.reference_price_thb}
        for claim, _detail in final.accepted:
            covered.add(claim.amount_thb)
            if claim.reference_price_thb:
                covered.add(claim.reference_price_thb)
        missing = uncovered_amounts(" ".join(segments), covered)
        if missing:
            review.append(ReviewItem(
                EventReviewReason.UNCOVERED_AMOUNT,
                "no validated claim covers: " + ", ".join(f"{m:,}" for m in missing)))
        # Amount coverage does not prove a changed condition/date was read.
        review.extend(unaccounted_triggers(
            reasons, previous, fingerprint, final.accepted, segments,
            deterministic.claims if deterministic else ()))

        if review:
            # Fail closed: keep the old baseline (the change is retried on the
            # next observation), cache nothing, but still hand over whatever
            # did validate so it is not lost.
            self.state.save()
            return EventOutcome(
                target.id, EventStatus.REVIEW, changes, claims, details, tuple(review),
                ai_calls=calls, tokens_in=tin, tokens_out=tout, cache_hit=cache_hit,
                fallback_reasons=tuple(reasons), evidence_hash=payload.evidence_hash)

        if not cache_hit:
            self.state.cache_put(self._cache_key(payload), accepted_raw)
        self.state.set_interpretation(
            target.id, fingerprint.price_hash, self._versions(),
            list(final.accepted_raw))
        self.state.set_baseline(target.id, fingerprint)
        self.state.save()
        return EventOutcome(
            target.id, EventStatus.AI_EXTRACTED, changes, claims, details, (),
            ai_calls=calls, tokens_in=tin, tokens_out=tout,
            cache_hit=cache_hit, fallback_reasons=tuple(reasons),
            evidence_hash=payload.evidence_hash)
