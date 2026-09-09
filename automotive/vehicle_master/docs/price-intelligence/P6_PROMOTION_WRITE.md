# Price Intelligence P6 — Reviewed Promotion + Canonical Price PR

Status: **implemented + hardened**

P6 is the first Price Intelligence phase allowed to change canonical market-price files. It sits after P5 reconciliation, remains HUMAN-gated, and fails closed whenever the reviewed artifacts or canonical truth have changed underneath it.

```text
P2 fetch
  -> P3 PriceClaim
  -> P4 EXACT MarketTrim match
  -> P5 reconcile / 24h candidate state
  -> content-bound review queue
       |- BIND campaign/option -> rerun P5
       `- APPROVE / REJECT promotable candidate
  -> P6 freshness + evidence + chronology checks
  -> P6 market-file write plan
  -> shared writer lock + atomic file replacement
  -> local commit
  -> guard + tests + market validate + serving dry-run
  -> push generated PR
  -> HUMAN PR MERGE
  -> later serving publication
```

P6 does not rematch raw trim names, reinterpret source semantics, or turn a P5 REVIEW/CONFLICT into a write. P5 remains the eligibility authority; P6 is the reviewed canonical write boundary.

## Frozen P6 rules

1. **Only three P5 dispositions are promotable:** `SAFE_CANDIDATE`, `CONFIRMED_REPLACEMENT`, and `HISTORICAL_ONLY`.
2. **Every canonical write needs a HUMAN review decision.** `SYSTEM_EVIDENCE` cannot approve a write in P6.
3. **PENDING_24H, REVERTED, REVIEW, and CONFLICT cannot be overridden.** Fix or bind upstream and rerun P5.
4. **Approval is snapshot-bound.** The review carries `source_batch_id`, `reconcile_id`, and `candidate_state_id`. P6 recomputes all three and refuses mixed or stale artifacts. See `P6_LINEAGE.md`.
5. **Immutable evidence is mandatory.** A mutable URL is insufficient. The promoted row stores the supporting `SourceDocument` SHA-256 in `source_document_id`.
6. **The latest candidate sighting must be proven by the supplied fetch batch.** The candidate's latest `claim_id` must exist in that batch, point to the same document SHA, match amount/type, retain the same P4 `EXACT` MarketTrim, and have a `document.fetched_at` at least as recent as `candidate.last_seen_at`.
7. **Review time must be fresh.** An approval cannot predate `first_seen_at`; a confirmed replacement must be reviewed after `confirmed_at`.
8. **SAFE_CANDIDATE is rechecked against canonical truth.** If the stream P5 saw as empty gained a canonical row before P6 writes, P6 refuses and requires a P5 rerun.
9. **CONFIRMED_REPLACEMENT is rechecked against canonical truth.** The expected `replaces_amount_thb` must still be current at confirmation/review. If another writer changed the stream, P6 refuses instead of superseding stale truth.
10. **Backdating cannot jump over newer canonical chronology.** A literal `effective_from` is honored only when no canonical row starts on/after that date in the same stream.
11. **Replacement is append + supersede.** The exact prior stream receives `effective_to`; the new price is appended as a separate canonical row/file.
12. **Price types are independent streams.** LIST, INTRODUCTORY, CAMPAIGN, FINANCE, ESTIMATED, DEALER, ECO_STICKER, and UNKNOWN never replace one another merely because the amount differs.
13. **Campaign/finance scope is exact.** `campaign_id + option_id` are required; raw `campaign_hint`/`option_hint` remain evidence only.
14. **Campaign binding is validated at the write boundary.** Campaign brand must equal the MarketTrim brand, the option must exist, and a current offer must still be open on the relevant Thailand business date.
15. **New campaigns may be created only in the same reviewed bundle that uses them.** Existing campaign identities are never auto-rewritten, duplicate creations are refused, and orphan campaign creations with no approved candidate are refused.
16. **One reviewed bundle cannot silently pick competing current truth.** Multiple approved current candidates in one canonical stream are refused, and approved historical/current windows in the same stream may not overlap.
17. **HISTORICAL_ONLY requires a complete literal window.** Both `effective_from` and `effective_to` must be explicit source evidence. P6 never invents the beginning of an already-ended promotion from `first_seen_at`.
18. **System timestamps use the Thailand business calendar when reduced to dates.** `first_seen_at`, `confirmed_at`, review time, and stale-check instants are converted to `Asia/Bangkok` before comparison with date-only canonical facts. Literal source dates are preserved. See `P6_TIME_SEMANTICS.md`.
19. **Production writes serialize through the shared writer lock.** The canonical read -> stale check -> plan -> validation -> apply sequence runs under the same lock used by manual price authoring.
20. **Each touched JSON file is replaced atomically and ordinary write failures roll back the touched set.** P6 does not use the direct `PromotionPlan.apply()` fixture writer in production.
21. **P6 changes canonical `market/` files only.** It does not write Supabase, serving tables, Phase-C outbox/shadow state, or application UI data directly.
22. **Human PR merge remains the publication gate.** P6 never auto-merges and does not publish serving data after opening a PR.

## Review queue

`tools/price_review_queue.py` consumes the exact P2-P4 fetch artifact, P5 reconcile report, and post-P5 CandidateBook snapshot. It emits two separate queues.

### Promotion review

A candidate P5 already resolved to a canonical stream:

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

A campaign/finance claim that P5 refused because canonical campaign scope is missing:

```json
{
  "claim_id": "...",
  "trim_id": "...",
  "raw_campaign_hint": "MORE RAIN, MORE GAIN",
  "raw_option_hint": "cash special",
  "required_action": "BIND_CANONICAL_CAMPAIGN_OPTION_THEN_RERUN_P5"
}
```

The human supplies canonical `campaign_id` and `option_id` through the Price Intelligence binding review flow, then reruns P5. The raw hints are never promoted by themselves and P6 never performs a second match.

## Promotion decision bundle

The review bundle is content-bound to the artifacts the reviewer saw:

```json
{
  "schema_version": 1,
  "source_batch_id": "pbatch:...",
  "reconcile_id": "prec:...",
  "candidate_state_id": "pstate:...",
  "decisions": [
    {
      "candidate_id": "pcand:...",
      "action": "APPROVE",
      "reviewer": "owner",
      "origin": "HUMAN",
      "reviewed_at": "2026-09-10T10:00:00+07:00",
      "notes": "source checked"
    }
  ],
  "create_campaigns": []
}
```

Do not copy an old APPROVE row into a newly generated review file. Regenerate the queue from the current fetch/reconcile/candidate-state artifacts and review that exact snapshot.

`create_campaigns` uses the canonical Campaign schema and is create-only. A new campaign must be referenced by an approved candidate in the same bundle.

## Canonical dating on replacement

System-observed timestamps are instants. Canonical PriceLedger dates are Thailand market-calendar dates.

No explicit effective date:

```text
first_seen_at  2026-09-08T18:30:00Z  -> Thailand 2026-09-09
confirmed_at   2026-09-09T18:30:00Z  -> Thailand 2026-09-10

