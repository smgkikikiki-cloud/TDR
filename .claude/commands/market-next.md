# /market-next — execute only the next Ice Market Track gate

Follow this procedure exactly.

1. Read `CLAUDE.md`.
2. Read `AGENTS.md`.
3. Read `docs/WORK_STATE.md`.
4. Read `docs/market-track/ROADMAP.md`.
5. If the task touches `TDR_FULL_*.zip`, `data/packages/`, Ice panels, import, or release metadata, read `.claude/skills/tdr-package-import/SKILL.md` before opening/importing package data.
6. Read only the relevant sections of `docs/vehicle-db/VEHICLE_DB_V3.md` and `docs/vehicle-db/SERVING_CONTRACT.md` for the current gate.

Then print a short execution header:

- CURRENT GATE:
- WHY:
- ALLOWED:
- FORBIDDEN:
- EXIT TESTS:

Execute **only** the current gate from `docs/market-track/ROADMAP.md`.

Non-negotiable:
- The owner-supplied M6.0 package is trial/fixture-only until the owner explicitly declares a final package.
- Never run a production Ice import, production crosswalk match/approval, or live cutover while the corresponding roadmap safety flag is false.
- Do not infer redirects, release authority, access scope, `period_from`, or missing metadata.
- Do not edit Ice numbers to make validation pass.
- Do not start a later gate because the current implementation looks “close enough.”
- If a stop condition is hit, report it and stop.

When the current gate is complete:
- run its required tests;
- update `docs/WORK_STATE.md` in the same session;
- update the roadmap gate/flags only if its documented exit condition is met;
- stop before the next hard gate unless the owner has explicitly authorized proceeding.
