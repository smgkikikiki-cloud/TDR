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
- `REPAIR-04`: `DONE / APPROVED` — frozen. Do not re-audit or rebuild unless user reopens it.

### REPAIR-04 membership

Status: `RESOLVED` — the collision noted below was against a batch built in a parallel chat session before this file existed; the user confirmed in-session that the 20-vehicle list already implemented is the correct, frozen `REPAIR-04` membership, and directed the fixes to remaining open items (BYD Seal, OMODA C5 EV, DEEPAL Hunter K50, DEEPAL L07, Farizon SV, FOMM One, FOTON Truck) directly.

membership: AION ES; Audi e-tron; BMW i3; BYD T3; BYD Seagull→ATTO 1; BYD Seal; Changan Lumin; NEVO Q05; OMODA C5 EV; DEEPAL Hunter K50; DEEPAL L07; DEEPAL S05; DENZA D9; Farizon SV; FOMM One; FOTON Truck; GEELY EX2; GWM ORA 03; GWM ORA Good Cat; Honda e:N1.

still-pending sub-items (not full batch reopen — see write_commit for what shipped): BYD Seal (no lifecycle evidence found, left unchanged); DEEPAL L07 (Standard 540/Plus 620 naming can't be safely mapped to L07/L07 S without spec confirmation — user says they'll choose).

batch_id: `ev-retail-repair-lot-04-2026-09-27`
write_commit: `48f9326d8197f9d768185a7f9a56c879b08cd99d`
release_id: `vehicle-2026-fbdad1638efeb292`
approved_by_user: true

### REPAIR-05 membership

State: `QUEUED` — Step 1 membership derived from the approved repair queue after `REPAIR-04`. Inspection, implementation prompt, and writes have not started.

The historical BEV+REEV audit numbers below are provenance for queue ordering, not repair-lot numbers. Models already handled in `REPAIR-02b` or `REPAIR-03` are skipped; pending sub-items of the frozen `REPAIR-04` remain with that batch rather than entering this one.

| Repair-05 | Historical audit # | Vehicle |
|---:|---:|---|
| 01 | 47 | Honda e:N2 |
| 02 | 49 | Hyundai IONIQ 6 |
| 03 | 50 | JAC Truck / N55 EV |
| 04 | 51 | JAECOO 5 EV |
| 05 | 52 | JAECOO 6 EV |
| 06 | 56 | Kia EV6 |
| 07 | 58 | Kia PV5 |
| 08 | 59 | Leapmotor B10 |
| 09 | 60 | Leapmotor C10 |
| 10 | 61 | Lexus ES |
| 11 | 63 | Lexus UX 300e |
| 12 | 64 | Lotus Eletre |
| 13 | 65 | Lotus Emeya |
| 14 | 66 | Maserati GranTurismo Folgore |
| 15 | 67 | Maserati Grecale Folgore |
| 16 | 68 | Mazda6e |
| 17 | 69 | Mercedes-Benz CLA EV |
| 18 | 70 | Mercedes-Benz EQB |
| 19 | 71 | Mercedes-Benz EQE |
| 20 | 72 | Mercedes G-Class EV |

Next: Step 2 inspection of precisely these 20 vehicles, including existing TDR trims, Thai-market lineup, list prices, promotions, and required changes. No batch payload or data write is approved at this stage.

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
