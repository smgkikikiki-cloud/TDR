# PEE-2 — Offline shadow evaluation and price-event reliability

Status: implemented, offline only. Scope is PEE-2 of the approved roadmap lane
**P-1 (Thai pricing evidence/events)** in `docs/portfolio/TDR_MASTER_ROADMAP_V1.md`.
Chunk 3 is not started. PEE-1 (Chunk 1, accepted at `44cc35f2`) was changed by
exactly one follow-up (below): the validator fixes for the two findings this harness
raised. Nothing else in PEE-1, and nothing in P3/P4/P5/P6 or the source registry, changed.

PEE-2 answers one question before any real model is ever enabled: *if PEE-1 had
been watching these pages, what would it have accepted, missed, sent to review and
cost — and what would P5 have done with it?*

It adds **no provider, makes no network request** (a guard makes any socket use
fail), writes **no Price Ledger / Supabase / canonical data**, and does not touch
P5, P6, P3, P4 or the source registry.

## What was built

| Path | Purpose |
| --- | --- |
| `vehreg/price_event_shadow.py` | fixture loader + validator, replay provider, offline guard, runner, metrics, renderers |
| `tools/price_event_shadow.py` | CLI: write the four artifacts, `--check` for drift, `--enforce` for gates |
| `tests/fixtures/price_events/*.json` | 27 scenarios (one timeline each) with labels |
| `docs/price-intelligence/pee2/` | generated, deterministic: `report.md`, `timelines.md`, `timelines.json`, `evaluation.json` |
| `tests/test_price_event_shadow.py` | harness correctness, provenance rules, reproducibility, mutation checks, F1/F2 regressions, readiness |
| `tests/test_price_event_fact_binding.py` | table-driven validator tests: 17 legitimate facts accepted, 25 unsafe ones rejected |

```bash
python tools/price_event_shadow.py --out docs/price-intelligence/pee2           # (re)generate
python tools/price_event_shadow.py --out docs/price-intelligence/pee2 --check --enforce
python tools/price_event_shadow.py --out /tmp/x --in-per-mtok A --out-per-mtok B # what-if cost
```

## How a run works

For each scenario the runner replays its observations in time order through the real
`extract_oem_price_claims` (P3), `PriceEventEngine` (PEE-1, with the clock set to each
observation time and a real on-disk state file in a temp directory), `match_trim_diagnostic`
(P4, live catalog) and `reconcile_one` (P5, with a seeded in-memory ledger and one shared
`CandidateBook`). The "model" is a **replay provider**: it can only return what the fixture
scripts for that observation; an unscripted call raises and is counted, so the engine fails
closed instead of the harness inventing a reply.

## Fixtures: what they are, and what they are not

Every scenario declares `provenance`: `evidence_kind`, `rights`, `label_status`, and for
reconstructed evidence its `source_refs`. The loader rejects (tests cover each case):

* `OWNER_LABELLED` without `labelled_by` + `labelled_at`, and a proposed label carrying a sign-off;
* `RECORDED_SNAPSHOT` without `capture.url`, `captured_at`, `permission_basis` and
  `robots_checked: true`;
* naive timestamps, non-increasing time, a first observation not labelled `baseline`,
  unknown config keys, a missing permission basis.

**Honest state of the corpus.** The repository holds no recorded raw OEM page snapshots and
no owner-labelled price-event golden set, so:

* 8 scenarios are `RECONSTRUCTED_FROM_PILOT_NOTES`: short factual statements re-typed from
  `P3_LIVE_PILOT_2026_09_09.md` and the admin campaign record, wrapped in synthetic page chrome.
  No third-party page text is stored.
* 19 scenarios are `SYNTHETIC_ADVERSARIAL`: invented to probe a specific failure.
* **0 scenarios are owner-labelled and 0 are recorded snapshots.** Every label is
  `PROPOSED_PENDING_OWNER_REVIEW`; I wrote them from the documented semantics (P0/P3/P5 docs,
  roadmap P-1 rules), not from engine output, but they are mine until the owner signs them.
  Every generated report says this before any number.

