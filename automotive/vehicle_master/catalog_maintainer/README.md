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

Recorded docs carry content hashes, local source IDs, capture dates, explicit trim/variant/powertrain coverage, quotes/line locators, source lineage, and extraction method. Retail-lineup completeness also requires a capture manifest whose listed rows match the document's trim IDs; a title or boolean alone cannot establish completeness. Spec sheets remain spec evidence and never change retail eligibility. Range values retain separate test basis and scope. Conflicting claims, unsupported units, stale/out-of-market sources, locked tombstones, historical or unadmitted trims are held/rejected. No price or P3 task is created.

Replay writes `replay_evidence.jsonl`, `field_candidates.jsonl`, `gap_diff.json`, and `replay_summary.json`. These are proposals/dispositions only: canonical writes, HTTP, paid model calls, paid tokens, and spend are always zero. Sample replay: 11 recorded documents, 3 accepted candidates (rated range, motor power, and AEB), conflicting battery claims held, and 0 writes/calls. Candidate proposals do not mutate the snapshot; replay-only gap counts change only for a proposed candidate that matches a tracked open gap. Focused tests: 30 pass from repository root and `automotive/vehicle_master/`.

### Chunk 2 completion record — QA pending

Implemented the offline Evidence Replay + Unified Gap Adapter scope described in `ROADMAP.md`. This record describes implementation status only; owner acceptance is pending. The deterministic parser covers engine displacement, motor power, catalog battery capacity, qualified rated range, dimensions/seats, and basic safety values. It does not perform AI extraction, HTTP acquisition, lineup reconciliation, live research, or writes. Full GitHub Actions were run on the resulting PR commit; see the PR checks for the final result.
