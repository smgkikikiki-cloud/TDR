# TDR Enforcer — Stage 0 read-only preflight

**Master plan:** [docs/portfolio/TDR_MASTER_ROADMAP_V1.md](../docs/portfolio/TDR_MASTER_ROADMAP_V1.md) (owner-approved v1.0; use the real main-branch file, not an independent chat synopsis).  
**Current behavior:** verifies repository/bootstrap invariants and evaluates future bounded Task Packets **without dispatching a worker**. The canonical plan in [portfolio.plan.json](../docs/portfolio/portfolio.plan.json) retains `execution.enabled=false`, `task_queue=[]`, `auto_merge=false`, `production_access=false`. **There is no Night Shift worker implementation or activation in this PR.**

## Human-first operational model

1. Claude Code and Codex read `AGENTS.md` and the owner-approved roadmap (plus domain-local source contracts). `CLAUDE.md` adds an explicit reading order for Claude.
2. A future Enforcer computes the *actual SHA-256* of the full roadmap file and checks the packet's `roadmap_version` + `roadmap_sha256`; AI self-report is not proof of compliance.
3. The tool checks that the task is explicitly present with `APPROVED` status in the *canonical owner-controlled queue*, with a matching independent owner authorization reference; paths and allowed capabilities must be bounded.
4. A future dispatcher would perform independent GitHub commit/diff checks, lease control, continuous CI status checks, test artifacts and Codex review, then return the draft PR to the owner. **Those dispatch/postflight functions are not implemented in Stage 0**.
5. Existing independent PRs #200, #201 and #203 retain their separate scope/QA/owner gates. Do not rebase/merge/cutover automatically merely because the portfolio document has been adopted.

### Locally reproducible checks

```bash
node orchestration/preflight.mjs --check-repo
node --test orchestration/preflight.test.mjs
```

The CLI emits a JSON PASS/FAIL report. The `--task-file <json> --changed-files-file <txt>` form exists for future integration and **will fail** against the current canonical `execution.enabled=false` plan (intentionally). It does **not** execute the packet.

A **task contract** must contain:
- `schema='tdr.task-packet.v1'`, unique `task_id`
- `roadmap_version='1.0'`, `roadmap_sha256` of actual roadmap contents
- immutable, valid Git `base_sha` pin; actual `head_sha` comes from the verified GitHub event at CI runtime
- `owner_authorized=true`, independently auditable `approval_ref`, matching `APPROVED` queue entry
- `execution_mode='OFFLINE'`, `allowed_paths`, explicit `dependencies` and `required_tests`
- `permissions` with no live network, paid AI, production writer, migration, merge or deploy

**No task is whitelisted by this README.** The pure unit tests use **in-memory synthetic plans** with `execution.enabled=true` to test positive/negative logic; never persist that state.

## CI activation and limits

`.github/workflows/portfolio-roadmap.yml` runs **read-only** repository contract checks + deterministic unit tests when governance files change or on manual dispatch. It does not run an implementer, review source diffs of arbitrary existing feature PRs, or enforce code-branch protection by itself.

This CI job is not automatically a **required merge check**. A maintainer must configure GitHub branch protection/rulesets for the exact check `portfolio-roadmap`, verify its green status and decide how to handle **pre-existing draft branches that do not contain the new bootstrap files**. Do NOT enable it as globally required before a compatible migration policy exists.

**Next separately bounded implementation:** an integration preflight that compares GitHub's authoritative changed-files list (including both sides of renames), verifies base/head and per-domain gate/owner approvals, verifies recorded test outcomes for the exact SHA and rechecks after each proposed fix. That work must happen under a separate approved task and independent QA.

## Stage 1 — PR admission inspection (read-only, non-dispatching)

New: `orchestration/pr-admission.mjs` + `pr-admission.test.mjs`, checked by `.github/workflows/enforcer-pr-admission.yml`.

**Source-of-truth split:**
- **BASE checkout at GitHub event `pull_request.base.sha`** supplies the checker script, approved `portfolio.plan.json`, roadmap and agent instruction files. The base policy must be a real exact SHA; never accept an untrusted PR's replacement plan/approvals.
- **HEAD checkout at GitHub event `pull_request.head.sha`** supplies only the proposed Git diff, file modes and optional `.tdr/enforcer-task.json` packet. The script verifies both actual Git SHAs and examines the full NUL-delimited name-status diff, including **both paths in rename/copy**.
- `base_sha` in a committed Task Packet must match GitHub's base SHA. **Do not include `head_sha` inside a file committed to that same HEAD:** that would be an impossible self-reference. GitHub's own event + `git rev-parse HEAD` provide the immutable HEAD SHA *during the CI run*.
- A future externally authorized **base-branch** queue entry must pin task ID, approval reference, approved source base SHA, roadmap SHA256/version, path allowlist, required tests and **exact domain, contract path, version and SHA-256**. The independent checker rereads that contract from BASE and verifies its digest; a `CLEARED` string or an unrelated domain's v1 label is insufficient. This cannot be forged by adding approval to PR-head `portfolio.plan.json`.
- The checker refuses protected files, out-of-scope renames, unknown dependencies, missing HEAD file-mode evidence, symlinks/submodules, missing independent domain approval, live/paid/writer/migration/merge/deploy capabilities, and any managed task while the owner-controlled plan keeps `execution.enabled=false`.

```bash
node --test orchestration/pr-admission.test.mjs
# PR-mode invocation by GitHub Actions; requires *real* BASE and HEAD checkouts:
node policy/orchestration/pr-admission.mjs \
  --event "${GITHUB_EVENT_PATH}" \
  --policy-root "${PWD}/policy" \
  --candidate-root "${PWD}/candidate"
```

