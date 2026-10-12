# PEE-2 — Offline shadow evaluation and price-event reliability

Status: implemented, offline only. Scope is PEE-2 of the approved roadmap lane
**P-1 (Thai pricing evidence/events)** in `docs/portfolio/TDR_MASTER_ROADMAP_V1.md`.
PEE-1 (Chunk 1, accepted at `44cc35f2`) is **unchanged** by this work; Chunk 3 is not
started.

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
| `tests/fixtures/price_events/*.json` | 23 scenarios (one timeline each) with labels |
| `docs/price-intelligence/pee2/` | generated, deterministic: `report.md`, `timelines.md`, `timelines.json`, `evaluation.json` |
| `tests/test_price_event_shadow.py` | harness correctness, provenance rules, reproducibility, mutation checks |

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
* 15 scenarios are `SYNTHETIC_ADVERSARIAL`: invented to probe a specific failure.
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
and P5 expectations (`p5`, `p5_forbidden`). Metrics (all in `report.md`):

* **Event detection** — recall of labelled events, missed events, *lost pending retries* (an
  unresolved change that is not re-flagged), false events on unchanged pages.
* **Claims** — coverage, precision, **false accepts** (emitted but not labelled correct, split
  rule/AI), **forbidden hits** (emitted although explicitly wrong), missed claims.
* **Dispositions** — mismatches, **unsafe resolves** (resolved where the label requires REVIEW),
  false reviews.
* **Review load** — review rate, items per 100 observations, by reason.
* **Distinct price events** — a stream's *value changing* (absence carries the last value
  forward), versus the scrape count: "a price event is not a count of scrapes/reposts".
* **P5** — labelled dispositions, and outcomes the labels forbid (a wrong claim reaching
  `CONFIRMED_REPLACEMENT`).
* **Estimated usage** — calls, cache hits, tokens, and a naive "call the model on every fetch"
  baseline. No token price is assumed; cost appears only if both rates are supplied.

### Proposed gates (not adopted)

Zero tolerance on every safety counter (false accepts, forbidden hits, unsafe resolves, lost
pending, missed/false events, P5 mismatches/forbidden, disposition mismatches, budget
violations, unscripted calls). They are computed over **regression** scenarios — every
scenario that is not an OPEN finding — so CI detects new regressions while the findings below
stay visible in all headline numbers.

## Results (seed corpus, 23 scenarios / 70 scrapes — see `pee2/report.md`)

* **Regression scenarios: all gates pass** — 0 false accepts, 0 unsafe resolves, 0 missed or
  false events, P5 24-hour semantics as labelled (16/16), including an *AI-read* price that
  P5 confirms on a fresh observation 25h later with **zero** extra model calls (the C1-2 property,
  measured end to end).
* Noise handling: an eight-scrape timeline with changing nav/scripts/timestamps on every page and
  one real price cut produced exactly **1 price event, 0 false events, 0 AI calls**.
* Fail-closed paths behave as labelled: terms-only change with an empty model reply → REVIEW then
  recovery on retry; invented end date → REVIEW; daily cap → REVIEW then recovery next Thai day;
  provider outage → 3 bounded attempts, REVIEW, recovery; hallucinated quote, deposit amount,
  bare `MAX` (P4-ambiguous), finance-conditional price, estimated-as-MSRP → all rejected.
* Missing offer ≠ zero: a promotion vanishing from a page yields no claim, no price event and no
  invented expiry.
* **Usage (replay):** 36 calls / 70 scrapes overall, but 23.5 / 100 on the reconstructed pages
  versus 77.8 / 100 on the adversarial ones (the corpus is adversarial-heavy; do not extrapolate).
  Versus calling the model on every fetch: 32 calls avoided, ~52% fewer input tokens. Each call
  carries a fixed ~891-token system prompt, so call count, not excerpt size, drives cost.

## OPEN FINDINGS in the accepted PEE-1 engine — not fixed here

These are reproduced by scenarios `s17`–`s22`, reported in every headline number, and excluded
only from the regression gates. Fixing them is a Chunk 1 change and needs a QA decision. A
proposed fix is listed, **not applied**.

**PEE2-F1 — `LIST_PRICE` is the default when no qualifier is recognised** (`s17`, `s18`, `s21`,
`s22`). `price_event_validate.price_context_class` only recognises a few marker families before
the amount and finance/conditional words after it. Promo wording after the amount
(`… 599,000 บาท (โปรโมชัน)`), restricted audiences (`… สำหรับลูกค้าเดิมเท่านั้น`), eco-sticker and
dealer-price wording are all accepted as `LIST_PRICE`, and the *correct* type (`CAMPAIGN_PRICE`,
…) is then refused. This violates roadmap P-1 ("ECO sticker ≠ MSRP") and the PDI scope that
excludes restricted offers. *Proposed fix:* require positive evidence for `LIST_PRICE` (an
MSRP/recommended-retail marker or a P3-style labelled card) rather than defaulting to it, extend
the before/after marker families (campaign, restricted audience, eco-sticker, dealer), and
send unproven cases to `PRICE_TYPE_UNSUPPORTED`.

**PEE2-F2 — trim/model and amount are not required to be adjacent** (`s19`, `s20`). The
validator checks that the trim and the amount each appear in the quote, and the model name
anywhere on the page, but not that they belong together. A swapped pair inside one table row
(`MAX+ ← 789,000`, `ULTRA ← 699,000`) validates, covers both amounts, and the change is
**marked resolved**; another model's price (`OMODA C5 EV MAX+ 709,000`) validates as JAECOO 5 EV.
Because resolved interpretations are re-emitted on every later fetch, the wrong claims are served
again with no model call and, in the replay, reach P5 `CONFIRMED_REPLACEMENT` on the second
observation 25h later (4 forbidden P5 outcomes in the corpus). *Proposed fix:* require the claimed
trim to be the nearest grade token before the amount (batch-known trims plus catalog trims when a
catalog is supplied), and require the claimed model to appear in the quote.

### Other observations (not defects in the accepted scope)

* **P3 drops a cross-month window** (`s04`). `21 August – 6 September 2026` is not a window P3's
  same-month parser reads, so the rule claims lose their dates while the AI claims carry them. The
  two coexist; the undated rule claims are labelled `tolerated` (less specific, not wrong) and do
  not count as false accepts, but P5 would see two competing values for the same scope. P3 is out
  of scope here.
* **Multi-model pages re-trigger the model** (`s06`). P3 reads only JAECOO 5 EV, so the other
  models' prices stay "uncovered" and *any* change on the page, including a JAECOO 5 price the
  rules read perfectly, costs one call. Carrying prior coverage forward would remove it.
* **A rejected proposal blocks resolution** (`s09`). One bad proposal alongside a good one keeps
  the whole change in REVIEW until a retry succeeds. That is the accepted C1-1 behaviour, but it
  makes review load sensitive to model noise.

## Not claimed

No live-page precision, no recall on unseen layouts, no real-model behaviour, no cost (no token
prices assumed), no owner approval of any label. The gates are proposals. A result here is an
upper-bound sanity check on a corpus the author wrote, and the findings above show it can
still miss things the author did not think to write down.
