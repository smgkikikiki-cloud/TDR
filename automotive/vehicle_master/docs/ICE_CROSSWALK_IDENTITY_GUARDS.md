# ICE ↔ TDR identity guards — 2026-10-13

## Scope of this patch

Candidate rejection / review rules for the existing `tools.ice_crosswalk_match`.
No schema migrations, existing crosswalk edits, canonical-model creation,
approved mapping rewrites, or production operations are part of this patch.

The live input has **1,200** Ice groups. **489** have some crosswalk row
(**82 AUTO**, **407 group-level PROPOSED**; 490 total crosswalk rows); **711** have
no crosswalk row. The unmatched groups cover **136,129** registration records;
**527 of the 711** have at most five records. These are as-observed snapshot
counts, not a claim of mapping correctness.

## Owner rules

1. Normalize punctuation/case and remove brand prefix. A standalone `L` or
   `l` token present on exactly one side is a **hard identity split**, for every
   brand. An `l` within another word or code is not a standalone token.
2. Compare *Latin letters* in normalized nameplate with Levenshtein edit
   distance (numbers excluded here). More than three edits is a hard split.
   Candidate cannot be inserted as AUTO or PROPOSED by the matcher.
3. For **Audi, BMW, Volvo, Lexus, Peugeot, Ferrari, Zeekr, Mazda, MG**,
   differing alphanumeric code tokens prevent **AUTO**. Retain a proposed
   pair for owner inspection if independent evidence otherwise supports it.
   The rule is conservative: a potential marketing label or true renamed
   model still needs an explicit reviewed alias; the algorithm cannot assume one.
4. Registration class discriminator for pickups:
   `RY1` → **Double Cab**; `RY3` → **Cab (single + smart/space)**;
   `RY2` is treated with the RY1-side pickup body **only under the
   documented owner policy**, not as a global relabeling for every vehicle.
   For model names explicitly ending in `Cab` / `Double Cab`, reject the
   opposite candidate. A mixed `RY1/RY3` or `RY2/RY3` Ice group cannot be
   safely represented by the current untyped crosswalk key: emit
   `REG_TYPE_SPLIT_REQUIRED` on the review sheet and **make no upsert**.

Current matching must retain evidence from both series and names and must never
treat a high series correlation as permission to override a hard identity split.

## What remains unresolved

* The current schema identifies a crosswalk row by Ice group and TDR model,
  without a `reg_type` discriminator. Complete pickup resolution requires
  a new registration-scoped mapping keyed by `(model_group_id, reg_type,
  canonical_model_id)`, an API/consumer cutover, and backfill with an audit of
  group-level legacy mappings. This patch **quarantines** mixed groups rather
  than claiming to split registration totals between canonical models.
* Strict negative guards cannot create an absent TDR canonical model. The
  **711 unmatched** groups still need a discovery/identity staging workflow.
  The **527 groups with at most five registrations** may be reviewed manually
  in a low-volume queue; the remaining **184** are prioritized by volume.
* Existing PROPOSED / AUTO rows are not retroactively corrected. A separate
  read-only audit must flag bad historical proposals (e.g. D-Max → MU-X,
  Mazda BT-50 → CX-30). Never bulk-approve those 407 proposals.
* Known aliases approved by the owner must have explicit provenance. Do not
  silently suppress these identity guards by adding general fuzzy exceptions.

## Acceptance

* Unit tests for isolated L, >3 Latin-letter edits, targeted brand code
  changes, and the existing Maxus/Mifa alias.
* Orchestrator tests proving mixed pickup classes do not call the writing RPC,
  and single-reg-class candidates cannot select the opposite Cab identity.
* Strong series cannot override a hard nameplate block; a sensitive-brand
  code mismatch downgrades would-be AUTO to PROPOSED.
* **No DB writes, no auto promotion, no merge.** Integrate with any separate
  working-tree `--dry-run` changes after both are reviewed.
