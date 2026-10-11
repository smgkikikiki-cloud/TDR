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
```

Reproduce the fixture output from the package directory's parent repository root using those exact commands. No credentials, optional packages, external services, or database are used. `--budget 0` returns empty queues. A positive `--budget` caps each queue independently, so a Retail Audit backlog cannot consume the Spec Enrichment allowance. The merged queue follows a finite policy-configured service cycle. Output contains `queue.csv`, `decisions.jsonl`, and `summary.json`.

## Queue semantics

- `RETAIL_AUDIT` is a model-level P0 task when a CURRENT model's live Thai lineup is not established.
- `SPEC_ENRICH` is available only for trims admitted by an owner-approved current-retail set or an official Thai-market source that explicitly declares `COMPLETE_LINEUP` and identifies its current trim IDs. Partial and individual-trim documents stay in Retail Audit.
- An owner-approved set is the membership authority; nonmembers are excluded even if their row says CURRENT or other signals imply activity.
- Spec gaps are grouped by model/document and field group with P1/P2 kept distinct inside mixed groups. Vehicle Master `value_state` (`KNOWN`, `UNKNOWN`, `NOT_AVAILABLE`, `NOT_APPLICABLE`, `ABSENT`, and locked null tombstones) is separate from `verification_status` (`VERIFIED`/`PROVISIONAL`). Existing facts and payload values suppress duplicate gaps; P3 never opens a task; prices are ledger-owned.
- RY1 and RY3 are selected through each model's declared registration profile, normalized within compatible strata and periods, and never summed together or with `*` aggregate rows. Registration contributes only to Retail Audit ranking and is never evidence.
- Job keys hash only the model's relevant identity/scope, document hashes, or field-gap bundle. An unrelated model/fact update does not regenerate every job.

`contract/SPEC.md` records the proposed V3 §4 permission amendment. It is not adopted policy and this package has no writer, scheduler, HTTP client, or model-provider dependency.

## Chunk 2 — offline evidence replay

`replay` reads only local JSON documents and the normalized fixture. Its fixed line grammar produces candidates only for exact existing Thai model/generation/trim identities. The read-only adapter pins the canonical 2026 comparable-spec registry (`vehreg/data/2026/product/comparable_specs/registry.json`) and the `trim-editor-fields.ts` alias source by SHA-256; missing or changed files fail closed. Vehicle Master field type, canonical unit, qualifiers, and powertrain applicability come from that registry. Fixture priority tiers remain an isolated policy overlay.

Recorded docs carry content hashes, local source IDs, capture dates, explicit trim/variant/powertrain coverage, quotes/line locators, source lineage, and extraction method. Retail-lineup completeness also requires a capture manifest whose listed rows match the document's trim IDs; a title or boolean alone cannot establish completeness. Spec sheets remain spec evidence and never change retail eligibility. Range values and other qualified fields retain their required comparison qualifiers; values with distinct or unproven qualifiers are not conflated. Dimensional numbers require a unit in the quoted claim, while seat counts remain unitless. Same-hash documents with conflicting market/authority/coverage metadata are held together instead of letting sort order choose a winner. Replay validates the normalized snapshot before indexing. `NOT_AVAILABLE` remains a catalog value state and does not imply persisted search exhaustion. Conflicting claims, stale/out-of-market sources, locked tombstones, historical or unadmitted trims are held/rejected. No price or P3 task is created.

Replay writes `replay_evidence.jsonl`, `field_candidates.jsonl`, `gap_diff.json`, and `replay_summary.json`. These are proposals/dispositions only: canonical writes, HTTP, paid model calls, paid tokens, and spend are always zero. The summary distinguishes accepted source candidates from the number that actually match an open priority gap; a valid candidate can be accepted while leaving gap counts unchanged. Candidate proposals do not mutate the snapshot. Focused regression suite covers canonicalized aliases, qualifiers, numeric units, duplicate-hash scope, catalog availability versus search exhaustion, and normalized snapshot validation.

### Chunk 2 completion record — QA pending

Implemented the offline Evidence Replay + Unified Gap Adapter scope described in `ROADMAP.md`. This record describes implementation status only; owner acceptance is pending. The deterministic parser covers engine displacement, motor power, catalog battery capacity, qualified rated range, dimensions/seats, and basic safety values. It does not perform AI extraction, HTTP acquisition, lineup reconciliation, live research, or writes. Both repository GitHub Actions workflows must complete successfully on the correction commit before owner acceptance.

The current QA correction sample replays 11 documents: 8 unique accepted into the evidence ledger, 3 documents held because identical bytes declare conflicting source/market/coverage metadata, 3 accepted field candidates, and 0 of 2 tracked priority gaps proposed for change. Accepted source candidates and gap reduction are separate measures. MOCK reports 0 HTTP, paid calls/tokens/spend, and writes.

## Chunk 3 — offline retail evidence and reconciliation

Complete lineups require more than a completeness label: the normalized source must carry a complete pagination/row manifest, a publisher completeness assertion with exact quote and locator, matching expected/captured page counts, a bound content SHA, and explicit rows. A partial, empty, or mismatched capture yields `HOLD`; omission from it can never be treated as discontinuation. The normalized snapshot contract applies the same explicit evidence requirement to source-confirmed current lineups.

`retail-reconcile` performs pure same-model `MarketTrim` comparison using exact IDs plus model, generation, grade, powertrain, model-year and facelift identity. Aliases remain evidence metadata and are never used to merge canonical identity. Outcomes are `KEEP`, `ADD_PROPOSAL`, `SOFT_DISCONTINUE_PROPOSAL`, `HOLD`, or `REVIEW`. Identity collisions, historical/admin/owner-retired trims, and owner-protected Retail Set members receive review protection. Soft discontinuation requires quote-bound first-party Thai end-of-sale evidence or two distinct official complete captures with independent source, lineage, and content hashes separated by the policy interval. All structural outcomes remain proposals/dispositions; canonical writes stay zero and Price Ledger remains separately owned.

The sample reconciliation output is `fixtures/sample_retail_reconciliation.json`. `CANDIDATE_PROPOSED` remains a proposal state; qualification review, canonical conflicts, and verification status cannot be converted into verified facts by this module.

### Chunk 3 implementation record — QA pending

Added explicit normalized completeness evidence, deterministic source validation, exact identity reconciliation, and adversarial proposal gates. Carried-forward regressions prove an eligible official Thai source reduces one genuinely missing P1 gap, mixed fact states are order-independent, and qualifier review remains unresolved. Local focused suite: 46 tests pass from repository root and `automotive/vehicle_master/`. Offline sample replay and trim reconciliation outputs regenerated. Full GitHub Actions status is pending for this correction commit; no live calls or canonical writes were enabled.
