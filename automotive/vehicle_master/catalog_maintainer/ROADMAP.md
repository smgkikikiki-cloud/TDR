# TDR Autonomous Vehicle Catalog Maintainer — Implementation Roadmap

Status: **PROPOSED EXECUTION PLAN / OWNER REVIEW**, 2026-10-11.
Repository: `smgkikikiki-cloud/TDR`; working PR: **#203**, branch `codex/vehicle-catalog-maintainer`.
Last accepted baseline: **Chunk 0-1, commit `d574ea1`**, both GitHub Actions workflows green.
This roadmap is a development/acceptance contract, **not authority to merge, deploy, access Production, call paid models, or run a backfill**.

## 0. Objective and boundaries

Build one governed maintainer with two operating phases:

1. **BACKFILL:** process missing data and retail-lineup uncertainty for *already existing, currently marketed Thai vehicles* using prioritized, bounded research jobs.
2. **EVENT_DRIVEN:** after actionable backfill has settled, remain dormant until a verified catalog/source change creates new work; research only the delta.

Each work phase has a separate execution mode: `MOCK`, `REPLAY`, `SHADOW`, `LIVE_LIMITED`, or `LIVE_BACKFILL`. State-machine transition and permission gates are explicit; no state is inferred from a clock.

Initial scope: existing canonical Model and Generation IDs only. No new Model/Generation; no undisclosed Bootstrap `DISCOVERED` shells, Upcoming, HISTORICAL or admin-retired records. MarketTrim additions/discontinuations are **proposals only** under the currently adopted `docs/vehicle-db/VEHICLE_DB_V3.md` §4. Auto structural changes are an owner-proposed *future change*, not current authority.

Authority: Supabase Vehicle Master (v57–v61 onward), NOT legacy Git/catalog files, `canonical_input_batches`, or serving views. Read-only snapshots can be used for research; **no ad-hoc production write path**. The Phase 1 governed DB writer (observations -> reconcile -> apply/propose -> revision audit/revert) must exist before anything can apply to master.

Cross-project separation:
- **#200 Identity Resolution**: matching provider/foreign identities to existing TDR Canonical Model IDs.
- **#201 Identity Bootstrap**: possible new Canonical identities, initially outside maintainer's allowed scope.
- **#203 Catalog Maintainer**: existing-model retail verification and P1/P2 fact research; later receives approved/published lifecycle events from #201, with a future separately approved scope extension.
Neither #200 nor #201 may silently overwrite the other's identity rules; #203 never performs model matching, model bootstrap or new Model/Generation creation.

## 1. Always-on invariants (all chunks)

- **No paid usage until explicit owner go:** `allow_paid_ai=false`, `allow_paid_search=false`, paid calls/tokens/spend = 0. No API key fallback, overage or subscription loophole.
- **No production mutation** before approved permissions, governed writer, test gates, and explicit owner go.
- **Current Thai retail only:** Registry `CURRENT` is *not* real-world sale confirmation. Accept owner-approved complete current-retail membership; otherwise require convincing official Thai-market complete-lineup evidence. Ambiguous/unverified => RETAIL_AUDIT, not spec research.
- Never spec-enrich `HISTORICAL`, `UNVERIFIED`, deleted, admin-retired, owner-retired, `DISCOVERED`, `UPCOMING`. Recheck eligibility before dispatch and before eventual apply.
- Two **independently prioritized and budgeted** queues: `RETAIL_AUDIT` (P0), `SPEC_ENRICH` (P1/P2); bounded fair merge prevents starvation. Registration numbers affect ordering ONLY, never evidence of retail availability; preserve RY1/RY3 comparability.
- P3/incidental fields can be extracted opportunistically from already-retrieved official documents, but never open their own paid/search task. Price changes belong to Price Ledger/price governance, NOT spec-fact writer.
- One official document may satisfy multiple specific Trims/Fields, but only if the source explicitly covers each. No copying by similarity or sibling trim inference.
- `KNOWN` value_state is not `verification_status=VERIFIED`; `NOT_APPLICABLE`, `ABSENT`, `UNKNOWN`, missing, conflicts, Admin-locked null tombstones, source-exhausted research state are distinct. No false gaps from payload/fact alias differences.
- Every proposed fact must have source provenance (URL or persisted document reference), captured/published time when known, immutable SHA-256, exact quote/locator, market TH, identified Model/Generation/Trim coverage, unit and confidence/reason. Unsupported guesses are discarded.
- Missing from one price list, scraping failure, or low registration ≠ discontinued. Structural changes are soft and reversible, and require extra evidence gates.
- Idempotent work keys are target scoped; unchanged sources/fields do not regenerate cost or work. All research calls have hard per-job and aggregate budgets, retry limits, stop codes, negative cache, manual pause/kill switch, and audit.
- Codex development/test is not a standing instruction to schedule, deploy or run real AI.

