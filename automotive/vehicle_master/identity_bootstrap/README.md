# TDR Identity Bootstrap

A permanent, provider-agnostic subsystem that decides when an **external vehicle identity that Identity Resolution could not map to any TDR vehicle** may become a
**minimal canonical identity**, plans that creation, and hands the new identity to a separate enrichment process.

> **Status: Contract v1 is a DRAFT for owner review. Milestone 1 (contract, corpus, tests) and milestone 2 (offline engine, Ice adapter, read-only shadow run on the pinned M7.0 package) are done.**
> There is no persistence, no migration, no workflow, no database access and no enrichment bot. Nothing in production imports the package (a test enforces it). No vehicle was created,
> R6 was not re-run, R7 was not started, no live serving or catalog behaviour changed, and PR #200 was read, not modified. **Start with [`shadow/FINDINGS.md`](shadow/FINDINGS.md) for the real-data results.**

## Reading order

1. This file — architecture, what was verified, **§6 decisions for the owner**.
2. [`contract/v1/SPEC.md`](contract/v1/SPEC.md) — the normative contract (§0–18 + generated appendices).
3. [`INTEGRATION.md`](INTEGRATION.md) — the live-schema analysis, the smallest schema change, conflicts, the proposed amendments to Identity Resolution, the write path.
4. [`contract/v1/policy.yaml`](contract/v1/policy.yaml), [`reason_codes.yaml`](contract/v1/reason_codes.yaml), [`taxonomy.yaml`](contract/v1/taxonomy.yaml), [`lifecycle.yaml`](contract/v1/lifecycle.yaml).
5. [`contract/v1/cases.jsonl`](contract/v1/cases.jsonl) — the golden corpus (127 cases) and the schemas `input` / `decision` / `event` / `case` `.schema.json`.
6. Milestone 2: [`engine/`](engine) (pure, offline; `decide` returns decisions and write *plans*, never writes), [`providers/ice.py`](providers/ice.py) (the only place Ice meaning lives),
   [`shadow/`](shadow) (read-only run on the pinned M7.0 package; `python -m identity_bootstrap.shadow --out DIR`), [`shadow/FINDINGS.md`](shadow/FINDINGS.md) and
   [`shadow/results/2569-09_v3_M7.0/`](shadow/results/2569-09_v3_M7.0) (`REPORT.md`, `decisions.csv`, `summary.json`, `plans_sample.json`).

## 1. The idea in one picture

```
External provider ─► Identity Resolution ──── existing target? ── yes ─► mapping
                                     │ no (NO_CANDIDATE + relations)
                                     ▼
                           Identity Bootstrap ── gates, batch arbitration, lineage, id allocation
                       ┌─────────────┼───────────────┐
                    HOLD       IDENTITY_REVIEW   CREATE_IDENTITY
              (wait / no-op)  (a human decides)        │ write plan (PROPOSE until the owner amends V3 §4)
                                                       ▼
                                  DISCOVERED shell + aliases + provenance + VEHICLE_IDENTITY_CREATED (one transaction)
                                                       ▼
                                          enrichment subsystem (separate; not built)
```

**The invariant:** identity existence and enrichment are different problems. A shell holds a canonical id, brand, name, source lineage and `DISCOVERED`/`PENDING`.
Everything else stays `NULL` and a test fails if a write plan carries any attribute.

## 2. How the brief's requirements map to the contract

| Requirement | Where |
|---|---|
| Lifecycle `DISCOVERED → ENRICHING → VERIFIED → PUBLISHED` separating existence from completeness/publication | SPEC §5, `lifecycle.yaml` (adds `WITHDRAWN`; two axes; closed list of legal pairs; visibility per surface) |
| Not inside the matcher; machine outcomes | `CREATE_IDENTITY` / `IDENTITY_REVIEW` / `HOLD`; activation only from `NO_CANDIDATE` (SPEC §6 G0) |
| Hard safety: provisional, raw, unknown, trim, code, derivative, body, generation, finer, alias, rename, split/merge, already discovered, duplicate, structurally ambiguous | gates G0–G7 (SPEC §6); 36 reason codes; 78 taxonomy entries |
| Batch-level reasoning | SPEC §8 (subject↔identities, subject↔subject, coalescing, collision between creators) |
| Volume is not existence authority | invariant I3; policy has no volume key outside `priority.*`; every corpus case is re-run with units ∈ {none, 0, 3, 499, 500, 10⁷} and must not change |
| Evidence tiers; output says what justified creation | SPEC §6.3, `evidence_basis` (tier, kinds, refs, cleared flags) |
| Provenance | SPEC §12.4, `INSERT_PROVENANCE` (append-only, survives enrichment) |
| Deterministic, collision-safe canonical id | SPEC §10: `{brand_id}.{the one TDR slug of the canonical name}`; reservation includes deleted/WITHDRAWN rows; no auto-suffix; no provider id, version, order or clock |
| Hand-off event | SPEC §14, `event.schema.json` (outbox, at-least-once, idempotent on `event_id`) |
| Interface with Identity Resolution | SPEC §15, INTEGRATION §3 |
| Persistence boundary | INTEGRATION §1–2, §5 |
| Idempotency and concurrency | SPEC §11; an in-memory model of the writer's constraints is exercised by the `apply` corpus cases |
| Reason codes | `reason_codes.yaml` (the 16 required names are kept verbatim; 20 are added) |
| Golden regression corpus | `cases.jsonl` — every item the brief listed has a named case (`test_ib_corpus.py::REQUIRED_SCENARIOS`) |

