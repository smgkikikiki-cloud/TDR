# Shadow run findings — Ice `2569-09` v3 M7.0 (read-only; recommendations only)

Numbers come from `results/2569-09_v3_M7.0/` (`REPORT.md` has every table; `summary.json` and `decisions.csv` have the data; a test fails if they go stale).
**Nothing was written, no identity was created, no contract or policy file was changed by this run.** Registration volume is informational throughout.

## Setup and its limits

- Input: the pinned package (sha256 `c558d2d4…94677d`, md5 of each used panel verified), **all 1,200 model groups**: 495 settled, 114 `__provisional`, 591 `BRAND|MODEL`. 81 `id_changes` events (31 MERGE / 31 SPLIT / 19 RENAME) became lineage input.
- TDR side: **the file snapshot `vehreg/data/2026/models/*.json` (62 brands, 323 models), not the live database.** It is the lineup that seeded Vehicle Master; models an admin added later are invisible, so CREATE counts are an **upper bound**.
- Identity Resolution does not exist (PR #200 has no engine). `shadow/stand_in.py` supplies brand resolution, name relations and the resolver outcome with the IR draft's §5.3 semantics, simplified (no series evidence). Two modes: **A** lets a lexical duplicate of a TDR model stop at the resolver; **B** offers every group to Bootstrap (worst case). **The CREATE set is identical in A and B** (78), i.e. Bootstrap's own defences catch what the resolver would have mapped.
- The analyst verdicts on CREATEs are my judgement (`shadow/analyst_notes.yaml`), not ground truth.

## Headline (mode A / mode B)

| | Groups | Units, all time | Units, last 12 m |
|---|---|---|---|
| CREATE_IDENTITY | 78 / 78 | 47,391 (1.14%) | 10,624 (1.54%) |
| IDENTITY_REVIEW | 94 / 385 | 76,714 (1.85%) / 4,075,954 (98.41%) | 23,328 (3.38%) / 675,682 |
| HOLD | 1,028 / 737 | 4,017,882 (97.0%) / 18,642 (0.45%) | 655,477 (95.08%) / 3,123 |

Most of the volume sits in HOLD because the resolver would map it to an existing TDR model (`NOT_ACTIVATED`, 301 groups, 96.6% of units). The 591 + 114 unsettled ids total 15,255 registrations (0.37% of units). **229 of the 591 raw ids have a name that passes every shape check** (e.g. `MG|MG6`, `CHEVROLET|CRUZE`, `VOLKSWAGEN|TRANSPORTER`): they are held correctly (Ice has not settled them) and become CREATE candidates only after Ice does.

## Top CREATE candidates (mode A)

By recent activity: Jaecoo J6 (8,659 / 6,848 last 12 m, first seen 2024-12) → `jaecoo.j6`; Zeekr 7X (2,892 / 2,867, first seen 2025-09) → `zeekr.7x`; Chery Q (332, since 2026-08) → `chery.q`; Foton eView (144, since 2026-08) → `foton.eview`. By all-time units the list is led by Honda Jazz (13,790), Jaecoo J6 (8,659), Toyota Vios (6,647), Nissan March (4,000) and Note (3,667), Toyota Sienta (2,645) — apart from J6, **discontinued models**: **69 of 78 CREATEs have ≤ 10 registrations in the last 12 months and only 21 first appeared in the last 24 months.** "New to the TDR catalog" is mostly "legacy, not in the current-lineup catalog", not "newly launched". Whether TDR wants those as identities is a catalog-scope decision the contract does not make.

## Suspected false CREATEs (20 of 78 by analyst judgement; 15,638 units)

| Kind | Groups | Caught by a proposed rule? |
|---|---|---|
| Chassis/registration codes | Hino ×6 (`FG8JJ1A-JJT`…), Toyota `KUN51R-NKPSYT` | **R1** (hyphenated code segment) catches all 7; 0 false positives on the 495 settled names. Foton `BJ1041`, Sokon `CRC50`: not caught |
| Variant of a modelled/batch model | JAC T8EV (glued suffix), BMW M2/M3/M4/M5 | **R2** (a digit followed by `ev`/`hev`/`phev` at the end of a token) catches T8EV. BMW M cars are an owner modelling decision |
| Same car, two names | Honda Jazz + Honda Fit, Honda Stepwagon vs TDR `Step WGN` | no — needs a model-synonym table |
| Truncated nameplate / brand | Jeep "Grand", Toyota "TR" (unverified), Genesis G80 under Hyundai | no |

## Top REVIEW / HOLD causes

Mode A HOLD: `PROVIDER_RAW_NAME` 611 (582 `BRAND|MODEL` ids plus **29 settled ids that are registration codes**, e.g. `foton-foton-bj1031evja3`; 9 more `BRAND|MODEL` ids are `NOT_ACTIVATED` because the stand-in matched them to a TDR model), `NOT_ACTIVATED` 301, `PROVIDER_IDENTITY_PROVISIONAL` 114, `LINEAGE_UNRESOLVED` 2.
Mode A REVIEW: `BRAND_NOT_IN_TDR` 37 (1,142 units — TDR has 62 brands, Ice 170), `STRUCTURAL_CONFLICT` 25, `PROVIDER_COARSER_THAN_TDR` 10 (Land Rover Range, Chevrolet Colorado, BMW 2 Series…), `EXISTING_IDENTITY_SUSPECTED` 9, `PROVIDER_FINER_THAN_TDR` 5, `POSSIBLE_MODEL_CODE` 5, `PROVIDER_LINEAGE_AMBIGUOUS` 2, `POSSIBLE_BODY_VARIANT` 1. Mode B adds `DUPLICATE_CANONICAL_SUSPECTED` 218 (its primary reason; 304 groups carry the code).

## Suspected false REVIEW / HOLD

1. **Relation-layer noise (the stand-in follows the IR draft):** of 1,154 SIBLING pairs, **731 share only a non-distinctive token** (`V`, `CX`, `30`, `GR`, `RS`, `AMG`: HR-V/WR-V, Audi RS 3/RS 6/RS Q3, GR Yaris/GR Corolla, AMG C/AMG SL); of 85 FUZZY pairs, **76 differ in a token containing a digit** (XC60/XC90, Mazda2/3, Aston DB11/DB12, VW T-Roc/T-Cross via `t`). They create false `STRUCTURAL_CONFLICT`s (≈ 12 of the 29) and hide four real models behind false `NOT_ACTIVATED` duplicates (Mazda 6e, Volvo ES90, Peugeot 5008, BMW 630i).
2. **Word rules:** Honda S660 (a real model, held as `POSSIBLE_MODEL_CODE`). Latent: legitimate names containing EV/Plus/Sport/GT/2008 are hit (MG4 EV, Wuling Air EV, Mini Aceman EV, Aion Y Plus, Pajero Sport, Mercedes-Benz GT-Class, Peugeot 2008) — today they are caught by other reasons, so only a live catalog would show their cost.
3. **Sub-brand aliases:** with catalog aliases used as brand spellings, "Ora 5" became canonical name `5` (`gwm.5`) and "Ora 07" `07`. Fixed in the stand-in; it is a hazard for any adapter.
4. Fuzzy chassis codes labelled duplicates (HINO XZU600R-WKMLST3 vs -WKTLST3, Toyota KDH222R/KDH223R): harmless (held) but wrong.

## Structural conflicts

29 groups in mode A, 110 in B — full tables with batch groups in `REPORT.md` §6. Families: Hino `XZU600R-*` (4), Foton Tunland/eTunland (+3 raw ids), Mini Cooper EV ↔ JCW Convertible ↔ JCW RHD (the known mutual split → `LINEAGE_UNRESOLVED`, HOLD), Mercedes AMG C/SL (+ raw `A 180`/`C 180`), Audi RS 3/RS 6/RS Q3, Toyota GR Yaris/GR Corolla, Toyota KDH222R/223R, Lexus RZ350E/450E, Aston DB11/DB12, Volvo 264GL/264GLE, Nissan Urvan/Urvan E26, VW T-Roc/T-Cross, GWM Ora 5/Ora 07. Lineage reaches only 8 subjects (`id_changes` mostly names retired or already-handled ids); no RENAME/MERGE continuity case arose because no identity is bound yet.

## Effect of the word rules

| Class | Settled ids hit | CREATEs it prevents (A / B) |
|---|---|---|
| model_code (pattern) | 21 | **5 / 4** (Honda S660, Lexus RZ500E/ES350E, Hino XZU720R-WKFTST3, Toyota GUN122R-BTFLXT) — of these only S660 is a real model name |
| body | 5 | 1 (Farizon MPV SV6, via `mpv`) |
| trim | 15 | **0** |
| powertrain | 9 (`ev` 8) | **0** |
| generation | 2 | **0** |

Removing the whole trim, powertrain and generation lists changes **no** CREATE on this data: of the 15 settled trim hits 9 are `NOT_ACTIVATED` and 5 sit in a structural conflict; of the 9 powertrain hits 4 are `NOT_ACTIVATED` and the rest are held for other reasons — none is decided by the word alone (the same holds for generation). The other 132 powertrain, 62 trim and 87 body hits are unsettled ids that were held anyway. They are cheap insurance, not the dominant filter — and the dominant *failure* (chassis codes, glued suffixes, trim codes, synonyms, dormant models) is not something they catch.

## Recommendations (none applied; each needs the owner)

Contract/policy (this subsystem):
1. **R1 — hyphenated code segments** in G1 raw-name detection (needs one engine rule: the hyphen splits the code into short tokens). Catches 7/7 chassis-code CREATEs, no false positives on settled names.
2. **R2 — powertrain suffix glued to a digit token**: policy-only (a `shape.powertrain.token_patterns` entry matching a digit followed by `ev`/`hev`/`phev` at the end of a token).
3. **R4 — displacement trim codes** (`^[0-9]{3}[a-z]{1,3}$`) into `shape.model_code.token_patterns`: policy-only. It flags BMW 630i/530e…, Volvo 264GL/GLE; one false positive (McLaren 750S), which tier-2 evidence or an admin decision clears. **Required before any relation refinement** — otherwise 630i/264GL become CREATEs.
4. **Year pattern** `^(19|20)[0-9]{2}$` flags Peugeot 2008; restrict to a plausible model-year range (policy-only).
5. **Adapter guard:** brand spellings must be spellings of the brand only (never sub-brands: Ora/Haval/Tank/Omoda/Jetour); a canonical name of a single character or a bare sub-brand remainder (`5`, `07`, `Q`) deserves a soft review code (owner decision: new code `NAME_TOO_SHORT`?).
6. **Brand families in G2:** the identity-key duplicate check is `brand_id`-scoped; Deepal↔Changan duplicates only stop because the relation layer pools both brands. Add a `brand_family` input so Bootstrap defends itself.
7. **Activity as routing, not authority:** add an informational `activity_band` (last-12-month registrations / first-seen age) beside `priority_band`, and let the owner decide how dormant "legacy" identities (69 of 78 CREATEs) are routed. Existence is still never volume.

For Identity Resolution (PR #200 — raise as amendments, do not apply here):
8. **FUZZY must not apply to tokens containing a digit**; **SIBLING needs a distinctive shared token** (not a digit, ≤ 2 letters, or a trim/body/powertrain/generation word). What-if on this data: STRUCTURAL_CONFLICT groups 29 → 12 (A) and 110 → 54 (B); CREATEs +10 (Mazda MX-30/6e, VW T-Roc/T-Cross, Peugeot 5008, Volvo ES90, Nissan BE-1 look real; **BMW 630i, Volvo 264GL, 264GLE are trim-code false CREATEs that R4 flags**).
9. A **model-synonym table** (Jazz = Fit, Stepwagon = Step WGN) belongs in IR's `aliases.model`; Bootstrap cannot see synonyms.
10. Ask Ice to settle the 229 shape-clean raw ids and the 29 settled ids that are registration codes (`foton-foton-bj1031evja3`, …) — those are provider-side fixes.

Before any real run: repeat on the **live** Vehicle Master snapshot (the file snapshot omits later admin additions), then calibrate with the R6 review sheet.
