# Price Intelligence P6 — Reviewed Promotion + Canonical Price PR

Status: **implementation**

P6 is the first phase allowed to change canonical market-price files. It sits
after P5 reconciliation and remains human gated.

```text
P2 fetch
  -> P3 PriceClaim
  -> P4 MarketTrim match
  -> P5 reconcile / 24h candidate state
  -> P6 review queue
       |- BIND campaign/option -> rerun P5
       `- APPROVE / REJECT promotable candidate
  -> P6 market-file write plan
  -> local commit
  -> pricefeed_guard + tests + market validate + serving dry-run
  -> push generated PR
  -> HUMAN PR MERGE
  -> later serving publication
```

## Frozen P6 rules

1. **P5 disposition is authority for eligibility.** P6 never rematches a trim,
   reclassifies document semantics, or bypasses a P5 REVIEW/CONFLICT.
2. **Only three dispositions are promotable:** `SAFE_CANDIDATE`,
   `CONFIRMED_REPLACEMENT`, and `HISTORICAL_ONLY`.
3. **Every canonical write needs a HUMAN promotion decision.** The P6 schema
   deliberately rejects `SYSTEM_EVIDENCE` and agent approval for now.
4. **PENDING_24H, REVERTED, REVIEW and CONFLICT cannot be overridden by an
   approval file.** Fix/rerun upstream instead.
5. **Campaign/finance requires canonical `campaign_id + option_id`.** A raw
   `campaign_hint` is display context only. Binding uses the existing pricefeed
   HUMAN decision audit file, then P5 is rerun.
6. **A reviewed new campaign identity may be created in the same promotion
   bundle.** Existing campaign definitions are never silently rewritten by the
   bot.
7. **Replacement is append + supersede.** The prior exact price stream receives
   an `effective_to`; the replacement is appended as a new row/file.
8. **Replacement never crosses PriceType.** Campaign/finance replacement is
   additionally scoped to exact campaign + option.
9. **Without a literal effective date, a confirmed replacement becomes
   effective on `confirmed_at` date.** `observed_at` retains the first-seen date.
   We therefore record both "when first noticed" and "when accepted as current"
   without inventing a true OEM effective date.
10. **A literal source effective date is preserved.** After 24h confirmation,
    historical resolution may be backdated to that explicit date because the
    source actually stated it.
11. **Price PRs change canonical `market/` files only.** P6 does not emit Phase-C
    canonical_state/outbox/shadow files and does not write Supabase.
12. **PR merge remains human.** No P6 path auto-merges or publishes serving data.

## Review queue

`tools/price_review_queue.py` consumes P5 candidate state + reconcile report +
P4 fetch batch. It emits two separate queues.

### Promotion review

A candidate that P5 says is promotable:

```json
{
  "candidate_id": "pcand:...",
  "disposition": "CONFIRMED_REPLACEMENT",
  "state": "CONFIRMED",
  "trim_id": "jaecoo.jaecoo_5_ev.j5.trim.max_plus_bev",
  "amount_thb": 719000,
  "price_type": "LIST_PRICE",
  "actions": ["APPROVE", "REJECT"]
}
```

### Binding review

A campaign claim P5 refused because canonical scope is missing:

```json
{
  "claim_id": "...",
  "trim_id": "...",
  "raw_campaign_hint": "MORE RAIN, MORE GAIN",
  "required_action": "BIND_CANONICAL_CAMPAIGN_OPTION_THEN_RERUN_P5"
}
```

The raw hint is never promoted by itself. A HUMAN decision supplies
`campaign_id` and `option_id`; P5 must then rerun and produce a candidate in that
canonical scope.

## Promotion decision bundle

```json
{
  "schema_version": 1,
  "decisions": [
    {
      "candidate_id": "pcand:...",
      "action": "APPROVE",
      "reviewer": "owner",
      "origin": "HUMAN",
      "reviewed_at": "2026-09-10T03:00:00+00:00",
      "notes": "source checked"
    }
  ],
  "create_campaigns": []
}
```

`create_campaigns` uses the existing canonical Campaign schema. It is for a new
reviewed identity only. If the id already exists, P6 refuses to rewrite it.

## Canonical dating on replacement

No explicit effective date:

```text
first_seen_at  2026-09-09 02:00Z
confirmed_at   2026-09-10 02:00Z

old row effective_to     2026-09-09
new row observed_at      2026-09-09
new row effective_from   2026-09-10
```

The old public truth therefore survives the 24h tolerance exactly as required.

Literal source date:

```text
source says effective_from = 2026-09-09
first seen                  = 2026-09-10
confirmed                   = 2026-09-11
```

After confirmation P6 records `effective_from=2026-09-09` and closes the prior
stream on 2026-09-08. That is not guessing: the date came from source evidence.

## Commands

Review queue:

```bash
python tools/price_review_queue.py \
  --candidate-state /tmp/price-candidates.json \
  --reconcile /tmp/jaecoo-reconcile.json \
  --fetch /tmp/jaecoo-fetch.json \
  --out /tmp/price-review.json
```

Dry-run promotion:

```bash
python tools/price_promote_batch.py \
  --candidate-state /tmp/price-candidates.json \
  --reconcile /tmp/jaecoo-reconcile.json \
  --fetch /tmp/jaecoo-fetch.json \
  --review /tmp/price-approvals.json \
  --manifest-out /tmp/price-promotion.json
```

Apply locally only:

```bash
python tools/price_promote_batch.py ... --apply
```

Generate guarded PR:

```bash
python tools/price_promotion_pr.py \
  --candidate-state /tmp/price-candidates.json \
  --reconcile /tmp/jaecoo-reconcile.json \
  --fetch /tmp/jaecoo-fetch.json \
  --review /tmp/price-approvals.json
```

The PR wrapper requires a clean working tree plus authenticated `git`/`gh`. It
commits locally first, then runs:

- `pricefeed_guard.py`
- full `pytest -q`
- `python -m vehreg market validate`
- serving projection dry-run for every affected model

Only after all gates pass does it push and call `gh pr create`.

## Deliberately still out of scope

- auto-merge;
- auto-publish to Supabase after merge;
- a polished browser Price Workbench;
- automatic creation of campaign identity from raw text;
- automatic edits to an existing campaign definition;
- letting SYSTEM_EVIDENCE promote without a person.
