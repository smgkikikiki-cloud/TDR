# TDR Vehicle Catalog Maintainer — offline simulator

Fixture-only implementation of deterministic catalog eligibility, gap inventory, two independently ranked queues, and evidence-gated structural proposals. It is not connected to production data. The in-package field registry exists only in the synthetic fixture; production must consume the canonical comparable-spec registry and its applicability semantics.

## Run

From repository root:

```bash
python -m unittest discover -s automotive/vehicle_master/tests/catalog_maintainer -v
python -m automotive.vehicle_master.catalog_maintainer.cli simulate \
  --fixture automotive/vehicle_master/catalog_maintainer/fixtures/sample_snapshot.json \
  --out automotive/vehicle_master/catalog_maintainer/fixtures/sample_output
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
