# TDR Vehicle Catalog Maintainer — offline simulator

Fixture-only implementation of deterministic catalog eligibility, gap inventory, two independently ranked queues, and evidence-gated structural proposals. It is not connected to production data. The in-package field registry exists only in the synthetic fixture; production must consume the canonical comparable-spec registry and its applicability semantics.

## Run

From repository root:

```bash
python -m unittest discover -s automotive/vehicle_master/tests/catalog_maintainer -v
python -m automotive.vehicle_master.catalog_maintainer.cli simulate \
  --fixture automotive/vehicle_master/catalog_maintainer/fixtures/sample_snapshot.json \
  --out automotive/vehicle_master/catalog_maintainer/fixtures/sample_output
python -m automotive.vehicle_master.catalog_maintainer.cli replay \
  --fixture automotive/vehicle_master/catalog_maintainer/fixtures/sample_snapshot.json \
  --documents automotive/vehicle_master/catalog_maintainer/fixtures/recorded_docs/*.json \
  --out automotive/vehicle_master/catalog_maintainer/fixtures/sample_replay_output
python -m automotive.vehicle_master.catalog_maintainer.cli retail-reconcile \
  --fixture automotive/vehicle_master/catalog_maintainer/fixtures/sample_snapshot.json \
  --document automotive/vehicle_master/catalog_maintainer/fixtures/recorded_docs/complete-lineup.json \
  --out automotive/vehicle_master/catalog_maintainer/fixtures/sample_retail_reconciliation.json
rm -f /tmp/catalog-maintainer-offline.sqlite /tmp/catalog-maintainer-offline.sqlite-shm /tmp/catalog-maintainer-offline.sqlite-wal
python -m automotive.vehicle_master.catalog_maintainer.cli offline-plan \
  --fixture automotive/vehicle_master/catalog_maintainer/fixtures/sample_snapshot.json \
  --db /tmp/catalog-maintainer-offline.sqlite --now-epoch 1791676800 \
  --out automotive/vehicle_master/catalog_maintainer/fixtures/sample_offline_run/plan.json
python -m automotive.vehicle_master.catalog_maintainer.cli offline-step \
  --db /tmp/catalog-maintainer-offline.sqlite \
  --responses automotive/vehicle_master/catalog_maintainer/fixtures/offline_mock_responses.json \
  --now-epoch 1791676800 --confirm-mock-only \
  --out automotive/vehicle_master/catalog_maintainer/fixtures/sample_offline_run/step.json
python -m automotive.vehicle_master.catalog_maintainer.cli offline-report \
  --db /tmp/catalog-maintainer-offline.sqlite \
  --out automotive/vehicle_master/catalog_maintainer/fixtures/sample_offline_run/report.json
```

Reproduce the fixture output from the package directory's parent repository root using those exact commands. No credentials, optional packages, external services, Production database, or remote database are used. Chunk 4's journal is local SQLite only. `--budget 0` returns empty queues. A positive `--budget` caps each queue independently, so a Retail Audit backlog cannot consume the Spec Enrichment allowance. The merged queue follows a finite policy-configured service cycle. Output contains `queue.csv`, `decisions.jsonl`, and `summary.json`.

## Queue semantics

- `RETAIL_AUDIT` is a model-level P0 task when a CURRENT model's live Thai lineup is not established.
- `SPEC_ENRICH` is available only for trims admitted by an owner-approved current-retail set or an official Thai-market source that explicitly declares `COMPLETE_LINEUP` and identifies its current trim IDs. Partial and individual-trim documents stay in Retail Audit.
- An owner-approved set is the membership authority; nonmembers are excluded even if their row says CURRENT or other signals imply activity.
- Spec gaps are grouped by model/document and field group with P1/P2 kept distinct inside mixed groups. Vehicle Master `value_state` (`KNOWN`, `UNKNOWN`, `NOT_AVAILABLE`, `NOT_APPLICABLE`, `ABSENT`, and locked null tombstones) is separate from `verification_status` (`VERIFIED`/`PROVISIONAL`). Existing facts and payload values suppress duplicate gaps; P3 never opens a task; prices are ledger-owned.
- RY1 and RY3 are selected through each model's declared registration profile, normalized within compatible strata and periods, and never summed together or with `*` aggregate rows. Registration contributes only to Retail Audit ranking and is never evidence.
- Job keys hash only the model's relevant identity/scope, document hashes, or field-gap bundle. An unrelated model/fact update does not regenerate every job.

