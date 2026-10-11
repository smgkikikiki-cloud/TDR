# Interface request to Identity Resolution (PR #200) — complete pair-level relation export

**Status:** a request for a later, separate change. PR #201 does not implement it, does not modify PR #200 and does not fork its rules.

**Why.** Today PR #200's published `after_rev4.json` lists pair ids only for the three kinds that rev 4 changed (FUZZY, SIBLING, EQUAL_VIA_MODEL_ALIAS). Bootstrap's shadow stand-in still generates EQUAL, EQUAL_VIA_TOKEN_EQUIV, SUBJECT_COARSER and SUBJECT_FINER itself, and the counts disagree
(Ice×TDR EQUAL 299 vs 239, SUBJECT_COARSER 46 vs 58, SUBJECT_FINER 45 vs 35; Ice×Ice EQUAL_VIA_TOKEN_EQUIV 0 vs 1). Until the export is complete, every Bootstrap verdict in the shadow is `IR_PARITY_UNRESOLVED`: a CREATE may rest on a relation the stand-in missed or invented.

**Request.** For the pinned M7.0 snapshot, publish deterministically (sorted keys, no timestamps), under a version label and the source-blob hashes:
1. Every pair of both populations with its relation, for **all nine** relation values including CONTRADICTION/UNAVAILABLE counts, keyed `"<subject_id>|<peer_id>"` (Ice×Ice with the smaller id first, as now; Ice×TDR as `subject|canonical_id`).
2. The Ice×TDR candidate pool definition used (which TDR models were compared for each subject), so population differences are inspectable.
3. The tokenisation each side used for each subject/peer (normalised tokens), so brand-prefix stripping differences are visible.
4. The decision-relevant subset per subject: the best relation to a TDR model and the engine outcome, which `after_rev4.json` already has.

**Acceptance for PR #201 once available.** `ir_rev4.adjudicate` is replaced by a direct lookup (no stand-in relation at all), `IR_PARITY_UNRESOLVED` clears per subject when its every relation is read from the export, and the parity tests assert 9/9 relation-kind equality. Registration data, activity and volume are not part of this interface.
