# R6 M7.0 offline recovery and shadow QA

This package preserves the original owner inputs and reproduces the M7.0 crosswalk
recovery offline. It never calls a writer or changes production. The live-review CSV
is a preserved read-only production export from 2026-10-12; the exact Ice Full Package
ZIP is the real M7.0 input. A new live SELECT snapshot could not be captured by the
current process because `SUPABASE_SECRET_KEY` is bound to the cloud environment but
was not injected into this shell. No credential value is stored here.

## Frozen inputs

`source_manifest.json` pins SHA-256 and byte counts for each source. Original inputs
are copied unchanged under `source/`, including the owner overlay, original local
override package, 244-row audit, prior live review and dry-run, rejected candidates,
recovery decisions, pickup registration-type split, redirects and original work state.
The M7.0 ZIP is pinned separately at SHA-256
`c558d2d4cc3ed667f8b30ea028dbb66c4030cdce4e7daabe735df870cb94677d`.

The 244-row owner ledger contains 92 links, 63 retained AUTO decisions, 51 exclusions,
and 38 identity creations. Its row-level output is `owner_decision_ledger_244.csv`;
technical exceptions are listed separately in `exception_only_review.csv` and do not
request a repeat review. The complete 1,200-row overlay also preserves earlier owner
decisions beyond that 244-row audit. The matcher package carries 430 exact
`owner_approved_identity_overrides`; those targets become `APPROVED/ADMIN` and keep
series correlation as diagnostic evidence, so an owner-approved Serena mapping cannot
fall back to `PROPOSED` at corr 0.974.

## Reproduce

From the repository root, rebuild the shadow identity target package and the row-level
dry run:

```bash
PYTHONPATH=automotive/vehicle_master python automotive/vehicle_master/tools/ice_crosswalk_build_owner_identity_package.py \
  --audit-csv data/packages/ice_crosswalk_r6_offline_recovery_M7.0/source/owner_overlay_original.csv \
  --package-zip data/packages/2569-09/v3_M7.0/TDR_FULL_2569-09_v3_M7.0.zip \
  --review-csv data/packages/ice_crosswalk_r6_offline_recovery_M7.0/source/live_review_original.csv \
  --model-dir automotive/vehicle_master/vehreg/data/2026/models \
  --output data/packages/ice_crosswalk_r6_offline_recovery_M7.0/owner_identity_targets.json
PYTHONPATH=automotive/vehicle_master python automotive/vehicle_master/tools/ice_crosswalk_r6_offline_recovery.py
```

The runner verifies that DIMS and registration-trend counts reconcile to 1,200 groups
and 4,141,987 registrations, rebuilds all 244 decisions, writes group/registration-
type shadow rows, emits all 675 source `UNMATCHED_NO_CANDIDATE` groups in descending
registration order, and replays the deterministic pass to verify an identical hash.
The row-level output is `shadow_crosswalk_rows.csv`; the 675-group classification is
`unmatched_classification_sorted.csv`; the shadow-only identity targets are
`shadow_identity_materialization.csv` and `owner_identity_targets.json`.

## Result and boundaries

`qa_summary.json` reports 4,122,556 shadow-covered registrations out of the fixed
4,141,987 denominator: **99.5309%**. The separately reported denominator after 58
owner-excluded groups is 4,128,086, yielding **99.8660%**. The fixed-denominator target
of 99.1% is met. All 244 owner decisions are present, all have the expected target or
exclusion in the shadow rows, and there are zero mismatches or repeat-review requests.

The 675 source-unmatched groups classify as 15 deterministic existing links, 9 invalid
or unspecified names, 133 genuinely ambiguous names, 516 low-volume groups, and 2
unresolved pickup splits. Fifteen now have deterministic targets; the other 660 remain
classified with evidence and are not sent back for another owner review. Low-volume is
only a priority label. The matcher uses no AI, paid API, guessed fuzzy link or sales-
share veto. Series evidence does not override owner decisions.

Pickup RY1/RY2-to-Double-Cab and RY3-to-other-cab rules are simulated in the shadow.
Classes without an exact same-brand target stay uncounted. Shadow identities have not
been written to `vehicle_models`, and no crosswalk row has been written or approved.
`--capture-live` is a separate GET-only option and is not required to reproduce the
offline result.