`contract/SPEC.md` records the proposed V3 §4 permission amendment. It is not adopted policy. The runner has no canonical writer, autonomous/background scheduler, HTTP client, or external/paid provider dependency.

## Chunk 2 — offline evidence replay

`replay` reads only local JSON documents and the normalized fixture. Its fixed line grammar produces candidates only for exact existing Thai model/generation/trim identities. The read-only adapter pins the canonical 2026 comparable-spec registry (`vehreg/data/2026/product/comparable_specs/registry.json`) and the `trim-editor-fields.ts` alias source by SHA-256; missing or changed files fail closed. Vehicle Master field type, canonical unit, qualifiers, and powertrain applicability come from that registry. Fixture priority tiers remain an isolated policy overlay.

Recorded docs carry content hashes, local source IDs, capture dates, explicit trim/variant/powertrain coverage, quotes/line locators, source lineage, and extraction method. Retail-lineup completeness also requires a capture manifest whose listed rows match the document's trim IDs; a title or boolean alone cannot establish completeness. Spec sheets remain spec evidence and never change retail eligibility. Range values and other qualified fields retain their required comparison qualifiers; values with distinct or unproven qualifiers are not conflated. Dimensional numbers require a unit in the quoted claim, while seat counts remain unitless. Same-hash documents with conflicting market/authority/coverage metadata are held together instead of letting sort order choose a winner. Replay validates the normalized snapshot before indexing. `NOT_AVAILABLE` remains a catalog value state and does not imply persisted search exhaustion. Conflicting claims, stale/out-of-market sources, locked tombstones, historical or unadmitted trims are held/rejected. No price or P3 task is created.

Replay writes `replay_evidence.jsonl`, `field_candidates.jsonl`, `gap_diff.json`, and `replay_summary.json`. These are proposals/dispositions only: canonical writes, HTTP, paid model calls, paid tokens, and spend are always zero. The summary distinguishes accepted source candidates from the number that actually match an open priority gap; a valid candidate can be accepted while leaving gap counts unchanged. Candidate proposals do not mutate the snapshot. Focused regression suite covers canonicalized aliases, qualifiers, numeric units, duplicate-hash scope, catalog availability versus search exhaustion, and normalized snapshot validation.

### Chunk 2 completion record — QA pending

Implemented the offline Evidence Replay + Unified Gap Adapter scope described in `ROADMAP.md`. This record describes implementation status only; owner acceptance is pending. The deterministic parser covers engine displacement, motor power, catalog battery capacity, qualified rated range, dimensions/seats, and basic safety values. It does not perform AI extraction, HTTP acquisition, lineup reconciliation, live research, or writes. Both repository GitHub Actions workflows must complete successfully on the correction commit before owner acceptance.

The current QA correction sample replays 11 documents: 8 unique accepted into the evidence ledger, 3 documents held because identical bytes declare conflicting source/market/coverage metadata, 3 accepted field candidates, and 0 of 2 tracked priority gaps proposed for change. Accepted source candidates and gap reduction are separate measures. MOCK reports 0 HTTP, paid calls/tokens/spend, and writes.

## Chunk 3 — offline retail evidence and reconciliation

Complete lineups require more than a completeness label: the normalized source must carry a complete pagination/row manifest, a publisher scope assertion with exact quote and locator, matching page counts, a bound content SHA, and explicit rows. Edition and capture provenance must match a line in the hashed source content. The same document-bound evidence object controls eligibility and reconciliation. A partial, empty, or mismatched capture yields `HOLD`; omission from it can never be treated as discontinuation.