## 2. Implementation path and gates

### DONE — Chunk 0–1: Offline deterministic foundation
- Baseline: PR #203 at `d574ea1`; both full GitHub Actions workflows SUCCESS (2141 passed, 2 skipped, 4334 subtests per vehicle-suite job).
- Deterministic fixture, eligibility, gap inventory, two queues, priorities, policy validation, scoped job keys, synthetic outputs, proposal-only structural gates.
- Exit: 20 new focused unittest tests; no networking, paid AI, DB client or writer. **Accepted for next chunk only; PR stays draft.**

### IMPLEMENTED — Chunk 2: Offline Evidence Replay + Unified Gap Adapter (ZERO TOKEN; QA pending)
Purpose: prove evidence/field identity correctness without live retrieval or an AI provider.
- Add versioned recorded-document fixtures (official Thai mock brochure, complete/partial price-list lineup, trim-specific table, invalid/out-of-market/old document). Local UTF-8 text/HTML/JSON fixtures only; synthetic or permissibly retained examples.
- Define immutable `SourceDocument`, `EvidenceClaim`, `FieldCandidate`, `FieldDisposition`, `ReplayReport` contracts with document hash, locator, quote, applicability, source authority, time, and lineage.
- Implement replay ingestion and deterministic claim parsing/normalizing for a **small typed set**: engine CC, motor power, battery catalog capacity, rated EV range with measurement basis/scope, dimensions, seat count, basic safety. Do not invent universal parsers or AI text extraction in this chunk.
- Inspect and consume the **actual canonical field registry** used by `lib/spec-field-registry.ts` and Vehicle Master. A deterministic, versioned read-only adapter/manifest may be added; no duplicate independently maintained registry. Document aliases for payload keys versus canonical field keys, semantics/units/applicable powertrains and exact ownership.
- Unify fact/payload/variant/generation/model presence detection with field-level applicability and owner locks; never copy a shared value to an unlisted trim. Report `MISSING`, `ALREADY_KNOWN`, `NOT_APPLICABLE`, `TOMBSTONED_LOCKED`, `CONFLICT`, `NEEDS_SOURCE_TRACE`, `SOURCE_EXHAUSTED` as appropriate.
- Outputs (offline only): `replay_evidence.jsonl`, `field_candidates.jsonl`, `gap_diff.json`, `replay_summary.json`. Include costs = 0, matched/mismatched/held counts, reason codes.
- Tests: wrong market, wrong trim/year/variant, partial lineup, stale/conflicting source, duplicated facts, wrong units, misleading nearby text, locked null, independent model and trim changes, unchanged hash replay, no P3 independent retrieval, byte-stable outputs.
- Gate: focused tests + full GitHub Actions green; replay never creates a master write, external request, paid-model call, new identity or live research job. **STOP for review before Chunk 3.**

Implementation record (2026-10-11): pinned read-only adapter consumes the real 2026 canonical comparable-spec registry and editor alias mappings; deterministic local replay and frozen contracts/schemas added; 11 synthetic recorded documents exercise complete/partial capture manifests, market/trim/variant/powertrain/year checks, exact quote/hash binding, units/range qualifiers, duplicates/conflicts, and stale sources. The unified adapter resolves supported payload/fact aliases and preserves canonical value states/locks while treating the synthetic tier list as fixture-only policy. CLI replay sample produced 3 accepted candidates, held conflicts and scope mismatches, 2 duplicate-hash suppressions, 0 canonical writes, 0 HTTP, 0 paid calls/tokens/spend. Candidate acceptance is reported separately from the number of open priority gaps actually matched.

