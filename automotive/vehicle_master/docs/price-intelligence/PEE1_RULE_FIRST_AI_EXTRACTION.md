# Price Event Engine — Chunk 1 (PEE-1): rule-first AI extraction

Status: implemented behind a feature flag that is **OFF by default**; offline QA
accepted (validator as amended by PEE2-F1/F2, see the end of this file).
**Operational readiness is BLOCKED** (`PEE2_OFFLINE_SHADOW_EVALUATION.md`): no live
provider, no owner-labelled evidence, no authorization. Chunk 3 is not started.

PEE-1 runs *beside* the Price Intelligence pipeline. It reuses P2 fetch evidence,
P3 deterministic extraction, P4 matching and P5 reconciliation and replaces none
of them. It writes no PriceLedger, catalog, Supabase or serving data, and it does
not touch P5's 24-hour confirmation rule or P6's approval/merge rules.

```text
P2 FetchResult
   ↓
price-relevant fingerprint ── unchanged ─────────────▶ 0 AI calls
   ↓ changed
P3 deterministic extraction ── reliable ─────────────▶ 0 AI calls
   ↓ cannot reliably interpret
cache(evidence_hash, extractor_version, prompt_version) ── hit ─▶ 0 AI calls
   ↓ miss
token limit → daily budget → provider adapter (bounded retries)
   ↓
evidence validation  ──▶  PriceClaim[]  → existing P4 → existing P5
                     └─▶  ReviewItem[]  (ambiguous / unsupported)
```

## Modules

| File | Role |
| --- | --- |
| `vehreg/price_event.py` | config + flag, fingerprints, state/cache/budget, orchestration |
| `vehreg/price_event_validate.py` | evidence validation, price-type rules, review reasons |
| `vehreg/price_llm.py` | provider adapter protocol, prompt, reply parser (no vendor code) |
| `tools/pricefetch_targets.py` | optional hook, only when the flag is on |

## Feature flag and configuration

`PriceEventConfig.enabled` defaults to `False`; the engine then returns
`DISABLED` without fingerprinting, writing state or calling anything. The CLI
reads `PriceEventConfig.from_env()`:

| Variable | Meaning (default) |
| --- | --- |
| `TDR_PRICE_EVENT_ENGINE` | `1` enables the engine (off) |
| `TDR_PRICE_EVENT_PROVIDER` | provider name registered via `price_llm.register_provider` (none) |
| `TDR_PRICE_EVENT_AI_SOURCES` | comma list of sources allowed to use AI (`official_jaecoo_th`) |
| `TDR_PRICE_EVENT_MAX_INPUT_TOKENS` / `_MAX_OUTPUT_TOKENS` | per-call limits (3000 / 1200) |
| `TDR_PRICE_EVENT_DAILY_TOKENS` / `_DAILY_CALLS` | per-source daily budgets (60000 / 200) |
| `TDR_PRICE_EVENT_MAX_RETRIES` | extra attempts after the first (2) |

When the flag is off, no other variable is parsed. Per-source budget overrides
(`source_token_budgets`, `source_call_budgets`) are config fields. No provider
is bundled: with none registered the AI fallback reports `AI_UNAVAILABLE` and
the existing rule-based path is unaffected.

## 1. Change detection

The visible text is cut into excerpts: a ±140-character window around every
amount, and around dates / offer-condition words / price words that sit within
300 characters of an amount. Navigation, scripts and unrelated copy do not
influence the result. The fingerprint hashes the excerpts overall and by kind:

* `AMOUNTS` — the multiset of amounts;
* `DATES` — literal date expressions;
* `CONDITIONS` — clauses with condition words, numbers/dates masked;
* `LABELS` — the remaining wording (trim names etc.), numbers/dates masked.

A change to conditions with an identical amount is therefore a real event.
The baseline advances only when the change was *resolved*: rules were reliable,
or the AI result is fully validated. A change is **unresolved** — status
`REVIEW`, old baseline kept, nothing cached, retried on the next observation —
when the AI step could not run (no provider, budget, token limit, non-durable
state, provider failure), when any proposal was rejected, or when a plausible
vehicle price in the excerpts is still not covered by a rule claim or a
validated AI claim (`UNCOVERED_AMOUNT`, including an empty `claims: []` reply
for a page that visibly carries a price), or when a fallback *trigger* was not
answered. Price coverage never answers a changed term or date:

