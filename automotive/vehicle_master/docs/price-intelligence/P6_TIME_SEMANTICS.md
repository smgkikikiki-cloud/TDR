# P6 Price Intelligence time semantics

TDR Price Intelligence separates **instants** from **market calendar dates**. They are not interchangeable.

## 1. Observation and review fields are instants

The following fields remain offset-aware ISO timestamps:

- `SourceDocument.first_seen_at`
- `SourceDocument.fetched_at`
- `PriceCandidate.first_seen_at`
- `PriceCandidate.last_seen_at`
- `PriceCandidate.confirmed_at`
- `PriceCandidate.reverted_at`
- `PromotionDecision.reviewed_at`

The P5 24-hour debounce compares these timestamps as real instants. It never compares date-only values and it never confirms from wall-clock passage without a later observation.

## 2. Canonical price dates use the Thailand business calendar

Canonical PriceLedger stores `observed_at`, `effective_from`, and `effective_to` as `YYYY-MM-DD`. Whenever Price Intelligence must reduce a system-observed instant to one of those date-only fields, the instant is first converted to `Asia/Bangkok` and then reduced to a date.

Example:

```text
2026-09-09T18:30:00Z
= 2026-09-10T01:30:00+07:00
=> Thailand business date 2026-09-10
```

The same instant expressed with a different offset must produce the same canonical date.

P5 also uses the Thailand business date when comparing an observation to canonical rows or explicit campaign windows. This prevents a campaign ending on September 9 in Thailand from remaining live for seven extra hours merely because the fetch timestamp is stored in UTC.

## 3. Literal source dates are evidence and are never timezone-converted

If the source explicitly states a date/window and P3 extracts it into:

- `effective_from`
- `effective_to`

that value is preserved literally. It is already a market-calendar statement, not an instant.

For example, an OEM saying `effective_from = 2026-09-09` remains September 9 even if the page was first fetched after midnight Thailand time on September 10.

## 4. Inferred replacement start

When a confirmed replacement has no literal `effective_from`, P6 infers the canonical start from `confirmed_at` **after converting that instant to the Thailand business date**.

`observed_at` is derived separately from `first_seen_at`, also on the Thailand business calendar. Therefore:

```text
first seen   2026-09-08T18:30Z -> observed_at 2026-09-09
confirmed    2026-09-09T18:30Z -> effective_from 2026-09-10
```

The old canonical row closes on the previous calendar day (`2026-09-09`).

## 5. Naive timestamps are invalid

A timestamp without an offset is not an instant and must not drive P5/P6 time decisions. `2026-09-10T01:30:00` is therefore invalid; `2026-09-10T01:30:00+07:00` is valid.

## 6. Non-goals

This contract does **not** rewrite historical literal dates already present in PriceLedger, and it does not convert publication dates that are evidence supplied by a source. It only defines how Price Intelligence interprets observation/review instants and how those instants become date-only canonical facts.