To use real evidence: drop a scenario JSON into `tests/fixtures/price_events/` with
`html_file` pointing at the permission-cleared snapshot, `evidence_kind: RECORDED_SNAPSHOT`
with its `capture` block, and `label_status: OWNER_LABELLED` once signed. The report then
breaks out an owner-labelled summary separately.

## Labels and metrics

Per observation the fixture states `expect.event` (`NONE`/`NEW`/`PENDING_RETRY`),
`disposition`, the exact set of `claims` the engine should emit then, `forbidden` claims it
must never emit, optional `tolerated` less-specific claims, required `conditions`, `max_ai_calls`,
and P5 expectations (`p5`, `p5_forbidden`, and `p5_never` for claims that must not reach P5 at
all). A scenario may carry `regression_for` (the former finding it now guards). Metrics (all in
`report.md`):

* **Event detection** — recall of labelled events, missed events, *lost pending retries* (an
  unresolved change that is not re-flagged), false events on unchanged pages.
* **Claims** — coverage, precision, **false accepts** (emitted but not labelled correct, split
  rule/AI), **forbidden hits** (emitted although explicitly wrong), missed claims.
* **Dispositions** — mismatches, **unsafe resolves** (resolved where the label requires REVIEW),
  false reviews.
* **Review load** — review rate, items per 100 observations, by reason.
* **Distinct price events** — a stream's *value changing* (absence carries the last value
  forward), versus the scrape count: "a price event is not a count of scrapes/reposts".
* **P5** — labelled dispositions, and outcomes the labels forbid (a rejected claim reaching P5
  at all, or reaching `CONFIRMED_REPLACEMENT`).
* **Stored claims** — after each run the engine's success cache and stored interpretation (what is
  re-emitted on every later fetch) are audited: a claim the labels never accept must be in neither.
* **Estimated usage** — calls, cache hits, tokens, and a naive "call the model on every fetch"
  baseline. No token price is assumed; cost appears only if both rates are supplied.

### Proposed gates (not adopted)

Zero tolerance on every safety counter (false accepts, forbidden hits, unsafe resolves, lost
pending, missed/false events, P5 mismatches/forbidden outcomes, forbidden claims stored, disposition
mismatches, budget violations, unscripted calls). They are computed over the **regression**
scenarios — everything that is not an OPEN finding (the mechanism stays for future findings; none
is open now) — so CI detects new regressions.

### Regression PASS is not operational readiness

The report and the CLI output carry two separate verdicts:

* **Regression gates** — "does the engine still behave as the labelled scenarios require?".
  `--enforce` exits non-zero when this fails.
* **Operational readiness** — **BLOCKED** unless every evidence requirement is met, and even then
  only `AWAITING_OWNER_AUTHORIZATION`: the harness can never emit READY, because authorization is
  the owner's decision made outside it. Requirements: regression gates pass; no open finding;
  owner-labelled scenarios, owner-labelled permission-cleared recorded snapshots, and distinct
  recorded sources at or above proposed minimums (30 / 10 / 3 — proposals, not adopted); explicit
  owner authorization. Today: 0 / 0 / 0 / not granted → **BLOCKED**.

This is reporting clarity only; it activates no gate and gates nothing in production.

## Results (seed corpus, 27 scenarios / 80 scrapes — see `pee2/report.md`)

* **Regression gates: all pass.** 0 false accepts, 0 forbidden claims accepted, 0 unsafe resolves,
  0 forbidden claims in the success cache / stored interpretation, 0 of 19 P5-forbidden checks hit,
  0 missed or false events, 33/33 labelled events detected, 21/21 distinct price events matched
  (80 scrapes → 21 events), P5 16/16 as labelled.
* **Readiness: BLOCKED** (see above).
* The AI-read price is still confirmed by P5 on a fresh observation 25h later with **zero** extra
  model calls (s16), and an eight-scrape noisy timeline still yields exactly one event with no AI call
  (s12).
* **Review load rose, by design.** Reconstructed pages: 5.9% of observations in REVIEW, 23.5 AI calls /
  100. Adversarial pages: 50% REVIEW, 89 calls / 100 (every rejected proposal keeps the change pending
  and is retried). Overall 31% REVIEW, 50 review items / 80 scrapes, 49 AI calls, ~41% fewer input
  tokens than calling the model on every fetch. The corpus is adversarial-heavy: do not extrapolate.