## 3. Decisions worth knowing (and why)

- **Two clearing authorities.** *Lexical* suspicions (a token that looks like a trim, code, body, generation or powertrain word) can be cleared by tier-2 evidence that attests a model
  nameplate. *Structural* questions about TDR's own catalog (is `Hilux Revo` a distinct model from our `Hilux Travo`? is `City Hatchback` a variant of `City`?) can only be cleared by a recorded
  admin decision bound to the review fingerprint — no external document can say how TDR chose to model its own catalog. Duplicates, provisional/raw identities and collisions can be cleared by nobody.
- **A rejected question stays rejected** until the evidence changes (the review fingerprint has no volume, version or time in it).
- **Ids are never auto-suffixed.** A suffix would hide exactly the slug folding (`Great Wall` / `Great Wall Motors` → `great_wall`) that produced the collision.
- **HOLD ≠ REVIEW.** A hold asks nobody to decide (wait for the provider, or it is already handled); a review is a question. High volume raises an *alert band*, never an outcome.
- **`apply_mode` is `PROPOSE`.** VEHICLE_DB_V3 §4 lets AI only *propose* model creation, and no governed write path exists yet. The plan is identical in both modes.
- **Bootstrap never binds a provider id to an existing identity** and never creates a brand; it only suggests.

## 4. Verification — and what it does not prove

Run from `automotive/vehicle_master` (the existing `vehicle-master-engine` CI job already runs this; it needs PyYAML and pytest only):

```bash
python -m pytest -q tests/identity_bootstrap             # 2,307 passed, 31 skipped (provider-id renaming is skipped on cases whose lineage/bindings/directives name provider ids by design; one skip until results are committed)
python -m identity_bootstrap.shadow --out /tmp/shadow     # the read-only evaluation (about 10 s)
python -m identity_bootstrap.contract.render --check      # SPEC appendices are current
```

What the tests establish: schemas are strict and consistent; policy/registry/taxonomy/lifecycle are internally consistent and SPEC cannot drift from them; **every** corpus case is reproduced by the
reference oracle; the properties of SPEC §16 hold on **every** decide case (volume independence, order and relation-orientation independence, source-version independence, determinism, shell-only plans,
one create per id, apply → re-decide converges, `finalize` fills only deferred fields); a **policy-mutation sweep** (58 single-key flips and every single lexicon word) fails the corpus, which found one dead
policy key and 13 other blind spots during development, all fixed; every policy key is read by the oracle or listed as declarative; scope guards (the engine and adapter are pure and offline, nothing imports a database, network or Identity Resolution, no migration, no writer).

What they do **not** establish: the oracle (`tests/identity_bootstrap/ib_reference.py`) and the corpus have the same author, so agreement shows consistency, **not** that the rules are right. The word lists and patterns
are `proposal`-grade and uncalibrated: they trade review load for safety (a legitimate model whose name contains `EV`, `Pro`, `Plus` or `Sport` goes to review rather than being created; `D-Max` splits on the hyphen, so
`max` was removed from the trim list after the sweep exposed the false flag). They have not been run against the real M7.0 `model_group` names, and the relations Bootstrap consumes are supplied as data, so the
quality of Identity Resolution's lexical layer is out of this milestone's evidence. No behaviour was measured on production data.

## 5. Assumptions and unverified items