old row effective_to     2026-09-09
new row observed_at      2026-09-09
new row effective_from   2026-09-10
```

A literal source date is different: it is already a market-calendar statement and is preserved exactly.

```text
source says effective_from = 2026-09-09
first seen                  = 2026-09-10
confirmed                   = 2026-09-11
```

After confirmation P6 may record `effective_from=2026-09-09` and close the prior stream on `2026-09-08`, but only if the stale/chronology guards prove that no newer canonical row has occupied that interval.

## Canonical provenance

Every promoted row retains both:

```text
source_ref         mutable source URL for navigation
source_document_id sha256:<64 hex> identifying the fetched representation
```

The supporting fetch must additionally contain the latest candidate claim and its P4 `EXACT` match. A correct URL with missing/stale claim evidence is rejected.

## Commands

Generate a strict lineage-bound review queue:

```bash
python tools/price_review_queue.py \
  --candidate-state /tmp/price-candidates.json \
  --reconcile /tmp/jaecoo-reconcile.json \
  --fetch /tmp/jaecoo-fetch.json \
  --out /tmp/price-review.json
```

Dry-run promotion (default):

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

`--apply` acquires the shared writer lock before the final canonical freshness check, plan construction, full ledger validation, and write.

Generate a guarded PR:

```bash
python tools/price_promotion_pr.py \
  --candidate-state /tmp/price-candidates.json \
  --reconcile /tmp/jaecoo-reconcile.json \
  --fetch /tmp/jaecoo-fetch.json \
  --review /tmp/price-approvals.json
```

The PR wrapper requires a clean working tree plus authenticated `git`/`gh`. Before reading/writing canonical market files it fetches the configured base branch and creates a fresh `pricebot/*` branch from that fetched base. After P6 applies and commits the market-only diff it runs:

- `pricefeed_guard.py`;
- full Vehicle Master `pytest -q`;
- `python -m vehreg market validate`;
- serving-projection dry-run for every affected model.

Only after all local gates pass does it push and call `gh pr create`. A failed gate never pushes. Merge remains human.

## What P6 still deliberately does not solve

- auto-merge;
- automatic serving/Supabase publication after merge;
- a browser Price Workbench;
- automatic campaign identity creation from raw text;
- automatic modification of existing campaign definitions;
- automatic campaign rollover across a different `campaign_id` without an explicit reviewed relationship such as a future `offer_family_id` / `replaces_campaign_id`;
- durable external storage policy for immutable source snapshots (the canonical SHA proves representation identity, but retention/storage is a separate operational decision);
- permission for `SYSTEM_EVIDENCE` to promote without a human.