`retail-reconcile` performs pure same-model `MarketTrim` comparison using exact IDs plus model, generation, grade, powertrain, model-year and facelift identity. Aliases remain evidence metadata and are never used to merge canonical identity. Outcomes are `KEEP`, `ADD_PROPOSAL`, `SOFT_DISCONTINUE_PROPOSAL`, `HOLD`, or `REVIEW`. Identity collisions, historical/admin/owner-retired trims, and owner-protected Retail Set members receive review protection. Soft discontinuation requires quote-bound first-party Thai retail end-of-sale evidence or two independent complete Thai official negative lineup observations; both must omit the trim, be strictly chronological, satisfy the policy interval, and carry distinct content/edition hashes and content-bound capture provenance. A previous positive lineup plus one negative is insufficient. End-of-production evidence does not prove end-of-retail-sale. Omissions outside exact model/generation/model-year/facelift scope are held as out of scope. All structural outcomes remain proposals/dispositions; canonical writes stay zero and Price Ledger remains separately owned.

The proposed minimum negative-lineup evidence interval is policy data in `contract/policy.yaml`, currently 30 days and `PENDING_OWNER_APPROVAL`. It is validated, reported with each result, and independent of the research negative cache. The sample reconciliation output is `fixtures/sample_retail_reconciliation.json`. `CANDIDATE_PROPOSED` remains a proposal state; qualification review, canonical conflicts, and verification status cannot be converted into verified facts by this module.

### Chunk 3 correction record — QA pending

Corrected all six QA findings. Added adversarial regressions for previous-positive plus one-negative, independent negative editions from one publisher, reverse chronology, content-bound capture provenance, generation/model-year/facelift scope, forged model metadata, page-count mismatch, production-vs-retail end, and policy interval validation. Carried-forward regressions prove an eligible official Thai source reduces one genuinely missing P1 gap, mixed fact states are order-independent, and qualifier review remains unresolved. Sample simulator, evidence replay, and retail reconciliation outputs were regenerated. The implementation remains offline, deterministic, proposal-only, and zero-write. Chunk 3 was accepted at `38a6d1ac583c3a34b8d92de134ff72a6ad601209`; Chunk 4 implementation and its QA gate are recorded below.

## Chunk 4 — bounded planner and persistent OFFLINE runner

The `offline-plan`, `offline-step`, and `offline-report` commands use a local SQLite journal only. Planning validates the normalized snapshot and policy, checks the snapshot and local evidence/negative caches first, then creates scoped idempotent tasks with a relevant policy revision. RETAIL_AUDIT and SPEC_ENRICH retain independent validated service windows; contradictory aggregate guarantees fail policy validation. Daily request/time quota exhaustion defers the next job without leasing it or consuming an attempt, and the same queued job resumes on the next UTC day. Cached evidence is admitted only as a content-bound SourceDocument through the established Chunk 2 replay validator, and suppresses work only when accepted claims cover the exact required trim/field scope. Each planned job retains its normalized snapshot locally, and COMPLETED requires replay-validated evidence for that job’s model, generation, required trim/field set, or complete lineup scope. Missing or mismatched evidence remains retryable and is never cached under the wrong target. Completion and cache persistence use one SQLite transaction. Lease policy requires at least two seconds for safe renewal; the default remains 900 seconds. MOCK steps renew their lease deterministically during long simulated work. Leases, attempt counts, checkpoints, retry cooldowns, terminal stop states, measured daily usage, negative caching, and unchanged content-hash suppression survive process restarts. Each manual step requires explicit `--confirm-mock-only` acknowledgment, consumes one canned response, then re-engages both pause and kill switches. No worker loop, cron, HTTP, paid service, Production database, or canonical writer exists.

`fixtures/sample_offline_run/` is generated from a fixed fake epoch and local `SOURCE_EXHAUSTED` canned response. Structural interval policy remains `PENDING_OWNER_APPROVAL`; it is independent from research negative-cache cooldown.

### Chunk 4 correction record — QA pending

Correction regressions cover renewable request and elapsed daily quotas, forged and incorrectly scoped cached evidence, malformed source hashes, transactional cache-write failure plus restart, differing Retail Audit/Spec Enrichment service windows with both queues backlogged and a journal restart, and a 901-second MOCK response under the 900-second lease. Focused tests use fake time, SQLite, and a canned in-memory provider. Sample plan/step/report outputs were regenerated. The sample reports 0 external HTTP, paid calls/tokens/spend, Production database accesses/writes, canonical writes, and background workers. The two full GitHub Actions workflows must pass on this correction commit before renewed QA. This records implementation only; stop for QA and do not begin Chunk 5.