QA correction record (2026-10-11): replay now canonicalizes all existing payload layers before value reconciliation; compares existing facts by every required qualifier; requires explicit quote-level units for dimensional numbers; holds all same-hash documents when declared market/source/coverage scope conflicts; preserves `NOT_AVAILABLE` separately from research exhaustion; and validates normalized snapshots before replay. Six targeted regressions added. The registry/editor checksums are pinned to the exact source bytes on the PR tree after CI exposed stale local canonical copies. Focused suite: 36 tests pass from both required working directories. Full GitHub CI for the correction commit must pass before owner acceptance. This is not acceptance to begin Chunk 3.

### Chunk 3: Retail Evidence Verification + Pure Trim Reconciliation (ZERO TOKEN)
- Replace trust in a mere `COMPLETE_LINEUP` flag with explicit evidence contract and validated complete source capture; detect incomplete scrapes/0 rows/partial landing pages, source drift, discontinued claims and identity collisions.
- Same-model exact identity, aliases, powertrain, dates, MY/facelift, completeness, and evidence window; model-level diff: KEEP / ADD_PROPOSAL / SOFT_DISCONTINUE_PROPOSAL / HOLD / REVIEW.
- Discontinuation requires quote-bound, exact-trim first-party Thai retail end-of-sale evidence OR two independent, complete official Thai lineup captures that both omit the trim, strictly chronologically ordered and separated by the policy minimum interval. A prior positive lineup plus one later omission is insufficient. End-of-production is not end-of-retail-sale.
- Honor owner-approved complete sets, Admin status and protected records. Do not touch model/generation IDs.
- Gate: adversarial golden corpus covering false trim additions, renames, reactivations, facelift, same-model MY, limited edition, options vs trims, broken pages, incomplete source, and all-trims-disappeared => HOLD; outputs remain proposals only.

Implementation record (2026-10-11): QA accepted Chunk 3 at `38a6d1ac583c3a34b8d92de134ff72a6ad601209`. The verifier binds completeness, scope, page counts, edition identity and capture provenance to source content; eligibility and reconciliation share the validator. Omission is compared only within exact model/generation/model-year/facelift scope. Soft discontinuation requires two independent negative observations or explicit quote-bound retail end-of-sale evidence; production end does not qualify. The proposed interval is validated policy and remains pending owner approval. All structural outcomes remain proposals.

### Chunk 4: Bounded Research Planner + Persistent OFFLINE Runner (ZERO TOKEN)
- Local durable job store (e.g. SQLite or serializable journal, *not* Production Supabase): separate RETAIL_AUDIT/SPEC_ENRICH queues, leases, attempt count, checkpoints, restart/replay and per-job/policy revision, jobs remain idempotent.
- Document-first research plan, existing snapshot/cache first, then official sources, limited secondary corroboration; P3 never justifies retrieval. Track `SOURCE_EXHAUSTED`, `BUDGET_EXHAUSTED`, `SOURCE_BROKEN`, `IDENTITY_AMBIGUOUS`, `CONFLICT` separately.
- Quotas are measured, not just displayed: request count, tokens, spend, time, retries; negative cache/cooldown per vehicle x field group; skip unchanged source hashes. A kill switch fails closed.
- Gate: deterministic fake-clock/fake-provider multi-day replay incl. interrupted/restarted worker, no duplicate work, no starvation, exhausted work stays stopped.