* `CONDITIONS_CHANGED` needs a validated claim carrying a condition that is a
  verbatim quote from that claim's own excerpt **and** new relative to the last
  resolved page (null, empty, restated-old or other-excerpt conditions give
  `CONDITIONS_NOT_INTERPRETED`);
* `DATES_UNINTERPRETED` needs every date newly written on the page (fully
  specified, vs. the last resolved page) to be an effective date of some
  validated claim, else `DATE_NOT_INTERPRETED`.

The baseline therefore also keeps the previous masked condition text and
written dates. Proposals that did validate are still returned in `ai_claims`,
so a partial result is never lost.

## 2. Rules first

The caller's P3 result (or a fresh `extract_oem_price_claims`) is judged
reliable unless any of these holds:

* a plausible vehicle-price amount in the changed excerpts is not covered by a
  claim amount / reference amount (deposits, down payments and instalments are
  excluded);
* conditions changed against a known baseline (rules cannot read conditions);
* dates changed and a written date is not on any claim;
* P3 raised.

A first sighting is a baseline: only uncovered amounts can send it to AI.

## 3–4. AI output and validation

The model must return `{"claims": [...]}` with price type, amount, raw
brand/model/trim, optional dates, optional reference price, verbatim
`conditions` and a verbatim `evidence_text` (≤ 200 chars, ONE price fact: model,
trim, price wording, amount) citing an excerpt index. Everything is then
re-checked deterministically, in this order:

* quote exists in the cited excerpt, else `EVIDENCE_NOT_FOUND`; amount and
  reference amount are in the quote;
* deposits, down payments, instalments → `NOT_VEHICLE_PRICE`;
* brand/model wording is on the page (`MODEL_UNKNOWN`); a trim is stated and is a
  whole token in the quote (`MAX` ≠ `MAX+`; `TRIM_UNKNOWN` / `TRIM_NOT_IN_EVIDENCE`);
* **one local price fact** (`bind_fact`, `FACT_NOT_BOUND`): the text before the trim,
  back to the previous price, is exactly the claimed model; the trim lies between the
  previous price and this one; only recognised price wording separates trim and amount.
  Swapped pairs, another model's price, a model named once for several prices and a
  reference amount claimed on its own fail closed;
* **price type from wording, never from its absence**: a closed Thai/English vocabulary
  is read from the fact's own label zone (trim → amount) and the wording that adjoins the
  amount afterwards (stopping at the next price or the next repetition of the model, so a
  neighbour's wording does not leak; wording directly before the next price labels that
  price). Restricted-audience, eco-sticker, dealer and previous-price wording, unrecognised
  words between trim and amount, and conditional wording (for a price with no type
  wording) → REVIEW. Otherwise estimated / finance / campaign / introductory wording sets
  the type, and `LIST_PRICE` requires affirmative recommended-retail / list-price / MSRP
  wording (a bare "ราคา"/"Price" counts only on a registered `PRICE_LIST` target). A
  mismatch with the claimed type is `PRICE_TYPE_CONFLICT` / `PRICE_TYPE_UNSUPPORTED`;
  `UNKNOWN`, dealer and eco-sticker types are never accepted from an OEM page;
* dates must be fully written (day, month, year; Buddhist Era handled) in the
  excerpt — a year is never filled in; `from ≤ to`;
* each condition is a verbatim quote;
* ambiguous grades: P4 `AMBIGUOUS` when a catalog is supplied, else a grade that
  is a token-prefix of another claimed grade → `TRIM_AMBIGUOUS`.

Accepted proposals become ordinary `PriceClaim`s
(`extraction_method = ai_event:<extractor>:<prompt>`), with `trim_id`,
`campaign_hint` and `option_hint` empty. Model-supplied `trim_id` / `campaign_id`
/ `option_id` are ignored and listed in `ClaimDetail.ignored_fields`. Facts a
`PriceClaim` has no field for (conditions, evidence location) live in a sidecar
`ClaimDetail`; `conditions=None` means UNKNOWN, `()` means "none stated". An AI
claim that restates a rule claim is not duplicated — its conditions are attached
to the rule claim's id (`origin="rules+ai"`).

Rejected proposals are `ReviewItem(reason, detail, proposal)` and are never
emitted as claims. Matching stays P4 (`match_trim_diagnostic`) and
reconciliation stays P5 (`reconcile_one`): an AI campaign claim still gets
`CAMPAIGN_SCOPE_REQUIRED` because the engine never supplies a campaign or
option id.

