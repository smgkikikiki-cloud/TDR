# P6 Price Intelligence artifact lineage

P6 does not use a mutable `run_id` as the authority for promotion. A price candidate can legitimately survive across multiple fetch/reconcile runs during the 24-hour confirmation window, so one global run ID would either be misleading or would need special-case rollover rules.

The canonical lineage chain is content-derived instead:

```text
P2-P4 fetch/match artifact
  source_batch_id = pbatch:<sha256>
        ↓
P5 reconcile report
  reconcile_id = prec:<sha256>
        ↓
post-P5 CandidateBook snapshot
  candidate_state_id = pstate:<sha256>
        ↓
human review bundle
  carries all three IDs
        ↓
P6 promotion
  recomputes and verifies all identities before planning a canonical write
```

## Why no extra run_id

A `run_id` would identify an execution, not the actual evidence/state contents. Two executions can produce the same semantic artifact, while one execution can also create several different artifacts. Content-derived IDs answer the question P6 actually cares about: "are these exactly the bytes/semantic contents the reviewer saw?"

The identities deliberately exclude mutable operational metadata such as robots diagnostics and file paths, but include the semantic data that can affect a price decision. A later real fetch observation changes `source_batch_id` because the result contains a different `fetched_at`, even when the source bytes and `SourceDocument` hash are unchanged.

## Required invariants

1. The supplied fetch artifact must recompute to its declared `source_batch_id`.
2. The supplied reconcile report must recompute to its declared `reconcile_id`.
3. The reconcile report must name the supplied fetch `source_batch_id`.
4. The reconcile report's `candidate_state_after_id` must equal the supplied CandidateBook snapshot.
5. Review decisions must carry the exact `source_batch_id`, `reconcile_id`, and `candidate_state_id` they were generated from.
6. Changing the fetch, rerunning reconciliation, or changing CandidateBook state invalidates an old review even if the candidate ID itself is unchanged.
7. Candidate identity is intentionally not a lineage identity. Candidates persist across observations; artifact snapshots do not.

## Operational consequence

Never copy an APPROVE decision into a newly generated review JSON by hand. Regenerate the review queue from the current fetch + reconcile + candidate-state artifacts and review that snapshot. This keeps the human approval bound to the exact evidence and staging state that P6 will promote.
