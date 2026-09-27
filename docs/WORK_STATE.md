# TDR Work State — Source of Truth

This file is the persistent execution state for long-running TDR work. Agents must read this file before continuing any multi-step TDR data repair, audit, batch, or migration task.

## Non-negotiable execution rules

1. **Do not infer state from chat memory alone.** Read this file first.
2. **Do not reuse ambiguous lot numbers.** Every batch must have a namespace and range, e.g. `AUDIT-BEV-REEV-061-080` or `REPAIR-04`.
3. **Approved means frozen.** Do not re-audit, reinterpret, or rebuild approved work unless the user explicitly reopens it.
4. **Carry repair requirements 1:1.** Every item listed under `required_changes` must appear in the implementation prompt / write batch. No silent omission.
5. **No scope expansion.** Do not add cleanup, QA, refactors, lifecycle changes, or new research that were not part of the active step.
6. **No duplicate audit.** If a vehicle has already been inspected for the active repair batch, move to the next step using the recorded findings.
7. **Latest explicit user instruction wins**, but only for the field or step it changes. Do not reset unrelated approved state.
8. **Before any write**, compare the proposed command against this state file and verify that all required changes are represented.
9. **After any completed step**, update this file in the same work session so the next agent starts from the correct state.

## Batch state machine

Allowed states:

- `QUEUED` — membership fixed, no inspection yet
- `INSPECTING` — existing TDR data + current market evidence being checked
- `INSPECTED` — findings complete; do not audit again
- `PROMPT_READY` — Claude/implementation prompt prepared from recorded findings
- `APPROVED_TO_WRITE` — user approved implementation
- `WRITING` — implementation in progress
- `DONE` — completed and frozen
- `REOPENED` — user explicitly reopened a frozen batch

The normal transition is:

`QUEUED -> INSPECTING -> INSPECTED -> PROMPT_READY -> APPROVED_TO_WRITE -> WRITING -> DONE`

Do not skip backward unless the user explicitly instructs it.

## Namespace rule

Historical audit lots and repair lots are separate workflows.

Example:

- `AUDIT-BEV-REEV-061-080` = historical/read-only audit range 61–80 of the 117-model BEV+REEV universe.
- `REPAIR-04` = fourth implementation/repair batch.

These are **not the same batch**, even if both are casually called “Lot 4” in conversation.

## Active workflow: Vehicle Master trim / price / promotion repair

Repository target: `smgkikikiki-cloud/TDR`
Canonical boundary: `automotive/vehicle_master/`

### Repair process

For each repair batch:

**Step 1 — Membership**
- Output the exact 20 vehicles continuing from the previously approved repair queue.
- Freeze membership before inspection.

**Step 2 — Inspection**
For each vehicle, record:
- current TDR model / CURRENT trim state;
- exact trim identity changes required;
- list price(s);
- current promotion / campaign evidence where relevant;
- lifecycle action only when supported by the inspected evidence;
- any structural problem that prevents a simple trim replacement.

This step is analysis only. Do not write to DB/repo unless the user explicitly advances the batch.

**Step 3 — Implementation prompt**
- Generate one Claude implementation prompt from the Step 2 findings.
- It must contain every required change from Step 2.
- Do not tell Claude to research or re-audit facts already fixed in Step 2.
- Do not invent additional changes.

**Step 4 — Write**
- Only after user approval.
- Use repository-supported edit/write format.
- Preserve valid existing specs/evidence when identity changes; do not blank a vehicle simply because a trim is renamed/reconciled.

## Historical audit record

`AUDIT-BEV-REEV-061-080` is complete and read-only. It covered:
Lexus ES; Lexus RZ; Lexus UX 300e; Lotus Eletre; Lotus Emeya; Maserati GranTurismo Folgore; Maserati Grecale Folgore; Mazda6e; Mercedes-Benz CLA EV; Mercedes-Benz EQB; Mercedes-Benz EQE; Mercedes G-Class EV; Mercedes EQS; MG Cyberster; MG EP; MG ES; MG IM5; MG IM6; MG Maxus 7; MG Maxus 9.

Do not use this historical audit range as `REPAIR-04` membership unless the repair queue explicitly says so.

## Current repair status

- `REPAIR-03`: `DONE / APPROVED` — frozen. Do not re-audit or rebuild unless user reopens it.
- `REPAIR-04`: active. Required user workflow is **Step 1 exact 20 vehicles -> Step 2 inspect/list all fixes + prices + promotions -> Step 3 one Claude prompt**. No redundant audit between Step 2 and Step 3.

### REPAIR-04 membership

Status: `UNRESOLVED_STATE_COLLISION`

Reason: prior conversation artifacts contain two incompatible things labeled “Lot 4”. Until the exact approved repair queue is recovered, agents must **not invent membership, borrow the historical audit 61–80 list, or silently continue from a guessed alphabetic position**.

Recovery rule: locate the last user-approved repair queue / preceding `REPAIR-03` membership, then derive the next 20 exactly once and replace this section with the frozen list.

## Per-batch recording template

```yaml
batch_id: REPAIR-XX
state: QUEUED
membership:
  - 01: Brand Model
required_changes:
  Brand Model:
    tdr_current: ""
    trim_action: ""
    list_price: ""
    promotion: ""
    lifecycle_action: ""
    preserve: ""
    source_notes: ""
approved_by_user: false
implementation_prompt_commit: null
write_commit: null
```

## Agent handoff format

Before continuing a batch, report only:

- `ACTIVE:` batch id + state
- `DONE:` frozen prior step
- `NEXT:` exactly one next action

Then execute that next action. Do not restart the workflow from the beginning.
