"""PEE-2: offline shadow evaluation and reliability measurement for PEE-1.

Replays *prerecorded* price evidence through the unchanged PEE-1 engine and the
unchanged P3/P4/P5, with a scripted (replay) provider instead of a model, and
measures what the engine would have done:

* did it notice every real price/terms/date change, and only those?
* did it ever accept a claim the labels say is wrong (false accept)?
* did it fail closed (REVIEW) exactly where the labels say it must?
* what does P5's 24-hour rule do with the claims it produced?
* what would it cost: calls, cache hits, tokens, review load?

Nothing here touches the network (a guard makes any socket use fail), writes a
Price Ledger, calls P6, or runs a real model.  State lives in a temp directory.

Fixture honesty: every scenario declares where its evidence came from and who
labelled it.  The harness never upgrades a label: ``OWNER_LABELLED`` needs a
named labeller and date, ``RECORDED_SNAPSHOT`` needs capture/permission facts,
and every report states how many scenarios are of each kind, so a result on
reconstructed or synthetic evidence cannot be mistaken for a measurement on
owner-labelled recorded pages.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json
import math
from pathlib import Path
import socket
import tempfile
from typing import Any, Iterable, Iterator, Mapping, Optional

from .catalog import Catalog, DATA_DIR, DEFAULT_YEAR
from .price_event import (
    EventState,
    PriceEventConfig,
    PriceEventEngine,
    price_segments,
    visible_text,
)
from .price_extract import ExtractionError, ExtractionResult, extract_oem_price_claims
from .price_fetch import FetchResult, FetchState
from .price_llm import (
    LLMProviderError,
    LLMResponse,
    SYSTEM_PROMPT,
    build_request,
)
from .price_match import match_trim_diagnostic
from .price_reconcile import (
    CandidateBook,
    ReconcileObservation,
    reconcile_one,
)
from .price_sources import SourceTarget, TargetRole
from .pricefeed import PriceClaim, SourceDocument, content_id
from .pricing import PriceLedger, PriceRecord, PriceType

SCHEMA_VERSION = 1
REPORT_VERSION = 1
FIXTURE_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "price_events"

EVIDENCE_KINDS = ("RECORDED_SNAPSHOT", "RECONSTRUCTED_FROM_PILOT_NOTES",
                  "SYNTHETIC_ADVERSARIAL")
LABEL_STATUSES = ("OWNER_LABELLED", "PROPOSED_PENDING_OWNER_REVIEW")
EVENT_LABELS = ("NONE", "NEW", "PENDING_RETRY")
DISPOSITIONS = ("UNCHANGED", "DETERMINISTIC", "AI_EXTRACTED", "REVIEW")
RESOLVED = frozenset({"UNCHANGED", "DETERMINISTIC", "AI_EXTRACTED"})
CONFIG_KEYS = frozenset({
    "max_input_tokens", "max_output_tokens", "daily_token_budget", "daily_call_budget",
    "max_retries", "extractor_version", "prompt_version", "window_chars"})

#: Proposed (NOT adopted) release gates.  Zero tolerance on the safety counters.
PROPOSED_GATES = {
    "false_accepts": 0,
    "forbidden_hits": 0,
    "unsafe_resolves": 0,
    "lost_pending_events": 0,
    "missed_events": 0,
    "false_events": 0,
    "unscripted_calls": 0,
    "unused_scripted_replies": 0,
    "p5_mismatches": 0,
    "p5_forbidden_hits": 0,
    "forbidden_stored": 0,
    "disposition_mismatches": 0,
    "ai_call_budget_violations": 0,
    "conditions_missed": 0,
    "missed_claims": 0,
}

#: Evidence an owner would have to supply before any operational use is even
#: discussed.  Proposed numbers, NOT adopted; the point is that today's count is 0.
PROPOSED_READINESS_MINIMUMS = {
    "owner_labelled_scenarios": 30,
    "recorded_snapshot_scenarios": 10,
    "distinct_sources": 3,
}

FINDING_TEXT = {
    "PEE2-F1": "LIST_PRICE was the default when no qualifier was recognised (promo, "
               "restricted-audience, eco-sticker, dealer or previous-price wording)",
    "PEE2-F2": "model, trim, amount and type were not required to form one local price "
               "fact (swapped pairs and cross-model attribution validated)",
}

SAFETY_COUNTERS = ("false_accepts", "forbidden_hits", "unsafe_resolves",
                   "lost_pending_events", "missed_events", "false_reviews",
                   "p5_mismatches", "p5_forbidden_hits", "forbidden_stored",
                   "disposition_mismatches",
                   "missed_claims")

FILLER = ("Lorem ipsum dolor sit amet consectetur adipiscing elit sed eiusmod "
          "tempor incididunt ut labore et dolore magna aliqua ") * 8


class ShadowFixtureError(ValueError):
    pass


class NetworkAttempted(AssertionError):
    pass


# ------------------------------------------------------------------ safety guard

@contextmanager
def offline_guard() -> Iterator[None]:
    """Make any network use raise.  The replay harness must never need one."""
    real_connect, real_lookup = socket.socket.connect, socket.getaddrinfo

    def blocked(*_a, **_k):
        raise NetworkAttempted("network access is forbidden in the PEE-2 shadow run")

    socket.socket.connect = blocked          # type: ignore[assignment]
    socket.getaddrinfo = blocked             # type: ignore[assignment]
    try:
        yield
    finally:
        socket.socket.connect = real_connect  # type: ignore[assignment]
        socket.getaddrinfo = real_lookup      # type: ignore[assignment]


# --------------------------------------------------------------------- fixtures

@dataclass(frozen=True, slots=True)
class Observation:
    id: str
    t: datetime
    html: str
    replies: tuple[Mapping, ...]
    expect: Mapping


@dataclass(frozen=True, slots=True)
class Scenario:
    id: str
    title: str
    provenance: Mapping
    source_id: str
    role: TargetRole
    model_hint: str
    url: str
    config: Mapping
    ledger_seed: tuple[Mapping, ...]
    p5: bool
    observations: tuple[Observation, ...]
    #: An OPEN defect in the engine this scenario deliberately reproduces.  Its
    #: counters are reported, but kept out of the regression gates.
    known_finding: Optional[Mapping] = None
    #: A former finding this scenario now guards as an ordinary regression.
    regression_for: Optional[str] = None

    @property
    def label_status(self) -> str:
        return self.provenance["label_status"]

    @property
    def evidence_kind(self) -> str:
        return self.provenance["evidence_kind"]


def wrap_page(body: str, noise: str = "") -> str:
    """Page chrome around a price block: nav/script/footer noise far from it."""
    return (f"<html><head><title>OEM</title><script>var t='{noise}'</script></head>"
            f"<body><nav>Home Models {noise}</nav><main>{FILLER}{body}{FILLER}</main>"
            f"<footer>Copyright {noise}</footer></body></html>")


def _claim_spec(raw: Mapping, where: str, problems: list[str]) -> Optional[tuple]:
    try:
        ptype = PriceType.parse(raw["type"])
        amount = int(raw["amount"])
        key = (str(raw["model"]).upper(), str(raw["trim"]).upper(), amount, ptype.value,
               raw.get("from"), raw.get("to"))
    except (KeyError, TypeError, ValueError, Exception) as exc:  # noqa: BLE001
        problems.append(f"{where}: bad claim spec {raw!r} ({exc})")
        return None
    return key


def validate_scenario(raw: Mapping, *, base: Path | None = None) -> list[str]:
    problems: list[str] = []
    sid = str(raw.get("id") or "")
    if not sid:
        problems.append("scenario id is required")
    if raw.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"{sid}: schema_version must be {SCHEMA_VERSION}")
    prov = raw.get("provenance")
    if not isinstance(prov, Mapping):
        return problems + [f"{sid}: provenance is required"]
    kind, status = prov.get("evidence_kind"), prov.get("label_status")
    if kind not in EVIDENCE_KINDS:
        problems.append(f"{sid}: evidence_kind must be one of {EVIDENCE_KINDS}")
    if status not in LABEL_STATUSES:
        problems.append(f"{sid}: label_status must be one of {LABEL_STATUSES}")
    if not prov.get("rights"):
        problems.append(f"{sid}: provenance.rights (permission basis) is required")
    if status == "OWNER_LABELLED" and not (prov.get("labelled_by") and prov.get("labelled_at")):
        problems.append(f"{sid}: OWNER_LABELLED requires labelled_by and labelled_at")
    if status == "PROPOSED_PENDING_OWNER_REVIEW" and (
            prov.get("labelled_by") or prov.get("labelled_at")):
        problems.append(f"{sid}: a proposed label must not carry an owner sign-off")
    if kind == "RECORDED_SNAPSHOT":
        capture = prov.get("capture") or {}
        for field_name in ("url", "captured_at", "permission_basis"):
            if not capture.get(field_name):
                problems.append(f"{sid}: RECORDED_SNAPSHOT needs capture.{field_name}")
        if capture.get("robots_checked") is not True:
            problems.append(f"{sid}: RECORDED_SNAPSHOT needs capture.robots_checked=true")
    if kind == "RECONSTRUCTED_FROM_PILOT_NOTES" and not prov.get("source_refs"):
        problems.append(f"{sid}: reconstructed evidence must cite source_refs")
    finding = raw.get("known_finding")
    if finding is not None and not (
            isinstance(finding, Mapping) and finding.get("id") and finding.get("summary")
            and finding.get("status") == "OPEN"):
        problems.append(f"{sid}: known_finding needs id, summary and status OPEN")
    try:
        TargetRole.parse(raw.get("role"))
    except ValueError as exc:
        problems.append(f"{sid}: {exc}")
    for key in raw.get("config", {}):
        if key not in CONFIG_KEYS:
            problems.append(f"{sid}: config key {key!r} is not allowed")
    observations = raw.get("observations")
    if not isinstance(observations, list) or len(observations) < 2:
        problems.append(f"{sid}: at least two observations are required")
        return problems
    last_t: Optional[datetime] = None
    seen: set[str] = set()
    for index, obs in enumerate(observations):
        oid = str(obs.get("id") or "")
        where = f"{sid}/{oid or index}"
        if not oid or oid in seen:
            problems.append(f"{where}: observation id missing or duplicated")
        seen.add(oid)
        try:
            t = datetime.fromisoformat(str(obs.get("t")))
        except ValueError:
            problems.append(f"{where}: t must be an ISO timestamp")
            continue
        if t.tzinfo is None:
            problems.append(f"{where}: t must be timezone-aware")
            continue
        if last_t is not None and t <= last_t:
            problems.append(f"{where}: observations must be strictly increasing in time")
        last_t = t
        sources = [k for k in ("html", "html_file", "body") if obs.get(k) is not None]
        if len(sources) != 1:
            problems.append(f"{where}: exactly one of html/html_file/body is required")
        if obs.get("html_file") and base is not None and not (base / obs["html_file"]).is_file():
            problems.append(f"{where}: html_file {obs['html_file']!r} not found")
        exp = obs.get("expect")
        if not isinstance(exp, Mapping):
            problems.append(f"{where}: expect is required")
            continue
        if exp.get("event", "NONE") not in EVENT_LABELS:
            problems.append(f"{where}: expect.event must be one of {EVENT_LABELS}")
        if exp.get("disposition") not in DISPOSITIONS:
            problems.append(f"{where}: expect.disposition must be one of {DISPOSITIONS}")
        if index == 0 and not exp.get("baseline"):
            problems.append(f"{where}: the first observation must be labelled baseline")
        for name in ("claims", "forbidden"):
            for spec in exp.get(name, []):
                _claim_spec(spec, f"{where}.{name}", problems)
        for reply in obs.get("ai_replies", []):
            if not isinstance(reply, Mapping) or not (
                    {"claims", "raw", "error"} & set(reply)):
                problems.append(f"{where}: ai_replies entries need claims/raw/error")
    return problems


def load_scenarios(directory: Path | str = FIXTURE_DIR) -> list[Scenario]:
    base = Path(directory)
    files = sorted(base.glob("*.json"))
    if not files:
        raise ShadowFixtureError(f"{base}: no scenario files")
    scenarios: list[Scenario] = []
    for path in files:
        raw = json.loads(path.read_text(encoding="utf-8"))
        problems = validate_scenario(raw, base=base)
        if problems:
            raise ShadowFixtureError(f"{path.name}: " + "; ".join(problems))
        observations = []
        for obs in raw["observations"]:
            if obs.get("html") is not None:
                html = obs["html"]
            elif obs.get("html_file") is not None:
                html = (base / obs["html_file"]).read_text(encoding="utf-8")
            else:
                html = wrap_page(obs["body"], obs.get("noise", ""))
            observations.append(Observation(
                id=obs["id"], t=datetime.fromisoformat(obs["t"]), html=html,
                replies=tuple(obs.get("ai_replies", [])), expect=obs["expect"]))
        scenarios.append(Scenario(
            id=raw["id"], title=raw.get("title", raw["id"]), provenance=raw["provenance"],
            source_id=raw.get("source_id", "official_jaecoo_th"),
            role=TargetRole.parse(raw["role"]), model_hint=raw.get("model_hint", ""),
            url=raw.get("url", "https://www.omodajaecoo.co.th/th"),
            config=raw.get("config", {}), ledger_seed=tuple(raw.get("ledger_seed", [])),
            p5=bool(raw.get("p5", False)), observations=tuple(observations),
            known_finding=raw.get("known_finding"),
            regression_for=raw.get("regression_for")))
    ids = [s.id for s in scenarios]
    if len(set(ids)) != len(ids):
        raise ShadowFixtureError("duplicate scenario ids")
    return scenarios


# ---------------------------------------------------------------- replay provider

class ReplayProvider:
    """A scripted stand-in for a model.  It can only replay what the fixture says."""

    def __init__(self) -> None:
        self.queue: list[Mapping] = []
        self.unscripted_calls = 0
        self.calls: list[int] = []        # request characters, per call

    def arm(self, replies: Iterable[Mapping]) -> None:
        self.queue = list(replies)

    def unused(self) -> int:
        return len(self.queue)

    def complete(self, request) -> LLMResponse:
        self.calls.append(len(request.system) + len(request.user))
        if not self.queue:
            self.unscripted_calls += 1
            raise LLMProviderError("unscripted provider call", retryable=False)
        reply = self.queue.pop(0)
        if "error" in reply:
            raise LLMProviderError(str(reply.get("message", reply["error"])),
                                   retryable=reply["error"] == "retryable")
        text = reply["raw"] if "raw" in reply else json.dumps(
            {"claims": reply["claims"]}, ensure_ascii=False)
        return LLMResponse(text, reply.get("input_tokens"), reply.get("output_tokens"),
                           "replay")


# ------------------------------------------------------------------------ runner

def claim_key(claim: PriceClaim) -> tuple:
    return (claim.model_raw.upper(), claim.trim_raw.upper(), claim.amount_thb,
            claim.price_type.value, claim.effective_from, claim.effective_to)


def _fetch_result(scn: Scenario, obs: Observation) -> FetchResult:
    raw = obs.html.encode("utf-8")
    digest = content_id(raw)
    stamp = obs.t.isoformat()
    document = SourceDocument(
        document_id=digest, source_id=scn.source_id, url=scn.url, content_hash=digest,
        first_seen_at=stamp, fetched_at=stamp)
    return FetchResult(
        target_id=f"shadow:{scn.id}", target_role=scn.role, source_id=scn.source_id,
        document=document, raw_body=raw, text=obs.html,
        state=FetchState(target_id=f"shadow:{scn.id}", content_hash=digest,
                         first_seen_at=stamp))


def _ledger(seed: Iterable[Mapping]) -> PriceLedger:
    ledger = PriceLedger(2026)
    for row in seed:
        ledger.records.append(PriceRecord(
            trim_id=row["trim_id"], amount_thb=int(row["amount"]),
            price_type=PriceType.parse(row["price_type"]),
            observed_at=row["observed_at"], source="official"))
    return ledger


def _spec_set(specs: Iterable[Mapping]) -> set[tuple]:
    problems: list[str] = []
    keys = {_claim_spec(s, "expect", problems) for s in specs}
    keys.discard(None)
    return keys  # type: ignore[return-value]


def run_scenario(scn: Scenario, catalog: Catalog) -> dict:
    """Replay one timeline.  Returns a JSON-serialisable, deterministic record."""
    provider = ReplayProvider()
    now = {"t": scn.observations[0].t}
    target = SourceTarget(id=f"shadow:{scn.id}", source_id=scn.source_id, url=scn.url,
                          role=scn.role, model_hint=scn.model_hint)
    book, ledger = CandidateBook(), _ledger(scn.ledger_seed)
    rows: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="pee2-") as tmp:
        config = PriceEventConfig(enabled=True, **scn.config)
        engine = PriceEventEngine(
            config, provider=provider, state=EventState(Path(tmp) / "event_state.json"),
            catalog=catalog, clock=lambda: now["t"], sleep=lambda _s: None)
        for obs in scn.observations:
            now["t"] = obs.t
            result = _fetch_result(scn, obs)
            try:
                rule: Optional[ExtractionResult] = extract_oem_price_claims(target, result)
            except ExtractionError:
                rule = None
            provider.arm(obs.replies)
            calls_before = len(provider.calls)
            outcome = engine.process(target, result, deterministic=rule)
            rule_claims = list(rule.claims) if rule else []
            all_claims = [*rule_claims, *outcome.ai_claims]
            p5_rows = []
            if scn.p5:
                for claim in all_claims:
                    match = match_trim_diagnostic(catalog, claim)
                    decision = reconcile_one(ReconcileObservation(
                        claim=claim, match=match, target_id=target.id,
                        target_role=scn.role, document=result.document),
                        ledger, candidate_book=book)
                    p5_rows.append({
                        "claim": list(claim_key(claim)),
                        "disposition": decision.disposition.value,
                        "reasons": sorted(r.value for r in decision.reasons)})
            segments = price_segments(visible_text(result), config.window_chars)
            naive = 0
            if segments and scn.source_id in config.ai_sources:
                request = build_request(
                    segments, source_id=scn.source_id, target_role=scn.role.value,
                    model_hint=scn.model_hint, max_output_tokens=config.max_output_tokens)
                naive = math.ceil(len(request.system + request.user) / config.chars_per_token)
            rows.append({
                "scenario": scn.id, "obs": obs.id, "t": obs.t.isoformat(),
                "status": outcome.status.value,
                "changes": sorted(k.value for k in outcome.changes),
                "fallback_reasons": list(outcome.fallback_reasons),
                "rule_claims": sorted(map(list, {claim_key(c) for c in rule_claims}),
                                      key=repr),
                "ai_claims": sorted(map(list, {claim_key(c) for c in outcome.ai_claims}),
                                    key=repr),
                "twin_claims": sorted(d.claim_id for d in outcome.details
                                      if d.origin == "rules+ai"),
                "conditions": sorted({c for d in outcome.details for c in (d.conditions or ())}),
                "review": sorted(r.reason.value for r in outcome.review),
                "ai_calls": outcome.ai_calls, "cache_hit": outcome.cache_hit,
                "tokens_in": outcome.tokens_in, "tokens_out": outcome.tokens_out,
                "naive_input_tokens": naive,
                "provider_calls": len(provider.calls) - calls_before,
                "unused_scripted_replies": provider.unused(),
                "p5": p5_rows,
            })
        unscripted = provider.unscripted_calls
        # What the engine kept: the success cache and the per-target interpretation
        # that is re-emitted on every later fetch.  Forbidden claims must be in neither.
        stored: set[tuple] = set()
        for store in ("cache", "interpretations"):
            for entry in engine.state.data[store].values():
                for raw in entry["claims"]:
                    try:
                        stored.add((str(raw.get("model_raw", "")).upper(),
                                    str(raw.get("trim_raw", "")).upper(),
                                    int(str(raw.get("amount_thb", 0)).replace(",", "")),
                                    str(raw.get("price_type", "")).upper(),
                                    raw.get("effective_from"), raw.get("effective_to")))
                    except (ValueError, AttributeError):
                        continue
    return {"id": scn.id, "title": scn.title, "role": scn.role.value,
            "evidence_kind": scn.evidence_kind, "label_status": scn.label_status,
            "unscripted_calls": unscripted,
            "stored_claims": sorted(map(list, stored)), "observations": rows}


# ------------------------------------------------------------------------ metrics

def _stream_events(per_obs: list[set[tuple]]) -> Counter:
    """Distinct price events: a stream's value *changing*, not scrapes or
    re-observations.  Absence is never a change (carry the last value forward)."""
    last: dict[tuple, tuple] = {}
    events: Counter = Counter()
    for index, claims in enumerate(per_obs):
        grouped: dict[tuple, set] = defaultdict(set)
        for model, trim, amount, ptype, start, end in claims:
            grouped[(model, trim, ptype)].add((amount, start or "", end or ""))
        for stream, values in sorted(grouped.items()):
            value = tuple(sorted(values))
            if stream in last:
                if last[stream] != value:
                    events[(stream, value)] += 1
            elif index > 0:
                events[(stream, value)] += 1
            last[stream] = value
    return events


def evaluate_scenario(scn: Scenario, record: dict) -> dict:
    """Score one replayed timeline against its labels."""
    totals: Counter = Counter()
    reasons: Counter = Counter()
    notes: list[dict] = []
    truth_obs: list[set[tuple]] = []
    engine_obs: list[set[tuple]] = []
    for obs, row in zip(scn.observations, record["observations"]):
        exp = obs.expect
        truth = _spec_set(exp.get("claims", []))
        forbidden = _spec_set(exp.get("forbidden", []))
        tolerated = _spec_set(exp.get("tolerated", []))
        rule = {tuple(c) for c in row["rule_claims"]}
        ai = {tuple(c) for c in row["ai_claims"]}
        emitted = rule | ai
        truth_obs.append(truth)
        # Tolerated (less specific but not wrong) claims do not make a new event.
        engine_obs.append(emitted - (tolerated - truth))
        baseline, label = bool(exp.get("baseline")), exp.get("event", "NONE")
        detected = bool(row["changes"])
        flag = lambda name, detail="": (totals.update([name]),            # noqa: E731
                                         notes.append({"obs": obs.id, "issue": name,
                                                       "detail": detail}))
        totals["observations"] += 1
        if not baseline:
            totals["non_baseline_observations"] += 1
            if label in ("NEW", "PENDING_RETRY"):
                totals["labelled_events"] += 1
                if detected:
                    totals["detected_events"] += 1
                    absent = sorted(set(exp.get("kinds", [])) - set(row["changes"]))
                    if absent:
                        flag("kind_mismatches", f"missing kinds {absent}")
                else:
                    flag("lost_pending_events" if label == "PENDING_RETRY" else "missed_events")
            elif detected:
                flag("false_events", f"changes {row['changes']}")
        expected_disp, status = exp["disposition"], row["status"]
        totals[f"status_{status}"] += 1
        if status != expected_disp:
            flag("disposition_mismatches", f"expected {expected_disp}, got {status}")
        if expected_disp == "REVIEW" and status in RESOLVED:
            flag("unsafe_resolves", f"{status} where labels require REVIEW")
        if expected_disp != "REVIEW" and status == "REVIEW":
            flag("false_reviews", ",".join(row["review"]))
        if status == "REVIEW":
            totals["review_observations"] += 1
        for reason in row["review"]:
            reasons[reason] += 1
            totals["review_items"] += 1
        if row["ai_calls"] > exp.get("max_ai_calls", 10 ** 9):
            flag("ai_call_budget_violations", f"{row['ai_calls']} calls")
        # claims -------------------------------------------------------------
        totals["labelled_claims"] += len(truth)
        totals["emitted_claims"] += len(emitted)
        totals["covered_claims"] += len(truth & emitted)
        if status in RESOLVED:
            totals["resolved_labelled_claims"] += len(truth)
            totals["resolved_covered_claims"] += len(truth & emitted)
        for name, group in (("rule", rule), ("ai", ai)):
            wrong = group - truth - tolerated
            totals[f"false_accepts_{name}"] += len(wrong)
            for key in sorted(wrong, key=repr):
                notes.append({"obs": obs.id, "issue": f"false_accept_{name}", "detail": list(key)})
        totals["tolerated_claims"] += len((emitted - truth) & tolerated)
        totals["false_accepts"] += len(emitted - truth - tolerated)
        totals["forbidden_hits"] += len(emitted & forbidden)
        missed = truth - emitted
        totals["missed_claims"] += len(missed)
        for key in sorted(missed, key=repr):
            notes.append({"obs": obs.id, "issue": "missed_claim", "detail": list(key)})
        for needle in exp.get("conditions", []):
            totals["labelled_conditions"] += 1
            if not any(needle.casefold() in c.casefold() for c in row["conditions"]):
                flag("conditions_missed", needle)
        # usage ----------------------------------------------------------------
        totals["ai_calls"] += row["ai_calls"]
        totals["cache_hits"] += int(row["cache_hit"])
        totals["tokens_in"] += row["tokens_in"]
        totals["tokens_out"] += row["tokens_out"]
        totals["naive_input_tokens"] += row["naive_input_tokens"]
        totals["naive_calls"] += int(row["naive_input_tokens"] > 0)
        totals["unused_scripted_replies"] += row["unused_scripted_replies"]
        # P5 -----------------------------------------------------------------------
        p5_expect = exp.get("p5", {})
        got = {f"{r['claim'][0]}|{r['claim'][1]}|{r['claim'][3]}|{r['claim'][2]}":
               r["disposition"] for r in row["p5"]}
        for key, want in sorted(p5_expect.items()):
            totals["p5_checked"] += 1
            if got.get(key) != want:
                flag("p5_mismatches", f"{key}: expected {want}, got {got.get(key)}")
        for key in sorted(exp.get("p5_never", [])):
            totals["p5_forbidden_checked"] += 1
            if key in got:
                flag("p5_forbidden_hits", f"{key}: a claim the labels reject reached P5")
        for key, bad in sorted(exp.get("p5_forbidden", {}).items()):
            totals["p5_forbidden_checked"] += 1
            if got.get(key) == bad:
                flag("p5_forbidden_hits", f"{key}: P5 reached {bad} for a claim the labels reject")
    totals["unscripted_calls"] += record["unscripted_calls"]
    banned, accepted_somewhere = set(), set()
    for obs in scn.observations:
        banned |= _spec_set(obs.expect.get("forbidden", []))
        accepted_somewhere |= _spec_set(obs.expect.get("claims", []))
        accepted_somewhere |= _spec_set(obs.expect.get("tolerated", []))
    # A claim is wrong to keep only if the labels never accept it at any time.
    banned -= accepted_somewhere
    for key in map(tuple, record.get("stored_claims", [])):
        if key in banned:
            totals["forbidden_stored"] += 1
            notes.append({"obs": "-", "issue": "forbidden_stored", "detail": list(key)})
    truth_events, engine_events = _stream_events(truth_obs), _stream_events(engine_obs)
    totals["truth_price_events"] = sum(truth_events.values())
    totals["engine_price_events"] = sum(engine_events.values())
    totals["matched_price_events"] = sum((truth_events & engine_events).values())
    return {"id": scn.id, "title": scn.title, "label_status": scn.label_status,
            "evidence_kind": scn.evidence_kind, "known_finding": scn.known_finding,
            "regression_for": scn.regression_for,
            "totals": dict(sorted(totals.items())),
            "review_reasons": dict(sorted(reasons.items())),
            "notes": notes}


def _ratio(num: int, den: int) -> Optional[float]:
    return round(num / den, 4) if den else None


def aggregate(evaluations: list[dict], *, gated: Optional[list[dict]] = None) -> dict:
    """Corpus metrics from per-scenario totals.

    Headline numbers cover every scenario; the proposed gates cover only the
    ``gated`` subset (default: all), i.e. scenarios that are not OPEN findings.
    """
    gate_total: Counter = Counter()
    for ev in (evaluations if gated is None else gated):
        gate_total.update(ev["totals"])
    total: Counter = Counter()
    reasons: Counter = Counter()
    for ev in evaluations:
        total.update(ev["totals"])
        reasons.update(ev["review_reasons"])
    t = total
    gate_values = {name: gate_total.get(name, 0) for name in PROPOSED_GATES}
    return {
        "scenarios": len(evaluations),
        "observations": t["observations"],
        "counts": {k: t.get(k, 0) for k in sorted(t)},
        "event_detection": {
            "labelled_events": t["labelled_events"], "detected": t["detected_events"],
            "recall": _ratio(t["detected_events"], t["labelled_events"]),
            "missed_events": t["missed_events"],
            "lost_pending_events": t["lost_pending_events"],
            "false_events": t["false_events"],
            "false_event_rate": _ratio(t["false_events"], t["non_baseline_observations"]),
        },
        "claims": {
            "labelled": t["labelled_claims"], "emitted": t["emitted_claims"],
            "coverage": _ratio(t["covered_claims"], t["labelled_claims"]),
            "coverage_when_resolved": _ratio(t["resolved_covered_claims"],
                                              t["resolved_labelled_claims"]),
            "precision": _ratio(t["emitted_claims"] - t["false_accepts"] - t["tolerated_claims"],
                                t["emitted_claims"]),
            "false_accepts": t["false_accepts"],
            "false_accepts_rule": t["false_accepts_rule"],
            "false_accepts_ai": t["false_accepts_ai"],
            "forbidden_hits": t["forbidden_hits"], "missed_claims": t["missed_claims"],
            "tolerated_less_specific": t["tolerated_claims"],
        },
        "dispositions": {
            "UNCHANGED": t["status_UNCHANGED"], "DETERMINISTIC": t["status_DETERMINISTIC"],
            "AI_EXTRACTED": t["status_AI_EXTRACTED"], "REVIEW": t["status_REVIEW"],
            "mismatches": t["disposition_mismatches"],
            "unsafe_resolves": t["unsafe_resolves"], "false_reviews": t["false_reviews"],
        },
        "review_load": {
            "review_observations": t["review_observations"],
            "review_rate": _ratio(t["review_observations"], t["observations"]),
            "review_items": t["review_items"],
            "items_per_100_observations": round(
                100 * t["review_items"] / t["observations"], 2) if t["observations"] else None,
            "by_reason": dict(sorted(reasons.items())),
        },
        "price_events": {
            "scrapes": t["observations"], "labelled_distinct_events": t["truth_price_events"],
            "engine_distinct_events": t["engine_price_events"],
            "matched": t["matched_price_events"],
            "precision": _ratio(t["matched_price_events"], t["engine_price_events"]),
            "recall": _ratio(t["matched_price_events"], t["truth_price_events"]),
        },
        "conditions": {"labelled": t["labelled_conditions"],
                       "missed": t["conditions_missed"]},
        "p5": {"checked": t["p5_checked"], "mismatches": t["p5_mismatches"],
               "forbidden_checked": t["p5_forbidden_checked"],
               "forbidden_hits": t["p5_forbidden_hits"]},
        "usage": {
            "ai_calls": t["ai_calls"], "cache_hits": t["cache_hits"],
            "tokens_in": t["tokens_in"], "tokens_out": t["tokens_out"],
            "naive_every_fetch_calls": t["naive_calls"],
            "naive_every_fetch_input_tokens": t["naive_input_tokens"],
            "calls_avoided_vs_naive": t["naive_calls"] - t["ai_calls"],
            "input_token_reduction_vs_naive": _ratio(
                t["naive_input_tokens"] - t["tokens_in"], t["naive_input_tokens"]),
            "ai_calls_per_100_observations": round(
                100 * t["ai_calls"] / t["observations"], 2) if t["observations"] else None,
        },
        "gates": {name: {"value": value, "limit": PROPOSED_GATES[name],
                         "pass": value <= PROPOSED_GATES[name]}
                  for name, value in gate_values.items()},
    }


def assess_readiness(scenarios: list[Scenario], summary: Mapping,
                     open_findings: list[dict]) -> dict:
    """Operational readiness is a different question from regression PASS.

    It is BLOCKED unless every evidence requirement is met, and even then it is
    only ``AWAITING_OWNER_AUTHORIZATION``: this tool can never grant READY,
    because authorization is the owner's decision made outside it.
    """
    owner = [s for s in scenarios if s.label_status == "OWNER_LABELLED"]
    recorded = [s for s in owner if s.evidence_kind == "RECORDED_SNAPSHOT"]
    sources = {s.source_id for s in recorded}
    need = PROPOSED_READINESS_MINIMUMS
    requirements = [
        ("regression_gates_pass", all(g["pass"] for g in summary["gates"].values()),
         "every regression gate passes"),
        ("no_open_findings", not open_findings, "no OPEN safety finding"),
        ("owner_labelled_scenarios", len(owner) >= need["owner_labelled_scenarios"],
         f"{len(owner)} owner-labelled scenarios; proposed minimum "
         f"{need['owner_labelled_scenarios']}"),
        ("recorded_snapshot_scenarios", len(recorded) >= need["recorded_snapshot_scenarios"],
         f"{len(recorded)} owner-labelled permission-cleared recorded snapshots; proposed "
         f"minimum {need['recorded_snapshot_scenarios']}"),
        ("distinct_sources", len(sources) >= need["distinct_sources"],
         f"{len(sources)} distinct recorded sources; proposed minimum "
         f"{need['distinct_sources']}"),
        ("owner_authorization", False,
         "no explicit owner authorization (granted outside this tool, never inferred)"),
    ]
    blocking = [name for name, met, _text in requirements if not met]
    evidence_met = all(met for name, met, _t in requirements if name != "owner_authorization")
    return {
        "status": "AWAITING_OWNER_AUTHORIZATION" if evidence_met else "BLOCKED",
        "requirements": [{"name": n, "met": m, "detail": t} for n, m, t in requirements],
        "blocking": blocking,
        "note": "A green regression suite is not safety acceptance and not operational "
                "readiness.",
    }


def estimate_cost(usage: Mapping, *, in_per_mtok: Optional[float],
                  out_per_mtok: Optional[float]) -> Optional[dict]:
    """What-if only.  No price is assumed: without both rates this is ``None``."""
    if in_per_mtok is None or out_per_mtok is None:
        return None
    engine = usage["tokens_in"] * in_per_mtok / 1e6 + usage["tokens_out"] * out_per_mtok / 1e6
    naive = usage["naive_every_fetch_input_tokens"] * in_per_mtok / 1e6
    return {"engine": round(engine, 6), "naive_input_only": round(naive, 6),
            "unit": "caller-supplied currency per 1M tokens"}


def run_corpus(directory: Path | str = FIXTURE_DIR, *, catalog: Optional[Catalog] = None,
               ) -> dict:
    """Run every scenario offline; returns timelines + evaluations + summary."""
    scenarios = load_scenarios(directory)
    catalog = catalog or Catalog.load(DATA_DIR, DEFAULT_YEAR)
    timelines, evaluations = [], []
    with offline_guard():
        for scn in scenarios:
            record = run_scenario(scn, catalog)
            timelines.append(record)
            evaluations.append(evaluate_scenario(scn, record))
    provenance = Counter(f"{s.evidence_kind}/{s.label_status}" for s in scenarios)
    chars_per_token = PriceEventConfig().chars_per_token
    owner = [e for e in evaluations if e["label_status"] == "OWNER_LABELLED"]
    regression = [e for e in evaluations if not e["known_finding"]]
    by_kind = {
        kind: aggregate([e for e in evaluations if e["evidence_kind"] == kind])
        for kind in sorted({e["evidence_kind"] for e in evaluations})}
    open_findings = [{
        "finding": e["known_finding"]["id"], "scenario": e["id"],
        "summary": e["known_finding"]["summary"],
        "counters": {k: e["totals"].get(k, 0) for k in SAFETY_COUNTERS
                     if e["totals"].get(k, 0)},
        "reproduces": any(e["totals"].get(k, 0) for k in
                          ("false_accepts", "forbidden_hits", "unsafe_resolves")),
    } for e in evaluations if e["known_finding"]]
    summary = aggregate(evaluations, gated=regression)
    return {
        "report_version": REPORT_VERSION,
        "provenance_counts": dict(sorted(provenance.items())),
        "usage_notes": {
            "fixed_system_prompt_tokens_per_call": math.ceil(
                len(SYSTEM_PROMPT) / chars_per_token),
            "chars_per_token_assumed": chars_per_token,
        },
        "summary": summary,
        "open_findings": open_findings,
        "readiness": assess_readiness(scenarios, summary, open_findings),
        "resolved_findings": {
            fid: {"summary": FINDING_TEXT.get(fid, ""),
                  "regression_scenarios": sorted(e["id"] for e in evaluations
                                                 if e["regression_for"] == fid)}
            for fid in sorted({e["regression_for"] for e in evaluations
                               if e["regression_for"]})},
        "summary_owner_labelled": aggregate(owner) if owner else None,
        "summary_by_evidence_kind": by_kind,
        "evaluations": evaluations,
        "timelines": timelines,
    }


# ----------------------------------------------------------------------- rendering

def dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _pct(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def render_timeline_md(timelines: list[dict]) -> str:
    out = ["# PEE-2 event timelines (generated, deterministic)", ""]
    for tl in timelines:
        out += [f"## {tl['id']} — {tl['title']}", "",
                f"role `{tl['role']}` · evidence `{tl['evidence_kind']}` · "
                f"labels `{tl['label_status']}`", "",
                "| obs | t | status | changes | rule | AI | review | calls | cache | P5 |",
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for row in tl["observations"]:
            def claims(items):
                return "<br>".join(f"{c[1]} {c[2]:,} {c[3].split('_')[0]}"
                                   + (f" {c[4] or ''}→{c[5] or ''}" if c[4] or c[5] else "")
                                   for c in items) or "–"
            p5 = "<br>".join(f"{r['claim'][1]} {r['claim'][3].split('_')[0]} "
                             f"{r['claim'][2]:,}: {r['disposition']}" for r in row["p5"]) or "–"
            out.append(
                f"| {row['obs']} | {row['t'][:16]} | {row['status']} | "
                f"{','.join(row['changes']) or '–'} | {claims(row['rule_claims'])} | "
                f"{claims(row['ai_claims'])} | {','.join(row['review']) or '–'} | "
                f"{row['ai_calls']} | {'hit' if row['cache_hit'] else '–'} | {p5} |")
        out.append("")
    return "\n".join(out)


def render_report_md(result: Mapping, *, cost: Optional[Mapping] = None) -> str:
    s = result["summary"]
    ev, cl, dp = s["event_detection"], s["claims"], s["dispositions"]
    rl, pe, us = s["review_load"], s["price_events"], s["usage"]
    lines = [
        "# PEE-2 offline shadow evaluation report (generated, deterministic)",
        "",
        "> **Read this first.** Every number below was measured by replaying fixtures",
        "> through the unchanged PEE-1 engine with a *scripted replay provider*. They",
        "> describe the **seed corpus only**. None of it is evidence of precision on live",
        "> pages, and no scenario here is owner-labelled recorded evidence.",
        "",
        "## Verdicts (two different questions)", "",
        f"* **Regression gates:** {'PASS' if all(g['pass'] for g in result['summary']['gates'].values()) else '**FAIL**'}"
        " — the engine still behaves as the labelled scenarios require.",
        f"* **Operational readiness: {result['readiness']['status']}** — "
        + result["readiness"]["note"],
        "",
        "| readiness requirement | met | detail |", "| --- | --- | --- |",
        *[f"| {r['name']} | {'yes' if r['met'] else '**NO**'} | {r['detail']} |"
          for r in result["readiness"]["requirements"]],
        "",
        "## Fixture provenance", "",
        "| evidence kind / label status | scenarios |", "| --- | --- |",
    ]
    lines += [f"| `{k}` | {v} |" for k, v in result["provenance_counts"].items()]
    owner = result["summary_owner_labelled"]
    lines += ["", ("**Owner-labelled subset measured separately: "
                   f"{owner['scenarios']} scenarios.**" if owner else
                   "**Owner-labelled scenarios: 0.** The metrics below are therefore "
                   "NOT owner-validated."), "",
              f"Scenarios: **{s['scenarios']}** · observations (scrapes): "
              f"**{s['observations']}**", "",
              "## Safety counters (proposed zero-tolerance gates — not adopted)", "",
              "Computed over the regression scenarios, i.e. every scenario that is not an "
              "OPEN finding below.", "",
              "| counter | value | limit | |", "| --- | --- | --- | --- |"]
    for name, gate in s["gates"].items():
        lines.append(f"| {name} | {gate['value']} | {gate['limit']} | "
                     f"{'PASS' if gate['pass'] else '**FAIL**'} |")
    findings = result["open_findings"]
    lines += ["", "## Findings in the PEE-1 engine", ""]
    if findings:
        lines += ["OPEN findings are excluded from the gates above (so the gates detect "
                  "*new* regressions) but included in every headline number below.", "",
                  "| finding | scenario | counters | still reproduces |",
                  "| --- | --- | --- | --- |"]
        for f in findings:
            counters = ", ".join(f"{k} {v}" for k, v in f["counters"].items()) or "–"
            lines.append(f"| {f['finding']} — {f['summary']} | {f['scenario']} | {counters} | "
                         f"{'yes' if f['reproduces'] else '**no — update fixture**'} |")
    else:
        lines.append("None open.")
    resolved = result.get("resolved_findings", {})
    if resolved:
        lines += ["", "Former findings, now enforced as ordinary regressions "
                  "(their scenarios are inside the gates):", ""]
        for fid, info in resolved.items():
            lines.append(f"* **{fid}** — {info['summary']}: "
                         + ", ".join(info["regression_scenarios"]))
    lines += [
        "", "## Event detection", "",
        f"* labelled events: {ev['labelled_events']} · detected: {ev['detected']} "
        f"(recall {_pct(ev['recall'])})",
        f"* missed: {ev['missed_events']} · lost pending retries: "
        f"{ev['lost_pending_events']} · false events on unchanged pages: "
        f"{ev['false_events']} (rate {_pct(ev['false_event_rate'])})",
        "", "## Claims", "",
        f"* labelled {cl['labelled']} · emitted {cl['emitted']} · coverage "
        f"{_pct(cl['coverage'])} (when the engine resolved: "
        f"{_pct(cl['coverage_when_resolved'])}) · precision {_pct(cl['precision'])}",
        f"* **false accepts {cl['false_accepts']}** (rule {cl['false_accepts_rule']}, "
        f"AI {cl['false_accepts_ai']}) · forbidden claims accepted "
        f"{cl['forbidden_hits']} · missed {cl['missed_claims']} · tolerated "
        f"less-specific rule claims {cl['tolerated_less_specific']}",
        f"* labelled conditions {s['conditions']['labelled']} · missed "
        f"{s['conditions']['missed']}",
        "", "## Dispositions & review load", "",
        f"* UNCHANGED {dp['UNCHANGED']} · DETERMINISTIC {dp['DETERMINISTIC']} · "
        f"AI_EXTRACTED {dp['AI_EXTRACTED']} · REVIEW {dp['REVIEW']}",
        f"* disposition mismatches {dp['mismatches']} · unsafe resolves "
        f"{dp['unsafe_resolves']} · false reviews {dp['false_reviews']}",
        f"* review rate {_pct(rl['review_rate'])} of observations · "
        f"{rl['items_per_100_observations']} review items / 100 observations",
        "* by reason: " + (", ".join(f"{k} ×{v}" for k, v in rl["by_reason"].items()) or "none"),
        "", "## Distinct price events (a price event is not a scrape count)", "",
        f"* {pe['scrapes']} scrapes → labelled distinct events "
        f"{pe['labelled_distinct_events']} · engine distinct events "
        f"{pe['engine_distinct_events']} · matched {pe['matched']} "
        f"(precision {_pct(pe['precision'])}, recall {_pct(pe['recall'])})",
        "", "## P5 24-hour semantics (unchanged P5, real catalog/P4)", "",
        f"* labelled P5 dispositions checked {s['p5']['checked']} · mismatches "
        f"{s['p5']['mismatches']}",
        f"* P5 outcomes the labels forbid (a rejected claim reaching P5 at all, or "
        f"reaching CONFIRMED_REPLACEMENT): checked {s['p5']['forbidden_checked']} · "
        f"reached {s['p5']['forbidden_hits']}",
        f"* rejected claims found in the engine's success cache or stored interpretation "
        f"(what is re-emitted later): {s['counts'].get('forbidden_stored', 0)}",
        "", "## Estimated usage (replay; no real model)", "",
        f"* AI calls {us['ai_calls']} ({us['ai_calls_per_100_observations']} / 100 "
        f"observations) · cache hits {us['cache_hits']}",
        f"* tokens in {us['tokens_in']:,} / out {us['tokens_out']:,} "
        "(provider-reported when scripted, else the engine's character estimate)",
        f"* naive baseline (call the model on every fetch with price text): "
        f"{us['naive_every_fetch_calls']} calls, "
        f"{us['naive_every_fetch_input_tokens']:,} input tokens → engine avoids "
        f"{us['calls_avoided_vs_naive']} calls, input-token reduction "
        f"{_pct(us['input_token_reduction_vs_naive'])}",
        f"* every call carries a fixed system prompt of about "
        f"{result['usage_notes']['fixed_system_prompt_tokens_per_call']} estimated tokens "
        "(the evidence excerpts are the small remainder), so call count, not excerpt size, "
        "drives cost",
    ]
    if cost:
        lines.append(f"* what-if cost ({cost['unit']}): engine {cost['engine']} vs naive "
                     f"(input only) {cost['naive_input_only']}")
    else:
        lines.append("* cost: not computed — no token prices were supplied and none are assumed")
    lines += ["", "## Same metrics by evidence kind", "",
              "The corpus is adversarial-heavy by design; the reconstructed-from-pilot-notes "
              "rows are the closer proxy for real page behaviour, and still are not live pages.",
              "",
              "| evidence kind | observations | AI calls / 100 obs | review rate | "
              "false accepts | missed events | false events |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    for kind, agg in result["summary_by_evidence_kind"].items():
        lines.append(
            f"| `{kind}` | {agg['observations']} | "
            f"{agg['usage']['ai_calls_per_100_observations']} | "
            f"{_pct(agg['review_load']['review_rate'])} | {agg['claims']['false_accepts']} | "
            f"{agg['event_detection']['missed_events']} | "
            f"{agg['event_detection']['false_events']} |")
    lines += ["", "## Findings per scenario", "",
              "| scenario | evidence / labels | issues |", "| --- | --- | --- |"]
    for e in result["evaluations"]:
        issues = Counter(n["issue"] for n in e["notes"])
        lines.append(f"| {e['id']} | {e['evidence_kind']} / {e['label_status']} | "
                     f"{', '.join(f'{k}×{v}' for k, v in sorted(issues.items())) or 'none'} |")
    return "\n".join(lines) + "\n"


ARTIFACT_NAMES = ("timelines.json", "evaluation.json", "timelines.md", "report.md")


def render_artifacts(result: Mapping, *, cost: Optional[Mapping] = None) -> dict[str, str]:
    """The four deterministic report artifacts for one corpus run."""
    evaluation = {k: v for k, v in result.items() if k != "timelines"}
    return {
        "timelines.json": dumps(result["timelines"]),
        "evaluation.json": dumps(evaluation),
        "timelines.md": render_timeline_md(result["timelines"]) + "\n",
        "report.md": render_report_md(result, cost=cost),
    }
