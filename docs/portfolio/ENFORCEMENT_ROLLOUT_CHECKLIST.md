# TDR Roadmap Enforcement — staged activation checklist

**Recorded:** 2026-10-11 · **Owner-approved portfolio roadmap:** v1.0 (merged via PR #204)  
**Repository Agent Bootstrap:** merged via PR #205.  
**Current state:** PR #206 merged to `main` at `efa7fe64fd6222520de82423525a590a1934a530`; Stage-1 positive/negative live smoke confirmed with PR #207 and #208 (both closed, unmerged).  
**Activation:** Agent dispatch remains DISABLED. A rulesets GET returned `[]`, but branch-protection GET was `403 Resource not accessible by integration`; no branch protection write or validation has occurred.

## Actual enforceability levels

| Level | What is technically true | Verified now |
| --- | --- | --- |
| P0 Approved plan in `main` | Roadmap v1.0 and approved portfolio contract are present | YES |
| P1 Agent bootstrap | `AGENTS.md` and `CLAUDE.md` direct reading and workstream gate precedence | YES, PR #205 merged |
| P2 Stage-0 preflight | Fails closed while `execution.enabled=false`; synthetic policy tests | YES; native CI 18/18 PASS |
| P3 Stage-1 PR inspection | Check trusted PR BASE plan, HEAD Git changes, managed packet, domain hash and permissions | YES; merged #206, 24/24 pure + 4/4 Git integration native CI and live smoke PRs #207/#208 |
| P4 GitHub required status check | Repo owner/admin must set required checks for `main` and prove red PR cannot merge | **NOT CONFIGURED/VERIFIED**. GET rulesets empty; branch-protection read forbidden to this app |
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
3. **PASSED — PR #207**: actual native GitHub job `enforcer-pr-admission`, run 38127550047 / job 114434952194, executed the BASE-origin checker and returned `UNMANAGED_AUDIT_ONLY`, `enforcerAuthorized=false`, correct base/head Git SHAs. Closed unmerged.
4. **PASSED — PR #208**: intentionally unauthorized synthetic `enforcer/`-branch packet; native job run 38127552999 / job 114434960773 exited 1 and reported `DENIED`, `enforcerAuthorized=false`, `ENFORCER_DISABLED_IN_TRUSTED_BASE` and `TRUSTED_BASE_TASK_APPROVAL_MISSING_OR_CHANGED`. Expected red CI; closed unmerged.
5. **Required-check setup (outstanding):** `enforcer-pr-admission` runs on all PRs. The original `portfolio-roadmap` used path filtering and **cannot safely be mandatory across every PR until its trigger is broadened**; see Required-Check Trigger Hardening PR. After the patch is merged and CI confirms it runs on unrelated PRs, an admin must configure required checks `enforcer-pr-admission`, `enforcer-stage1-tests`, `portfolio-roadmap` for `main` in Settings → Rules → Rulesets or branch protection, verify the actual reported contexts and test with a deliberately failing PR. Do not make `Test TDR` jobs mandatory without reviewing their trigger conditions.
6. **Existing PR migration:** #200, #201, #203, and design graft branches may predate enforced packets and hold their own established gates. Define an explicit migration/grandfather date policy; do not label their unpacketized work as automatically approved or silently force a merge/rebase.
7. **Future managed-task enablement:** requires an independent owner-controlled queue, signed or GitHub-auditable approval provenance, bounded allowed paths and domain contract hash, trusted full diff including renames, read-only CI source checks, accepted test evidence for exact HEAD, deterministic retry limit, audit log and narrow least-privilege isolated worker. Activation is a separate versioned change and **cannot** be accomplished by changing `execution.enabled` in this branch.

## Validation record for merged PR #206

Native GitHub Actions passed **18/18 Stage-0**, **24/24 Stage-1**, **4/4 real Git checkout/diff integration** tests, plus Roadmap Contract, Test TDR and Test TDR consolidated CI. After merge, PR #207 succeeded in unmanaged audit-only mode and PR #208 failed as expected for missing approval. The earlier V8 simulated logic checks are superseded by these native tests and real PR smoke observations. Still **not** evidence of required branch protection or Night Shift activation.

## No-unattended-operation statement

`docs/portfolio/portfolio.plan.json` still has `execution.enabled=false`, no task queue and no delegated implementation authority. No automatic code agent, merge, deploy, paid API, production write, R6 repair, database migration or recurring automation is part of PR #206.
