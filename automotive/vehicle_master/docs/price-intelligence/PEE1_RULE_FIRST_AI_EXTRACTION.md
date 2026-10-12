# Price Event Engine — Chunk 1 (PEE-1): rule-first AI extraction

Status: implemented behind a feature flag that is **OFF by default**. Chunks 2
and 3 are not started.

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
The baseline advances only when the change was *resolved* (rules were reliable,
or the AI result was validated). If the AI step could not run (no provider,
budget, token limit, provider failure) the old baseline is kept and the change
is retried on the next observation instead of being lost.

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
`conditions` and a verbatim `evidence_text` (≤ 200 chars, trim **and** amount)
citing an excerpt index. Everything is then re-checked deterministically:

* quote exists in the cited excerpt, else `EVIDENCE_NOT_FOUND`;
* amount / reference amount are in the quote; trim is a whole token in the
  quote (`MAX` ≠ `MAX+`); brand/model wording is on the page;
* dates must be fully written (day, month, year; Buddhist Era handled) in the
  excerpt — a year is never filled in; `from ≤ to`;
* each condition is a verbatim quote;
* price type vs. the words directly before the amount: *special / promotion /
  discount* → `CAMPAIGN_PRICE`; *financing* wording → `FINANCE_PRICE`;
  *estimated* → `ESTIMATED_PRICE`; `(from 699,000)` is a reference → list;
  otherwise `LIST_PRICE`. Mismatches are `PRICE_TYPE_CONFLICT` /
  `PRICE_TYPE_UNSUPPORTED`; `UNKNOWN`, dealer and eco-sticker types are not
  accepted from an OEM page;
* deposits, down payments, instalments → `NOT_VEHICLE_PRICE`;
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
  + `prompt_version`. A hit costs nothing and is re-validated against the
  current document. On an unchanged page the cached interpretation is
  re-emitted (zero calls) so P5 still receives a fresh sighting.
* Per-call input limit is estimated (`chars_per_token`, default 2.0 — Thai
  heavy); the full excerpt set is sent, falling back to only the changed
  excerpts, else `TOKEN_LIMIT_EXCEEDED` with no call.
* Daily budgets (tokens and calls) are per source per Thailand business day and
  are reserved *before* each attempt using the estimated input plus the output
  cap; provider-reported usage is charged afterwards.
* Retries: `1 + max_retries` attempts for retryable provider errors and
  malformed JSON; a non-retryable error stops at once.
* State is one JSON file only when `--event-state` / a path is supplied; a
  corrupt file raises (`EventStateError`) instead of silently resetting usage.

## Tests

`tests/test_price_event_engine.py` — all offline with scripted fake providers:
unchanged page, rule success, conditions-only change, MSRP vs campaign vs
finance, ambiguous trims (heuristic and P4), missing/invented dates,
hallucinated evidence, cache hit / key versioning / unchanged re-emission,
token and call budgets, token limit, bounded retries, P4→P5 reuse, state
persistence, and the flag-gated CLI hook.

## Known limitations (Chunk 1)

* No concrete provider is shipped; a deployment registers one.
* Token counts are a character-based estimate unless the provider reports usage.
* Only the JAECOO source is AI-enabled by default.
* Review items are returned/printed, not yet fed into the P6 review queue.
* Conditions are coarse clauses; a pure wording edit inside a clause containing
  a condition word is reported as `CONDITIONS`, not `LABELS`.
* Excerpts use fixed character windows, so unrelated text within ~140 characters
  of a price can register as a change (cheap false positives, never misses).
