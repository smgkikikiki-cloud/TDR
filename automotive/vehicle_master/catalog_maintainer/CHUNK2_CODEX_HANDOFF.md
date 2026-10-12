# Codex Handoff — PR #203 / Chunk 2 Only

**Task:** Implement **Chunk 2: Offline Evidence Replay + Unified Gap Adapter** on the *existing* branch `codex/vehicle-catalog-maintainer`, draft PR #203. The controlling roadmap is `automotive/vehicle_master/catalog_maintainer/ROADMAP.md` (committed after accepted Chunk 1 at `d574ea1`). Finish Chunk 2, run tests, update documentation, and STOP for owner review.

## Hard boundaries

- DO NOT start Chunk 3 or later; do not merge, deploy, access Production or real Supabase, invoke paid AI/search, make live HTTP requests, run cron, or schedule any background work.
- No direct writer, no migrations, no changes to canonical master, and no resurrecting retired file/release writers.
- Existing `docs/vehicle-db/VEHICLE_DB_V3.md` §4 is authoritative: structural MarketTrim changes are PROPOSAL ONLY. Proposed amendment in #203 is not adopted.
- Follow `AGENTS.md`, `docs/WORK_STATE.md`, adopted Vehicle DB v3 and existing #203 policy. Preserve accepted Chunk 0–1 behavior, keys, two queues, eligibility and deterministic output.
- Do not touch the #200 identity_resolution and #201 identity_bootstrap worktrees/contracts, or write a new registry.

## Goal

Prove on recorded/offline documents that the maintainer can tell **what a source actually proves for which exact active Thai-market trim**, and distinguish true missing P1/P2 fields from data already present in Vehicle Master/fact/payload layers. This is an evidence and data-contract chunk, NOT real research or AI extraction.

## Required work

### A. Canonical field registry compatibility
1. Inspect `lib/spec-field-registry.ts` and the real underlying canonical registry data source; trace shape, applicability, units, qualifiers and ownership.
2. Design a **read-only deterministic adapter/manifest** to resolve canonical `field_key` and version/checksum; avoid a second hardcoded production field registry. If a TS-to-Python bridge or export is necessary, it must read a pinned in-repository registry and fail on drift, never silently fall back to synthetic fixture definitions.
3. Add a versioned alias map only when supported by concrete real stored payload examples (trim/generation/variant/model); detect ambiguous aliases and hard-fail/hold. Never infer a field value just because another trim/variant shares a model.
4. Maintain the synthetic fixture catalog ONLY for isolated offline test cases.

### B. Recorded evidence contract + replay reader
1. Define versioned, validated `SourceDocument`, `SourceClaim`, `FieldCandidate`, `ReplayDisposition` and `ReplaySummary` structures/schemas. At minimum capture: source/market, model/generation/trim coverage, immutable content hash, URL or local recorded-source identifier, quote + in-document locator, published/captured date, document completeness, extraction method, data type/unit and measurement qualifiers.
2. Add a small, controlled corpus of **local synthetic or permissibly recorded** Thai official price/spec sheets in UTF-8 HTML/text/JSON. Include complete, partial, misleading, outdated, wrong-market and conflict cases. Keep test fixtures tiny and auditable.
3. Parse/replay a limited *explicit* set of P1/P2 keys (e.g. engine displacement, battery catalog capacity, motor power, dimensions, seats, rated range with basis/scope, safety); use deterministic extraction of controlled fixture text/tables. No LLM, browser, scraper or universal PDF parser yet. No guessed missing values.
4. Verify quote/locator and exact document SHA before accepting source claims. Confirm Thai market, model/generation, exact grade/powertrain, MY/date where represented; a source that merely lists a model may not grant permission to write every trim.
5. Separate **spec evidence** from **complete current retail lineup proof**; ECO/homologation document evidence cannot automatically confirm that a trim is offered for sale in Thailand. MSRP must remain Price Ledger-owned.

### C. Unified Gap and Research Work Planning
1. Reconcile canonical Vehicle Master Fact `value_state` versus `verification_status`, field aliases, payload facts, model/generation/variant/trim scoped data, locks, temporal applicability and source trace without duplicating work.
2. Preserve outcomes: MISSING, UNKNOWN, KNOWN/ALREADY_KNOWN, NEEDS_SOURCE_TRACE, NOT_APPLICABLE, ABSENT, SOURCE_EXHAUSTED (research state, not a new canonical fact enum), CONFLICT, TOMBSTONED_LOCKED and OUT_OF_SCOPE.
3. **Never** generate research for HISTORICAL/UNVERIFIED/deleted/admin-retired/owner-retired, `DISCOVERED` or Upcoming. Within a CURRENT model, exclude historical sibling trims.
4. P3 is opportunistic if a captured document already has the value; no standalone P3 task; P1 first, P2 second; one document reused over explicitly named trims.
5. Do not create live fetching jobs; output *offline evidence candidates and gap dispositions* from fixture replay only. Any candidate that cannot pass model/trim/source/unit validation must remain HOLD/REVIEW, not silently accepted.

### D. CLI outputs
Extend the fixture-only CLI with an explicit `replay` subcommand that accepts local fixture snapshot and local recorded-document paths plus an output directory. Keep `simulate` unchanged. Emit byte-stable:
- `replay_evidence.jsonl`
- `field_candidates.jsonl`
- `gap_diff.json`
- `replay_summary.json`

Summaries must include accepted/held/rejected candidates by reason, applicable gaps before/after **in replay only**, cache/duplicate suppressions, external HTTP calls = 0, paid model calls = 0, paid tokens = 0, production writes = 0. Distinguish a candidate proposed from a canonical fact written (always zero writes).

### E. Tests (must add regressions)
- Correct doc hash, wrong/forged hash and missing locator/quote.
- Thai vs non-Thai model, wrong trim/powertrain, period/generation mismatch.
- Explicit `COMPLETE_LINEUP` vs partial scraped subset; no source-completeness by mere document title or boolean.
- Range NEDC/WLTP/CLTC and full vs electric-only scope: no cross-standard conflation or unsupported inferred conversion.
- Known Fact with PROVISIONAL verification; UNKNOWN Fact with VERIFIED verification; explicit NOT_APPLICABLE and ABSENT; Admin locked null tombstone; variant/payload alias with canon field key; contradicting source values.
- Mixed P1/P2 group, P3 skip, list price excluded.
- Two documents that derive from the same announcement not assumed independent; duplicate document hash creates no duplicated accepted candidate.
- Byte-identical two offline replays; negative/fail-closed invalid-schema cases; no network, provider or DB imports.
- Run focused tests under both repository root and `automotive/vehicle_master/`, and full repository CI. No regression to Chunk 1 queues.

## Exit criteria / response

- PR #203 remains OPEN/DRAFT, same branch. Zero HTTP, zero paid tokens, zero paid calls, zero writes, no deployments.
- Report changed-file inventory and file paths, CLI commands and exact output, focused and full CI results, examples of accepted/held/rejected source claims, and design questions left open.
- Append a **Chunk 2 completion record** to roadmap or package README with scope and tests only (do not claim owner acceptance).
- Stop for ChatGPT QA and owner review; **do not begin Chunk 3** automatically.
