# Price Intelligence P0 — Lifecycle Semantics

Status: **frozen for implementation**

This phase defines what a price observation means before any OEM crawler or
review UI is allowed to automate publication.

## Canonical truth vs staging

`PriceRecord` in `PriceLedger` remains canonical history.  Fast-changing
observation state does **not** belong in that row.  Crawlers and reconcilers work
with `PriceCandidate`; only a later canonical-write phase may append/supersede
ledger records.

```text
SourceDocument -> PriceClaim -> PriceCandidate -> review/reconcile
                                             -> PriceLedger (later phase)
```

## Frozen invariants

1. **Absence is not expiry.** A page disappearing, failing to fetch, or no longer
   mentioning a number does not close a price.
2. **Age is not expiry.** Article age, page age, `published_at`, and
   `first_seen_at` never manufacture an end date.
3. **No explicit end means open-ended.** A canonical row with no `effective_to`
   remains applicable until explicit evidence closes/retracts it or a confirmed
   replacement supersedes it in a later phase.
4. **Explicit end dates are honoured literally.** The price remains active on
   the stated final date and closes after it.
5. **Future prices are scheduled.** A future `effective_from` is not current
   price truth before that date.
6. **Retraction is correction, not expiry.** A wrong row stays auditable but no
   longer participates from `retracted_at` onward.
7. **Replacement never crosses price type.** `LIST_PRICE`, `CAMPAIGN_PRICE`,
   `ESTIMATED_PRICE`, etc. are separate timelines.
8. **Campaign alternatives may coexist.** `CAMPAIGN_PRICE` and `FINANCE_PRICE`
   need an explicit `campaign_id + option_id` before an automatic replacement
   scope exists.  Missing scope means review, never a guessed supersession.
9. **A new observation is not immediately truth.** Replacement candidates enter
   `PENDING_24H`.
10. **24 hours means persistence, not a timer.** The candidate must be fetched
    and observed again at or after `first_seen_at + 24h`.  A sleeping scheduler
    cannot confirm a candidate merely because the clock advanced.
11. **Reverted candidates never publish.** A transient number that disappears or
    reverts remains staging history only.
12. **Crawler state is not canonical state.** `NEW`, `PENDING_24H`, `CONFIRMED`,
    `REVERTED`, and `REVIEW` belong to candidates, not PriceLedger rows.

## Derived canonical state

We intentionally do not add a persisted `status` column to `PriceRecord`, because
that would duplicate `effective_from`, `effective_to`, and `retracted_at`.
Canonical state is derived:

```text
future effective_from              -> SCHEDULED
retracted_at reached               -> RETRACTED
explicit effective_to passed       -> CLOSED
otherwise                          -> ACTIVE
```

Validity is likewise derived:

```text
effective_to present -> EXPLICIT_WINDOW
effective_to absent  -> OPEN_ENDED
```

A later reconciler may record *why* a row ended (for example a confirmed
replacement), but it must not create a second independent truth for whether the
row is currently active.

## 24-hour replacement tolerance

Example:

```text
T0      current campaign price = 579,000
T0      source starts showing 599,000
        -> 599,000 PENDING_24H
        -> 579,000 remains canonical/current

T0+24h  source is fetched again and still shows 599,000
        -> candidate becomes eligible for CONFIRMED
        -> canonical supersession happens in a later write phase
```

If the latest actual observation is before `T0+24h`, the candidate is not
confirmable even if the current clock is days later.

## Replacement scope

For ordinary single-timeline price types:

```text
(trim_id, price_type)
```

For campaign/finance alternatives:

```text
(trim_id, price_type, campaign_id, option_id)
```

Without the explicit campaign/option identity, the automatic replacement scope
is `None`; a future reconciler must request review or use explicit evidence to
bind the relationship.

## Out of scope for P0

P0 does **not**:

- crawl OEM websites;
- classify raw page text;
- decide whether one source outranks another;
- mutate PriceLedger;
- write Supabase serving prices;
- implement the admin workbench.

Those phases consume these semantics rather than redefining them.
