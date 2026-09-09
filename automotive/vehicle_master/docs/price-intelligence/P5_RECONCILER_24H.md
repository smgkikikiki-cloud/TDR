# Price Intelligence P5 — Reconciler + 24-hour replacement engine

Status: **implemented as staging-only engine**

P5 answers one question: given a source observation that P3 extracted and P4
resolved to a canonical MarketTrim, how does it relate to canonical PriceLedger
truth *without changing that truth yet*?

```text
P3 PriceClaim
  + P4 EXACT / AMBIGUOUS / UNMAPPED
  + SourceDocument / TargetRole
  + canonical PriceLedger
  + prior PriceCandidate staging state
        ↓
P5 reconcile
        ↓
NO_CHANGE
SAFE_CANDIDATE
PENDING_REPLACEMENT
CONFIRMED_REPLACEMENT
HISTORICAL_ONLY
REVIEW
CONFLICT
```

P5 never writes PriceLedger, vehicle identity, campaign definitions, Supabase or
serving projections.

## Candidate state

Fast-changing observation state remains outside canonical PriceRecord:

```text
NEW
PENDING_24H
CONFIRMED
REVERTED
REVIEW
```

`PriceCandidate` records:

- canonical trim + price type;
- explicit campaign + option scope when required;
- source + target (the observation stream);
- amount;
- first_seen_at / last_seen_at;
- observation_count;
- confirmed_at / reverted_at;
- claim ids;
- effective window/reference price evidence;
- the canonical amount it proposes to replace.

The candidate JSON schema is intentionally staging-only and serializable between
scheduled runs.

## The 24-hour rule

A replacement begins only when a different amount is observed inside the same
replacement scope.

```text
T0      canonical LIST = 699,000
T0      current OEM price page says 719,000
        → PENDING_24H
        → canonical/public remains 699,000

T0+23h  page again says 719,000
        → still PENDING_24H

T0+24h  page is actually fetched/observed again and still says 719,000
        → CONFIRMED
        → eligible for a later canonical-write phase
```

The timestamp of a later scheduler invocation is irrelevant. Confirmation needs
a later **observation**. Replaying the same T0 observation does not increment the
observation count and does not confirm anything.

If the same source/target stream returns to 699,000 before publication, the
candidate becomes REVERTED. If it changes 719,000 → 729,000, the 719,000 cycle is
REVERTED and a fresh 24-hour window starts for 729,000.

## Replacement scope

Ordinary single-price streams:

```text
(trim_id, price_type)
```

Campaign and finance alternatives:

```text
(trim_id, price_type, campaign_id, option_id)
```

Raw `campaign_hint` / `option_hint` strings do not create canonical scope.
Campaign/finance claims without explicit canonical binding go to REVIEW.
Different campaign options can therefore coexist without falsely superseding or
conflicting with each other.

## Document-role semantics

Source authority and document role remain separate.

`CURRENT_MODEL_PAGE` and `PRICE_LIST` may drive ordinary current-price changes.

`PROMOTION` may drive only explicitly scoped `CAMPAIGN_PRICE` / `FINANCE_PRICE`.
A promotion's “from 699,000” reference MSRP is evidence/context; it is not allowed
to replace the LIST stream.

`PRESS_RELEASE`, `LAUNCH_PAGE` and `BLOG` need a literal `effective_from` before
they may automatically replace a current price. Publication date and first-seen
date are not silently reinterpreted as effective dates.

This is why the current JAECOO 5 buyer guide may provide useful evidence without
silently making its ULTRA 789,000 wording the current MSRP.

## Explicit dates, age and absence

P0 semantics remain unchanged:

- `effective_to` is literal; after that date the observation is HISTORICAL_ONLY;
- no `effective_to` means open-ended for reconciliation purposes;
- old `published_at` alone never expires a price;
- page disappearance/absence never expires a price;
- future `effective_from` creates scheduled candidate evidence, not current truth.

A bound open-ended campaign can therefore remain active until explicit closure
or a replacement survives the 24-hour persistence rule.

## Price types are independent

P5 never treats different PriceTypes as contradictory replacement amounts.
Example:

```text
ULTRA 809,000 ESTIMATED_PRICE
ULTRA 789,000 LIST_PRICE
```

This is a type transition/new LIST stream, not a conflict and not a reason to
retract the estimate. Canonical history may retain both; serving logic chooses
LIST when it exists.

## Conflicts

P5 blocks a source contradicting itself across live current-role observations in
the same replacement scope during one batch.

It does **not** replace the existing Tier-A/Tier-B source-consensus policy in
`pricefeed.decide()`. Cross-source independence/consensus remains upstream policy.

Canonical PriceLedger rows with two different amounts at the same latest start
inside one scope are also returned as `CANONICAL_CONFLICT`, never guessed away.

## CLI

`tools/price_reconcile_batch.py` consumes a JSON batch produced by:

```bash
python tools/pricefetch_targets.py \
  --extract-prices \
  --match-trims \
  --out /tmp/fetch.json
```

Then:

```bash
python tools/price_reconcile_batch.py \
  --in /tmp/fetch.json \
  --candidate-state-in /tmp/price-candidates.json \
  --candidate-state-out /tmp/price-candidates.json \
  --out /tmp/reconcile.json
```

An optional legacy pricefeed decisions file may provide HUMAN-reviewed
`campaign_id + option_id` bindings. P5 uses those bindings only; it does not use
human decisions to silently override P4 trim identity.

## Still out of scope

P5 does not:

- append/close/retract PriceLedger rows;
- create campaign/option identities from raw copy;
- decide reviewer UI actions;
- open GitHub price PRs;
- publish serving projections;
- resolve Variant or DLT Trim Ledger identity.

The next write/promotion phase consumes only P5 candidates/dispositions that are
eligible under these rules.
