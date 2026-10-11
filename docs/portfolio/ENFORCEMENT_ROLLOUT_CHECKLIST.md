# TDR Roadmap Enforcement — staged activation checklist

**Recorded:** 2026-10-11 · **Owner-approved portfolio roadmap:** v1.0 (merged via PR #204)  
**Repository Agent Bootstrap:** merged via PR #205.  
**Current change:** draft PR #206, Stage-1 read-only PR admission.  
**Activation:** NOT APPROVED/NOT ENABLED. Branch protection status has not been read or modified through the connected GitHub capability.

## Actual enforceability levels

| Level | What is technically true | Verified now |
| --- | --- | --- |
| P0 Approved plan in `main` | Roadmap v1.0 and approved portfolio contract are present | YES |
| P1 Agent bootstrap | `AGENTS.md` and `CLAUDE.md` direct reading and workstream gate precedence | YES, PR #205 merged |
| P2 Stage-0 preflight | Fails closed while `execution.enabled=false`; synthetic policy tests | YES, code present; CI result pending |
| P3 Stage-1 PR inspection | Check trusted PR BASE plan, HEAD Git changes, managed packet, domain hash and permissions | DRAFT PR #206, offline-only |
| P4 GitHub required status check | Ruleset on `main` makes invariant status unavoidable at merge | **NOT VERIFIED / NOT CONFIGURED HERE** |
| P5 Managed all-PR migration | Every PR either bound to owner-approved packet or explicitly dated grandfathered exception | **NOT ACTIVE** |
| P6 Autonomous Claude↔Codex worker | Separate sandbox, least privilege, retry/cost budget, reviewer evidence, production isolation | **NOT IMPLEMENTED** |

**Semantics:** P1 cannot prove model internal attention. P2/P3 cannot prevent GitHub bypass without P4. P3 does not authorize legacy PRs. A green CI result for an unmanaged PR is not a proof that it consumed the portfolio roadmap or has owner task authorization.

## Hard stops on protected production domains

Retain Vehicle Master Phase-1 missing-writer gate; Ice Market `R6_PRODUCTION_CROSSWALK` authorization is factually unresolved despite 490 crosswalk rows; no auto production import/approve/cutover; no new migration using reserved v57/v58; billing authority conflict not resolved; CTPDI published grain remains undecided. These are **domain-specific blocks** even after portfolio approval, not reasons to suspend unrelated offline work.

## Stage-1 rollout — do not conflate with live Night Shift

1. **Accept Stage-1 code only after native Node tests and current branch CI complete**:
   `node --test orchestration/preflight.test.mjs` and
   `node --test orchestration/pr-admission.test.mjs`.
2. **First merge bootstrap caveat:** PR #206 BASE does not contain Stage-1 checker. Its admission job prints a notice rather than executing the BASE checker. This is not independent Stage-1 acceptance; require explicit human review of the first implementation.
3. **Post-adoption smoke PR** (new harmless docs change): verify BASE-origin `pr-admission.mjs` is actually executed, reported Github base/head SHAs match, and `UNMANAGED_AUDIT_ONLY` does **not** claim Enforcer authorization.
4. **Negative managed PR** (synthetic `enforcer/` branch or `.tdr/enforcer-task.json`): the BASE plan still has `execution.enabled=false` and `task_queue=[]`, so the action must fail with `ENFORCER_DISABLED_IN_TRUSTED_BASE` / `TRUSTED_BASE_TASK_APPROVAL_MISSING_OR_CHANGED`. Do not merge the negative fixture.
5. **Required-check review:** once these pass, select the *exact* GitHub required status check names from actual completed run contexts. Suggested `portfolio-roadmap` and `enforcer-pr-admission`; verify check consistency before requiring both across all PRs. `Test TDR` and consolidated may have separate required contexts. Owners must configure main Branch Protection/Rulesets in GitHub; not a step this PR executes.
6. **Existing PR migration:** #200, #201, #203, and design graft branches may predate enforced packets and hold their own established gates. Define an explicit migration/grandfather date policy; do not label their unpacketized work as automatically approved or silently force a merge/rebase.
7. **Future managed-task enablement:** requires an independent owner-controlled queue, signed or GitHub-auditable approval provenance, bounded allowed paths and domain contract hash, trusted full diff including renames, read-only CI source checks, accepted test evidence for exact HEAD, deterministic retry limit, audit log and narrow least-privilege isolated worker. Activation is a separate versioned change and **cannot** be accomplished by changing `execution.enabled` in this branch.

## Local validation record for PR #206 (not a substitute for native Node)

2026-10-11 source-only exercise: imported the exact branch scripts and their regression case sources into a fresh V8 execution context with **mocked Buffer and SHA-256** and no I/O. **18/18 Stage-0 pure checks and 24/24 Stage-1 pure checks passed**. This validates pure decision behavior in a simulation but **does not run Node's actual crypto, child_process, filesystem, git checkout or native test runner**. GitHub Actions jobs were observed **queued** during this review; production CI PASS is not claimed.

## No-unattended-operation statement

`docs/portfolio/portfolio.plan.json` still has `execution.enabled=false`, no task queue and no delegated implementation authority. No automatic code agent, merge, deploy, paid API, production write, R6 repair, database migration or recurring automation is part of PR #206.