Implementation record (2026-10-11, QA pending): added a local SQLite journal, document-first normalized planner, separate fair queues, scoped idempotency with policy revision, leases/checkpoints/recovery, explicit terminal/retry states, measured zero-token/spend budgets, cooldown and unchanged-hash caches, and a fail-closed one-step manual MOCK CLI. No provider interface for external calls, background execution, cron, Production database, or canonical writer is present. Seventy-three focused tests cover restart and multi-day behavior; sample plan/step/report are deterministic. Full CI status is required on the correction commit. Stop for QA here; do not start Chunk 5.

### Chunk 5: Source Acquisition Adapters (offline-first)
- Read existing source registry and permitted official Thai sources; respect publisher permissions, Terms, robots/rate limits and document licensing. Prefer PDF/structured HTML stored in a content-addressed evidence cache; where JS render is necessary, treat adapter as an explicit source capability.
- Start with prerecorded/fake HTTP transport, never live request in unapproved mode. Source status is `FETCH_OK`, `UNCHANGED`, `PARTIAL`, `SOURCE_BROKEN`, `BLOCKED`, etc.
- Gate: stable replay fixtures, exact URL allowlist and permissions, bounded retries, no accidental access/charge.

### Chunk 6: Read-only Vehicle Master Shadow Integration (approval gate)
- **Separate owner approval required to read Production.** Before that, use exported/anonymized read-only snapshots, not live DB.
- Map canonical master tables, `vehicle_facts`, trim payloads, price ledger/retail memberships and actual registry into normalized input. No write role, no stored credentials in code, no `current_*` writes.
- Produce scope/coverage/priority reports on the existing catalog: eligible models/trims, audit-only, excluded, unresolved, P1/P2 by powertrain, duplicate/false gap rate, proposed source work/cost. Validate row-level sampling.
- Gate: factual QA against known current lineups + safe-read authorization, no changes to Production.

### Chunk 7: Real AI Extraction Adapter — opt-in, capped
- Introduce provider/model interface consistent with **adopted** Vehicle DB v3 §9 (do not substitute an unauthorized model or authentication/billing path). Deterministic discovery, fetch/cache, parsing and validation run without LLM when possible; LLM only extracts bounded relevant snippets or resolves ambiguity.
- First test with fake provider/replayed deterministic model responses and zero spend. Require structured output schema, evidence quote binding, per-trim applicability, independent validator, cache/stop policy, usage accounting, and blocked paid mode by default.
- **LIVE_LIMITED** requires a separate owner go, confirmed billing configuration (including disabling overage as required), explicit tiny THB/token/request budgets and hard-off switch. Do not assume a subscription is cost-free or permitted for unattended automation.
- Gate: known-answer source corpus and hand-checked 2–3 vehicle/field samples, strict observed false-accept controls, actual measured cost per accepted field, zero unsourced writes.

### Chunk 8: Governed Writer and Structural Authority (separate owner/platform gates)
- Wait for supported DB-master Phase 1 governed write layer: observations -> reconcile -> apply/propose -> revision/change log -> revert, plus protected Admin tombstones and authority ordering.
- Under currently adopted V3 §4, **all ADD / soft-DISCONTINUE remain proposals**, never auto-applied. A separate, explicit owner-reviewed V3 §4 amendment, migration/security rules and adversarial acceptance is needed before autonomous structural applies.
- Future permitted auto ADD only for unambiguous official Thai grade + powertrain + exact identity and collision-free, owner-safe evidence. Soft-DISCONTINUE requires stronger audited evidence; never physically delete, never silently remove a member of owner-locked retail set.
- Integration is per-model atomic, revision/hash checked, idempotent and reversible. No impersonation of ADMIN. Price Ledger uses its own policy.
- Gate: permission tests, RLS/role checks, concurrency tests, compensating revert, and explicit production deployment go.

### Chunk 9: Controlled 2–3-week BACKFILL (operational approval gate)
- Only AFTER owner authorizes live research, budget, deployed runner and permitted writes/proposals. Start 2–3 vehicles/fields, expand in measured batches, then gradual 2–3-week run; no unattended spend beyond hard ceiling.
- Two queues with mandatory spec service slots. Prioritize confirmed current + high-value P1, group fetch reuse, field group negative cache, skip discontinued. Daily dashboard: accepted facts/proposals, confidence, false positives from sample audit, paid tokens/spend, failed/exhausted, stopped jobs.
- Completion = no remaining **actionable** eligible jobs, while `SOURCE_EXHAUSTED` / needs-review are recorded and not endlessly retried; not a naive 100% fill-rate.
- Any anomaly or budget overrun => halt.

