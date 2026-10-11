# Stage-1 PR admission — non-managed smoke probe

**Date:** 2026-10-11
**Purpose:** verify the production GitHub workflow now loads `orchestration/pr-admission.mjs` from the actual **PR BASE** (after merged #206), compares the candidate HEAD against that trusted BASE, and reports `UNMANAGED_AUDIT_ONLY` / `enforcerAuthorized=false` for an ordinary PR with no task packet.

This is an **audit artifact only**. It is neither an approval for agents nor a request to enable task execution. This file intentionally makes no code/runtime/DB changes and should not be merged merely to satisfy the smoke check.

Expected:
- `enforcer-pr-admission` executes the trusted-base checker instead of emitting the bootstrap-only notice.
- The job succeeds but explicitly classifies the PR as `UNMANAGED_AUDIT_ONLY`, **not owner-approved**.
- The separate managed-deny smoke PR should fail Stage-1 admission while the canonical plan keeps `execution.enabled=false`.

Close this smoke PR after recording the observed evidence.