## 5. Cache, limits, budgets, retries

* Cache key: `sha256(source|role|model_hint + excerpts)` + `extractor_version`
  + `prompt_version`. Only **validated** proposals of a **resolved** change are
  cached; a hit costs nothing and is re-validated against the current document.
* Full-page association: a resolved change also stores the validated proposals
  under the target's *full-page* price fingerprint. When only the changed
  excerpts fit the input limit, the proposals already resolved for the previous
  baseline are carried over and the whole page is re-validated, so the stored
  interpretation always describes the whole page. On an unchanged page it is
  re-validated against the fresh document and re-emitted (zero calls), so P5
  still receives each new sighting 24h+ later.
* Per-call input limit is estimated (`chars_per_token`, default 2.0 — Thai
  heavy); the full excerpt set is sent, falling back to only the changed
  excerpts, else `TOKEN_LIMIT_EXCEEDED` with no call.
* Daily budgets (tokens and calls) are per source per Thailand business day.
  Each attempt is **reserved and persisted before** the provider is invoked
  (estimated input + output cap); a successful reply settles to the reported
  usage, but a failed attempt keeps the full reservation, so unknown usage is
  never charged as zero.
* Provider calls require a persisted state file (`require_durable_state`,
  default on; CLI `--event-state`). With in-memory state the engine makes zero
  calls and reports `STATE_NOT_DURABLE`, so a fresh process cannot reset a cap.
* Retries: `1 + max_retries` attempts for retryable provider errors and
  malformed JSON; a non-retryable error stops at once.
* State is one JSON file only when `--event-state` / a path is supplied; a
  corrupt file raises (`EventStateError`) instead of silently resetting usage.

## Tests

All offline with scripted fake providers:

* `tests/test_price_event_engine.py` — engine behaviour: unchanged page, rule
  success, conditions-only change, ambiguous trims, missing/invented dates,
  hallucinated evidence, cache hit / key versioning / unchanged re-emission, budgets,
  token limit, bounded retries, P4→P5 reuse, state persistence, flag-gated CLI hook,
  and the C1-1…C1-4 / final-QA fail-closed regressions.
* `tests/test_price_event_fact_binding.py` — table-driven validator contract (F1/F2).
* `tests/test_price_event_shadow.py` + `tools/price_event_shadow.py` — PEE-2 replay
  evaluation, deterministic reports and the separate readiness verdict.

## Known limitations (Chunk 1)

* No concrete provider is shipped; a deployment registers one.
* Token counts are a character-based estimate unless the provider reports usage.
* Only the JAECOO source is AI-enabled by default.
* Review items are returned/printed, not yet fed into the P6 review queue.
* Fail-closed has a cost: a page that legitimately shows a plausible non-vehicle
  amount the model does not claim stays `REVIEW` and is retried (within budget)
  every observation until a human or a later chunk marks it ignorable. Likewise a
  price with unrecognised wording, a bare "ราคา"/"Price" off a price-list target, a
  shared-model row, or a nearby last-updated date goes to REVIEW rather than being
  accepted. `REVIEW` is not a confirmed price change.
* The price-wording vocabulary is a conservative closed list and will need extending
  from owner-reviewed real pages.
* AI claims reach P5 as ordinary `PriceClaim`s; campaign/finance claims still need
  campaign + option binding there. Review items are not yet fed to P6.
* Conditions are coarse clauses; a pure wording edit inside a clause containing
  a condition word is reported as `CONDITIONS`, not `LABELS`.
* Excerpts use fixed character windows, so unrelated text within ~140 characters
  of a price can register as a change (cheap false positives, never misses).

## Validator contract amended by PEE-2 (PEE2-F1 / PEE2-F2)

The shadow evaluation (`PEE2_OFFLINE_SHADOW_EVALUATION.md`) found that the original type and
identity checks defaulted to `LIST_PRICE` when no qualifier was recognised and accepted swapped or
cross-model trim/amount pairs. Both are fixed; the validator rules are those in sections 3–4
above. The prompt is `price-event-v2` and tells the model to quote one fact per price. P4 and P5
are unchanged. Original behaviour (superseded): type inferred from the words before the amount,
defaulting to LIST; model checked anywhere on the page.