### Chunk 10: EVENT_DRIVEN dormancy / ongoing maintainer
- Cheap deterministic detector watches approved `MODEL_ACTIVATED`, `TRIM_ADDED`, `MODEL_YEAR_CHANGED`, verified new spec gaps, source hash changes; dedupe by event/revision/source hash. No AI call when unchanged.
- New-model identities from #201 remain excluded until explicitly published and scope policy expanded; do not treat `DISCOVERED` as CURRENT. #200 supplies reviewed mapping only if relevant; neither blocks initial Backfill.
- On event: recheck Thai retail eligibility; enqueue only delta; otherwise sleep. Support PAUSED and replay/backfill recovery.
- Gate: event replay, duplicate delivery, out-of-order events, archived trim events, no false wake-ups or paid calls.

## 3. Dependency / gate matrix

| Capability | Independent of #200/201? | Needs governed writer? | External/Paid? |
|---|---|---|---|
| Chunks 0–5 deterministic/offline | YES | NO | NO |
| Chunk 6 offline export shadow | YES | NO | NO |
| Chunk 6 live read-only Production | YES | NO | Separate owner approval |
| Chunk 7 fake AI adapter | YES | NO | NO |
| Chunk 7 small real model calls | YES | NO | Separate owner + billing approval |
| Chunk 8 apply facts / structural proposal | YES | **YES** | Not intrinsically paid |
| Chunk 8 autonomous ADD/discontinue | YES | **YES + V3 §4 owner amendment** | Not intrinsically paid |
| Chunk 9 unattended live backfill | YES | Writes need writer | Explicit authorization/budget |
| Chunk 10 new published-model events | **Depends on #201 integration** | Writer/lifecycle integration | Only on change |

## 4. Acceptance metrics, not vanity metrics

- `precision_of_accepted_facts` and `false_structural_change_rate` on owner-labelled golden/adversarial corpus, reported separately from coverage.
- `verified_P1_coverage` over eligible active trims; `coverage_by_powertrain` and `fields_per_official_document`.
- `false_gap_rate` from fact/payload reconciliation and source-trace verification.
- `source_exhaustion_rate`, `repeat_retrieval_avoidance_rate`, `duplicate_job_rate` and `stale_cache_research_calls`.
- `cost_per_accepted_verified_field` including search, fetch, tokens, validation and retries; `paid_spend_actual` measured and hard capped.
- `retail_audit_queue_age`, `P1_spec_queue_age`; prove bounded fair service regardless of backlog.
- `admin_protected_write_attempts=0`, `discontinued_trim_spec_jobs=0`, `unsourced_fact_commits=0`.
- A pipeline is not declared complete merely because 100% of generated jobs were executed; unresolved/unknown/exhausted cases are explicit.

## 5. Codex execution contract

- Work on **existing branch** `codex/vehicle-catalog-maintainer`, existing draft PR #203. Never merge or deploy by inference.
- **One chunk per review**; Chunk 2 is NEXT; do not start Chunk 3+ in the same iteration.
- Read `AGENTS.md`, `docs/WORK_STATE.md`, `docs/vehicle-db/VEHICLE_DB_V3.md`, and the existing #203 contract/test fixtures before editing.
- PR changes for Chunk 2 stay under `automotive/vehicle_master/catalog_maintainer/` and its tests, except an explicitly justified read-only registry adapter; do not touch #200/#201 directories or retired paths.
- End each chunk with: change inventory, evidence/gap examples, focused + full CI, zero-call/writes proof, scoped cost report, unresolved decisions, updated fixture outputs, and explicit stop for owner review.
- A later approval to `continue` means **next offline chunk**, not authority to turn on paid research, Production, structural auto-writes, cron or deployment.