1. A shell's public slug is `{brand_id}-{local}` with `_`→`-` (current slugs are a release-time crosswalk output; INTEGRATION C7).
2. New ids drop a leading whole-token brand name (`jaecoo.j5`), whereas some legacy ids keep it (`jaecoo.jaecoo_5_ev`); keys are compared brand-insensitively so the two still collide.
3. `dlt` is listed as a second creating provider only to exercise cross-provider rules; no adapter exists, and `ice` is the only provider with real input.
4. Ice's behaviour when `id_changes.csv` renames/merges an id that is still live in `dims` is undefined (inherited from PR #200 open question 10); Bootstrap sends such a subject to review.
5. The policy/word lists for Thai generation words (`โฉมใหม่`, `ไมเนอร์เชนจ์`, `เจนใหม่`) are untested on real Thai model names.
6. IR's relation vocabulary and tokenisation are pinned from the PR #200 **draft**; if #200 changes, SPEC §4.2 is re-pinned.

## 6. Decisions for the owner

1. **Permission model.** Amend VEHICLE_DB_V3 §4 so a deterministic non-AI actor `BOOTSTRAP` may create hidden `DISCOVERED` shells (then `writes.apply_mode: DIRECT` becomes possible), or keep `PROPOSE` so every creation is an admin card. *Recommend: `PROPOSE` first; revisit after a month of cards shows the review rate.*
2. **Schema option.** A (in-place lifecycle columns + state-aware rules + published-only views), B (separate identity registry) or neither — INTEGRATION §2. *Recommend A, gated on the leak audit and a parity test.*
3. **Trim/powertrain tokens.** Words such as `EV`, `Pro`, `Plus`, `Sport` send otherwise-clean names to review. Accept (safe, noisy) or scope them (e.g. only when a same-brand model of the stem exists)? *Recommend accept for v1 and calibrate on the R6 review sheet.*
4. **Evidence tier for creation.** v1 creates on tier 0 (a settled, clean provider identity). Require tier ≥ 1 (a second source) or a minimum number of consecutive packages for brand-new nameplates? *Recommend tier 0 for now; the cost of a wrong shell is a hidden row an admin can withdraw.*
5. **Slug and canonical-name rules** (assumptions 1–2).
6. **Retired/`WITHDRAWN` ids** are reserved for ever; a re-appearance is a review, never a silent re-creation.
7. **Interface amendments to PR #200** (INTEGRATION §3): target `identity_state`; excluded-candidate relations in the IR record; `DISCOVERY_CATALOG_GAP` stays routing-only; an `ORIGIN` match method. *Recommend: raise them on #200; none blocks this contract.*
8. **Shared primitives.** `contract/schema_subset.py` is a copy of PR #200's generic validator (that PR is not on main). After #200 merges, hoist one copy.
9. **State docs.** `WORK_STATE.md` still says R6 has not started while the owner reports it ran; not reconciled here (same note as #200).

## 7. Milestone 2 (done) and what comes next (needs its own go)

**M2 delivered:** `engine/` implementing the SPEC (engine and the independent test oracle are compared exactly on every corpus snapshot, on shuffled/volume-varied variants, under all 58 policy mutations and on all 1,200 real subjects);
`providers/ice.py`; a read-only shadow run. **Headline (mode A, TDR file snapshot):** 78 CREATE / 94 REVIEW / 1,028 HOLD across 1,200 groups — see `shadow/FINDINGS.md`: 20 of the 78 CREATEs look false by analyst judgement,
69 of 78 are dormant legacy models, and the trim/powertrain/generation word lists decide **no** CREATE on this data while the real failure modes (chassis codes, glued suffixes, trim codes, synonyms) need new rules.
**Next (separately gated):** apply the owner-approved subset of FINDINGS recommendations as a contract v1.1 (policy-only rules first; R1 needs one engine rule); re-run against the **live** Vehicle Master snapshot and the R6 review sheet;
then M3 persistence (INTEGRATION §2, only after owner decisions 1–2), M4 writer behind the Phase-1 write layer, M5 enrichment hand-off consumer. Nothing in this PR may be wired to production.

## 8. Working with the contract

**Adding an edge case** (SPEC §16): add or extend a taxonomy entry → add a failing corpus line with the smallest input → change `policy.yaml` (or, later, the engine) until it passes → bump `policy.version`
if behaviour moved → `python -m identity_bootstrap.contract.render --write`. Never a Python special case.

## 9. Not done, deliberately

No writer, persistence, migration, workflow or database access (the engine only returns plans; the shadow run only reads the pinned package and the repository's file catalog and writes report files to a directory you name); no change to `vehreg/`, `tools/`, `supabase/`, `.github/`, any `ice_*` table, mapping, `PRODUCTION_*` flag or roadmap gate; no vehicle created or
published; no catalog or serving change; no enrichment bot; no change to PR #200; R6 not re-run; R7 not started.
