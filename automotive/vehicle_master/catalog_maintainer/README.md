# TDR Vehicle Catalog Maintainer — offline simulator

Fixture-only implementation of deterministic catalog eligibility, gap inventory, two queue planners, and evidence-gated structural proposals. It is not connected to production data. The in-package field registry exists only in the synthetic fixture; production must consume the canonical comparable-spec registry and its applicability semantics.

## Run

From repository root:

```bash
python -m unittest discover -s automotive/vehicle_master/tests/catalog_maintainer -v
python -m automotive.vehicle_master.catalog_maintainer.cli simulate \
  --fixture automotive/vehicle_master/catalog_maintainer/fixtures/sample_snapshot.json \
  --out automotive/vehicle_master/catalog_maintainer/fixtures/sample_output
```

Reproduce the fixture output from the package directory's parent repository root using those exact commands. No credentials, optional packages, external services, or database are used. `--budget 0` returns an empty queue. Output contains `queue.csv`, `decisions.jsonl`, and `summary.json`.

## Queue semantics

- `RETAIL_AUDIT` is a model-level P0 task when a CURRENT model's live Thai lineup is not established.
- `SPEC_ENRICH` is available only for trims admitted by an owner-approved current-retail set or a source-confirmed lineup.
- An owner-approved set is the membership authority; nonmembers are excluded even if their row says CURRENT or other signals imply activity.
- Spec gaps are grouped by model/document and field group. Existing facts and payload values suppress duplicate gaps; powertrain-inapplicable fields are `NOT_APPLICABLE`; P3 never opens a task; prices are ledger-owned.
- Registration contributes only to deterministic Retail Audit ranking and is never evidence.

`contract/SPEC.md` records the proposed V3 §4 permission amendment. It is not adopted policy and this package has no writer, scheduler, HTTP client, or model-provider dependency.
