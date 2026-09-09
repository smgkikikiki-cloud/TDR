# Price Intelligence P3 — OEM Extraction and Classification

Status: JAECOO 5 pilot implementation.

P3 consumes immutable P2 fetch evidence and emits `PriceClaim` rows.  A claim is
evidence, not canonical truth.  P3 does not match a claim to a canonical trim,
reconcile it against PriceLedger, or publish it.

```text
SourceTarget
   ↓
P2 FetchResult / SourceDocument
   ↓
P3 deterministic extractor
   ↓
PriceClaim[]
   ↓
P5 matcher / later reconciler
```

## JAECOO pilot source shapes

The first-party Thailand site currently exposes the useful price semantics in
three different page shapes, so P3 handles them separately rather than trying to
write one giant regex for every OEM page:

1. `PRICE_LIST` — multi-model homepage price cards.
   - `ราคาขายปลีกแนะนำ` / `Price` => `LIST_PRICE`
   - `ราคาคาดการณ์` / `Estimated Price` => `ESTIMATED_PRICE`
2. `BLOG` — JAECOO 5 buyer-guide variant table.
   - first figure in a variant row => `LIST_PRICE`
   - parenthetical promo/special figure => `CAMPAIGN_PRICE`
3. `PROMOTION` — promotion detail pages discovered from the P2 promotion index.
   - `ราคาพิเศษ` / `Special Price` => `CAMPAIGN_PRICE`
   - `(จากราคา ...)` => separate `LIST_PRICE` reference claim
   - `(จากราคาคาดการณ์ ...)` => separate `ESTIMATED_PRICE` reference claim

`CURRENT_MODEL_PAGE` and `PROMOTION_INDEX` are fetch/discovery evidence in P3;
they are not assumed to contain a price.

## Expiry rule

P3 obeys the P0 rule literally:

- if a page states an unambiguous campaign window, P3 may populate
  `effective_from` / `effective_to` on the campaign claim;
- if no end date is written, `effective_to` stays `None`;
- page age, publication date, crawl age, disappearance and wording such as
  "limited offer" never manufacture an expiry date.

The pilot understands literal same-month ranges in Thai and English, for example
`21–30 สิงหาคม 2569` and `21–30 August 2026`.  Unknown date wording stays
unknown instead of being guessed.

Reference-price claims do not inherit the campaign window.  A promotion saying
`599,000 from 699,000` means the 599,000 offer is windowed if the campaign says
so; it does not mean the 699,000 list price existed only during that campaign.

## Model and trim identity

P3 emits raw identity only:

```text
brand_raw = JAECOO
model_raw = JAECOO 5 EV
trim_raw  = MAX+ / ULTRA / LONG RANGE ...
```

A target `model_hint` may scope a dedicated buyer-guide parser, but it never
writes `trim_id` and never bypasses canonical matching.  Promotion pages have no
model hint and must identify `JAECOO 5 EV` from the page itself.

## Claim identity

Claim ids are deterministic from:

- document hash;
- raw model/trim identity;
- amount;
- price type;
- literal effective window;
- reference amount.

Re-running extraction on the same immutable document therefore yields the same
claim ids.

## P3 CLI

The P2 fetch command remains fetch-only by default.  P3 is opt-in:

```bash
python tools/pricefetch_targets.py \
  --source official_jaecoo_th \
  --follow-discovery \
  --extract-prices \
  --out /tmp/jaecoo-p3.json
```

The output may contain SourceDocuments, raw classified claims and extraction
warnings.  It still never writes PriceLedger, catalog, Supabase or serving data.

## Pilot expectations

The frozen P3 tests cover these semantics:

- homepage MAX+ `699,000` => `LIST_PRICE`;
- homepage ULTRA `809,000` explicitly estimated => `ESTIMATED_PRICE`;
- buyer-guide ULTRA `789,000` + special `669,000` => list + campaign claims;
- open-ended `MORE RAIN, MORE GAIN` MAX+ `599,000` / ULTRA `699,000` => campaign
  claims with no invented end date;
- BIG MOTOR SALE MAX+ `579,000` / ULTRA `669,000`, explicitly 21–30 Aug 2026 =>
  campaign claims with that literal window;
- deposit and monthly-installment numbers are not extracted as vehicle prices.

## Out of scope

P3 does not:

- decide whether a blog is stale versus a current model page;
- apply the 24-hour replacement state machine;
- resolve source disagreement;
- attach a campaign claim to a canonical campaign/option id;
- match raw trim names to MarketTrim ids;
- mutate PriceLedger;
- update the public site.

Those remain later phases so the evidence boundary stays auditable.