## Findings PEE2-F1 and PEE2-F2 — fixed in the PEE-1 validator

Both were reproduced by this harness (scenarios `s17`–`s22`), reported as OPEN, and then fixed in
`vehreg/price_event_validate.py` only (`bind_fact`; prompt `price-event-v2`). P4, P5 and the engine
flow are untouched. The six scenarios are now ordinary regressions inside the gates.

**F1 — price type needs affirmative evidence.** `LIST_PRICE` is accepted only when the fact's own
wording says recommended retail / list price (`ราคาขายปลีกแนะนำ`, `ราคาขายปลีก`, `ราคาแนะนำ`, MSRP,
RRP, "recommended/suggested/retail/list price"). Wording is read from a closed vocabulary in two
places only: between the trim and the amount, and the wording that *adjoins* the amount afterwards.
Campaign, finance, estimated and introductory wording classify the price (and must match the type the
model claims); restricted-audience, eco-sticker, dealer and previous/regular-price wording, any
unrecognised word between trim and amount, and conditional wording send the claim to REVIEW; a bare
"ราคา"/"Price" is "unproven". Wording that directly precedes the *next* price is that price's label
(not leaked), and the tail window stops at the next price or the next repetition of the model.

**F2 — one local price fact.** The quote must read `<model> <trim> <price wording> <amount>`: the
text before the trim, back to the previous price, must be exactly the claimed model; the trim must lie
between the previous price and this one; and the wording between trim and amount must be recognised.
Swapped pairs, another model's price, a model named once for several prices ("shared row") and a
reference amount claimed on its own all fail closed with `FACT_NOT_BOUND`. A row that repeats the
model for each price binds each price correctly.

### Owner policy decisions surfaced (not decided here)

These fail closed today; each is a judgement an owner may want to relax or tighten:

1. **Bare "ราคา"/"Price" as MSRP.** Accepted only on a registered `PRICE_LIST` target (mirrors P3,
   which treats a price-list card's "Price" as the list price); rejected elsewhere (`s26`).
2. **Shared-model rows** (`MAX+ … 699,000 ULTRA … 789,000`): the later price is refused until the
   model is written with it (`s24`). Real OEM tables may need a safe row-header rule.
3. **Reference amounts** ("from 699,000") are accepted only as `reference_price_thb` of the offer,
   never as a separate LIST claim from the model (P3 already emits those).
4. **Restricted-audience campaign offers** (existing customers, students, …) go to REVIEW for every
   price type, since no `PriceType` represents them.
5. **Vocabulary coverage.** Thai/English price wording outside the closed list yields REVIEW. The list
   is conservative and will need extending from owner-reviewed real pages.

### Other observations (not defects in the accepted scope)

* **P3 drops a cross-month window** (`s04`). `21 August – 6 September 2026` is not a window P3's
  same-month parser reads, so the rule claims lose their dates while the AI claims carry them. The two
  coexist; the undated rule claims are labelled `tolerated` (less specific, not wrong) but P5 would see
  two competing values for the same scope. P3 is out of scope here.
* **Multi-model pages re-trigger the model** (`s06`). P3 reads only JAECOO 5 EV, so the other models'
  prices stay "uncovered" and *any* change on the page costs one call.
* **A rejected proposal blocks resolution** (`s09`). One bad proposal alongside a good one keeps the
  whole change in REVIEW until a retry succeeds (accepted C1-1 behaviour); the stricter validator makes
  review load more sensitive to model noise.
* **A last-updated date near a price** can hold a change in REVIEW (accepted Chunk 1 limitation).

## Not claimed

No live-page precision, no recall on unseen layouts, no real-model behaviour, no cost (no token
prices assumed), no owner approval of any label, and **no operational readiness**. The gates are
proposals. A result here is a sanity check on a corpus the author wrote; the two findings it raised
show it can miss things the author did not think to write down, and a green regression suite says
nothing about price-checker safety on real pages.
