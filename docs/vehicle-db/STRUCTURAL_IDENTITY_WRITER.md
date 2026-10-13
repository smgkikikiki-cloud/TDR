# Vehicle Master Structural Identity Writer — Issue #236

Status: bounded offline implementation; independent QA and database integration remain open. No production adapter/route, state-changing SQL, migration allocation, gate advancement, merge, deployment or Price Fetcher changes.

Source: PR #235 `b5a6bcff2870afb8d81d672dd284e7935e3cb4ac` on `codex/r6-m7-real-acceptance-20261013`. Development branch: `codex/vm-structural-identity-writer-20261013`, based on that exact source; PR #235 remains unchanged. Approved portfolio roadmap v1.0 source `42be6b6a803727086b404b2cb46f75593bb2c1d4`; main baseline `c2715cbee494ae076b2582ef99f2bbc590b5dd99`. Domain contracts: Vehicle DB v3 §3–5/§12, v60 legacy closure, and separate Ice R6 gate. The uploaded owner task is preserved with normalized whitespace under `structural-writer/owner_task_236.txt` (original attachment SHA256 `d8a36074e1237bc8131fec2e9caaffb982fa8b977186c49dd53e4db5fe2a8aec`); Issue #236/PR API access returned 403.

## Audit first / bounded implementation

[Legacy writer audit](STRUCTURAL_IDENTITY_WRITER_AUDIT.md) records active callers, component classifications and the reuse decision. Cleanup commit `bf70150a` removes only the unused database-writing implementation of `lib/canonical-write-shadow.ts`; exported compatibility types/function remain a no-write disabled guard. Python file writer/worker modules, workflow guards, historical DB objects and all production RPCs stay intact because callers/history remain.

`lib/vehicle-engine/structural-writer.ts` extends the existing Vehicle Engine boundary. It reuses canonical serialization from `specs.ts`, canonical vocabulary/cross-facet validation from `taxonomy.ts`, the actor-kind contract from `price-writer.ts` (type only), and registration-class normalization from the existing R6 scoped reader. It never invokes the price writer/RPC, retired queue or legacy file writer.

`planStructuralChanges(snapshot, batch)` is deterministic and read-only. It validates `CREATE_BRAND`, `CREATE_MODEL_BASIC`, `UPDATE_MODEL_ALIAS` and `LINK_ICE_MODEL_GROUP_BY_REG_TYPE`. It checks existing canonical IDs/brand FKs, global slugs, same-brand names/aliases (including hidden historical identities), unique batch targets, model-vs-trim evidence, pickup parent aliases and expected revisions. Several source groups may link to one canonical identity; group/class keys remain unique. Letters/numbers are retained by model identity normalization, including 6/6e, A3/S3 and Atto 1/2. New non-equivalent model aliases require trusted reviewed equivalence evidence; an absent conflicting model is not permission to invent an alias. Existing aliases may be preserved or removed without rewriting history. No new match scoring/AI architecture is introduced.

New basic models have no generation, price band, trim, guessed classification or CURRENT claim. Canonical Segment/Body Type are NULL/UNKNOWN unless trusted, approved TDR evidence for that exact identity exists in the store snapshot. Ice values remain only in immutable raw observation evidence. Raw request JSON cannot set canonical classification fields or actor/approval permissions.

`StructuralIdentityWriter` executes through a serializable `TransactionalIdentityStore` contract. The shipped adapter is `scripts/test-support/structural-identity-store.ts`, an in-memory test double; it never persists Vehicle Master files or reaches a database. Server permissions are injected from verified credentials. Non-admin principals can propose and store observations, but cannot apply/approve/revert. `structural-writer-server.ts` provides the existing admin-session boundary without registering a route/DB adapter; its R6 permission remains false. Approval re-reads the snapshot and replans, rather than applying a stale preview. Source-change dedupe suppresses already-decided identical evidence despite a new retry timestamp/key.

Apply is atomic across identities/aliases/links, observations, audit and idempotency receipt. Expected revisions prevent stale updates; repeated identical requests do not create extra rows/revisions; reused keys with different payloads are rejected. All changes map to the existing catalog-topic revision convention. Revert creates compensating audit entries, increments revisions, hides created identities instead of deleting them, refuses stale after-state or active dependents, and does nothing on a second revert. Scoped apply/revert requires separate R6 permission even for an admin. The fake-store tests may simulate authorization; no simulation grants production permission.

## Nine-identity real-source preflight

The Python preparer verifies frozen PR #235 file hashes, the catalog relation hashes, all 244 owner decisions and each of the 1,407 genuine M7.0 ZIP class scopes. The TypeScript runner then uses that snapshot with the structural planner and fake transaction store. `SAFE_CANDIDATE` is never used as CREATE approval.