**Staged enforcement:** a PR containing a packet at `.tdr/enforcer-task.json` or using `enforcer/` branch name is classified as a **MANAGED** request. A legacy PR with neither is `UNMANAGED_AUDIT_ONLY`: this is an audit, **not** an Enforcer authorization nor proof the branch follows the Roadmap. Current plan is disabled, so **no managed packet can be admitted**. An offline test can simulate `enabled=true` in memory without changing the real plan; even successful pure validation returns `enforcerAuthorized=false` because no worker dispatcher/postflight exists.

**First merge/bootstrap caveat:** the Stage-1 workflow runs pure tests from the candidate head; its base-trusted PR admission job activates only **after the Stage-1 checker exists on `main`**. On its own initial PR it emits an explicit bootstrap notice. Subsequent PRs invoke the trusted base checker. Candidate-file tests are not equivalent to a trusted base policy.

**Branch protection caveat:** neither creating this workflow nor a local `ok:true` makes it a required check. GitHub rulesets/check policy, CODEOWNERS/protected governance paths, migration of older open PRs, actual CI completion and provenance of owner approval require separate verification before hard enforcement. Automatic merge/deployment/dispatch remain unsupported.

## Stage-1 central CI compatibility fix (2026-10-11; proposed)

**Incident:** Legacy PR #201 (GitHub run [38128865165](https://github.com/smgkikikiki-cloud/TDR/actions/runs/38128865165)) and PR #203 ([38128785197](https://github.com/smgkikikiki-cloud/TDR/actions/runs/38128785197)) failed `enforcer-stage1-tests` because the central GitHub workflow checked out PR HEAD before executing `orchestration/preflight.test.mjs`, which did not exist in those historical branches. Their separate `enforcer-pr-admission` jobs succeeded **only** through a historical-base bootstrap notice; this was **never task authorization**. The separately named attachment `TDR_Enforcer_Incident_Report_2026-10-11.md` was not exposed to this review session; factual reconstruction used the supplied incident description plus actual GitHub job logs.

**Correction, source and identity:**

- `enforcer-stage1-tests` now checks out **trusted repository default branch** to `trusted-enforcer/` and runs all Enforcer self-tests there. The exact Git commit SHA is recorded in Actions logs. Historical PR HEAD code is not executed as CI self-tests. This separates **central governance implementation QA** from independent feature-branch CI.
- `enforcer-pr-admission` keeps using the PR's **exact BASE SHA** for policy and executable admission script whenever `policy/orchestration/pr-admission.mjs` exists. It still reads the **candidate HEAD only as untrusted Git diff and optional manifest**; nothing from HEAD is run as admission logic.
- When a historical BASE has no admission script, the former unconditional `exit 0` bootstrap is replaced by the versioned central `orchestration/historical-pr-audit.mjs` reader. It verifies repo/PR identity, exact BASE and HEAD checkouts, full diff (including both paths in renames), and whether the candidate contains any `.tdr/enforcer-task.json`. **Only an ordinary historical PR can receive `UNMANAGED_AUDIT_ONLY`, always with `enforcerAuthorized=false`.**
- Historic `enforcer/*` branches or manifests are **DENIED**, as are attempts by a historical candidate to alter `AGENTS.md`, `CLAUDE.md`, Enforcer code, workflow files or portfolio governance docs. A domain-specific `docs/WORK_STATE.md` modification (observed in existing PR #201) is not *by itself* an Enforcer request; it is reported as a risk warning, not approved or denied on some invented policy.
- The **present canonical portfolio plan remains disabled**, and this change does not create or authorize an Enforcer worker. A successful audit is a compatibility result only. Existing PR #201/#203 domain review and CI remain separate and cannot be bypassed.

The accompanying `orchestration/historical-pr-audit.test.mjs` contains isolated temporary Git repository regression cases for old branches, normal unmanaged history, explicit managed deny, suspicious governance changes and SHA mismatch. The central workflow discovers these tests from its **trusted checkout** once this change is adopted into `main`. It does **not** falsely claim to test candidate-proposed governance code in a legacy PR.

**Operational compatibility:** PR #209 independently changes `.github/workflows/portfolio-roadmap.yml` to remove its PR path filter. This patch edits only `.github/workflows/enforcer-pr-admission.yml` and Enforcer compatibility code/documentation; do not merge branches into one another or preempt #209.

**QA gate:** Existing CI jobs on this proposed PR can validate the currently adopted trusted main Enforcer; a separate, clean native run against the proposed compatibility source and an after-merge smoke against actual #201/#203 PR events is still required to prove the new flow. Re-running an old pre-fix Actions attempt alone cannot prove that a new version of the workflow was used. Branch protection and Night Shift remain separately gated.

## Security boundaries

- File/diff path filters are an early safety check, not OS sandboxing. Running Claude/Codex with powerful shell/tools and production credentials is still unsafe even if a JSON packet passes. Future workers need an isolated, least-privileged environment without DB secrets or unrestricted network.
- The Stage-0 checker **does not know that a human really read the roadmap**. It checks machine-known content hashes and instruction pointers. A tampered CI script on a branch or self-reported task approval is not an independent authority; protect source-controlled policy files and set required CI/rulesets after migration.
- Documentation and roadmap-level approval are distinct from formula/data readiness, target-specific PR QA, R6/R7/R8, writer, payment and deployment authorization.