| Proposed identity | Registrations | Structural preflight |
| --- | ---: | --- |
| Honda Jazz | 13,790 | Valid basic identity proposal; admin authorization required |
| Ford Ranger Raptor Double Cab | 12,839 | REVIEW HOLD: current `ford.ranger_double_cab` owns alias `ranger raptor` |
| JAECOO J6 | 8,659 | Valid basic identity proposal; admin authorization required |
| Toyota Vios | 6,647 | Valid basic identity proposal; admin authorization required |
| GWM Ora 5 | 4,809 | Valid basic identity proposal; admin authorization required |
| Nissan March | 4,000 | Valid basic identity proposal; admin authorization required |
| Nissan Note | 3,667 | Valid basic identity proposal; admin authorization required |
| ZEEKR 7X | 2,892 | Valid basic identity proposal; admin authorization required |
| Toyota Sienta | 2,645 | Valid basic identity proposal; admin authorization required |

The nine retain their **59,948** registrations. Eight valid proposals cover **47,109**; Ford's **12,839** remain held, and its frozen owner target is unchanged. The writer does not silently merge it into Ranger or create a competing alias identity. A reviewed alias-detach/equivalence repair plan and a fresh catalog row revision are required; the dated snapshot does not carry update revisions.

The combined nine-create batch is rejected atomically with zero fake-store changes. The eight valid create proposals succeed only under a fake admin in a separate simulation. Linking the simulated identities still fails R6 authorization with zero link changes. Canonical Segment/Body Type/generation/lifecycle stay UNKNOWN throughout this preflight.

Adding the eight valid candidates to the existing-identity candidate baseline simulates **4,075,005 / 4,123,704 = 98.819047%**, below 99.1%. This corrects the earlier nine-candidate readiness assumption; the held target cannot be counted. Production-approved/servable additions are **zero**. The unchanged full reconciliation is **4,141,987 = 4,123,704 effective + 18,283 excluded**. No registration fact, owner decision, or PR #235 source artifact is modified.

Machine evidence: `structural-writer/nine_identity_inputs.json` and `nine_identity_preflight_report.json`. The latter carries per-identity/class evidence, holds, frozen hashes, exact totals, fake transaction outcomes and production blockers.

## Reproduction and acceptance

```bash
PYTHONPATH=automotive/vehicle_master:automotive/vehicle_master/tools \
  python automotive/vehicle_master/tools/structural_identity_preflight.py
node --experimental-strip-types scripts/structural-identity-preflight.ts
npm run check:structural-identity-writer
python -m pytest -q automotive/vehicle_master/tests/test_structural_identity_preflight.py
```

The focused TypeScript cases cover success, duplicate/natural-name/alias/slug protection, FK, uncertain trim evidence, spoofed/unauthorized AI, stale revision, idempotency/concurrent create, atomic rollback, audit/revert, dependent/stale revert, class isolation/ALL rejection, frozen owner exclusions, R6 denial, TDR-versus-Ice authority, parent alias conflict, fresh approval/replay and decided-source suppression. The Python tests replay real M7.0 reconciliation, frozen decisions, current catalog alias evidence and the documented schema blockers. `npm run check` includes these structural tests and a no-write regeneration comparison of the real preflight report; no CI service calls are added.

Local full CI evidence is recorded in `structural-writer/validation_evidence.json`: 27 structural TypeScript tests; 1,923 Python tests passed, 379 skipped and 4,357 subtests; full npm check, Python compile, market validation and roadmap repository preflight pass. GitHub-hosted CI status and real database integration are not verified.

## Exact next dependency

[Database integration contract and activation checklist](STRUCTURAL_IDENTITY_WRITER_DB_CONTRACT.md) identifies the v57/v59 BASIC identity and provenance constraints, v66 structural observation field extension, existing audit/inbox reuse, normalized-token concurrency protection, authenticated structural RPC/adapter, and registration-class scoped schema/CAS. That design is unnumbered and unapplied. Independent QA, C02 migration reconciliation and explicit production authorization precede integration; C01/R6 remains a separate link gate. Fake-store success proves the offline behavior, not acceptance by the current database schema.


## Delivery status

The separate development branch is pushed. Draft PR creation was attempted with both GitHub GraphQL and REST endpoints; both returned HTTP 403. No new PR object/URL or GitHub-hosted CI result is claimed. The review-ready description is preserved in `structural-writer/DRAFT_PR_BODY.md`; `delivery_status.json` records the intended stacked base, source/implementation SHA and access blocker. Independent QA can review the pushed branch; API access must be restored to create the Draft PR. PR #235 remains untouched.
