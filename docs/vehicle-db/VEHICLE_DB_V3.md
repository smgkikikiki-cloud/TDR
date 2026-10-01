# TDR Vehicle Identity & Market Engine — Design v3.1 (for Claude Code)

**Goal: overhaul the engines behind vehicle identity and market analysis while preserving the UI.** Pages keep their structure and components; engines are replaced behind a fixed serving contract (§15).
Supersedes `PRICE_FEED.md` and incorporates the "Living Vehicle Database" thesis and Ice's Full Package as the market data base. **Every rule here is decided by the owner. Do not change any rule on your own.** If something is not covered, apply the default rules in §6 and report it in the PR.
Baseline: live DB state on 1 Oct 2026 (Supabase project `ltvwzkffmpudpjfjomrg`).

## 1. Core decisions
1. **The DB is the master from Phase 0.** Git/releases stop being a write path and become backup/export only.
2. **Authority order:** `ADMIN` > `OFFICIAL` (brand website, price-list/spec-sheet PDF, ECO Sticker) > `AI` (agents, media). A lower tier never overwrites a higher tier. Within the same tier, newer overwrites older.
3. **Admin always wins.** Admin can edit, add, or delete any field instantly, with no source and no review queue. Admin-set values are `locked` until the admin unlocks them. When another source disagrees with an admin value, the system creates no alert, no badge, and no conflict; the observation is stored silently.
4. **AI may change data on its own, but may only *propose* structural changes** (permission table in §4).
5. **Everything is reversible.** Every change is written to the change log. Delete = hide (soft delete). Revert = a new compensating entry.
6. **Act first, ask only when the system would have to guess.** Minimal notifications (§11).
7. **UNKNOWN ≠ NO.** Unknown = no row. Never create NO from absence.
8. **Never infer facts** from segment, price, or sibling trims.
9. New model year always overwrites the old one (§6.A). Prices excluding VAT are used as given, with a flag. Promo prices and freebies are part of the core system.
10. EV range: the public site shows **NEDC** as the single standard (§8).

## 2. Phase 0 — move the master into the DB
One PR per step, in order:
1. **Engine inventory.** Read `automotive/vehicle_master/` and write `docs/vehicle-db/ENGINE_INVENTORY.md`: every validation rule, every value the engine computes (e.g. `retail_price_min/max`, `comparable_specs`, `price_history`, `current_list_price`, `campaign_quote`), the ID format, and slug generation. Do not port anything before this document is complete.
2. **Master tables** (no `release_id`): brands, models, generations, variants, trims, facts, price ledger, promotions. Seed from the active release (`canonical_vehicle_state.active_release_id`). Every existing ID stays unchanged.
3. **Serving parity.** The `current_*` views (`current_market_trims`, `current_vehicle_models`, `current_vehicle_generations`, `current_vehicle_brands`, `current_spec_facts`, `current_price_ledger`) read from the master instead of the projections, **with identical columns and identical payload shape**. A view or a trigger-maintained serving table is acceptable (choose by performance). **Parity test:** the new output equals the old output for the active release, row for row, before switching.
4. **Port the engine rules** to DB constraints/triggers or TS validation. The existing Python tests are the reference: the same cases must give the same results.
5. **Close the old write path.** The `canonical_input_batches` worker stops accepting jobs. Old tables stay read-only.
6. **Backup.** Daily JSON export of the master to Storage (and/or a repo commit). May be recorded in `canonical_vehicle_releases` as a snapshot.
7. **Update repo rules.** `AGENTS.md`, `docs/CANONICAL_INPUT.md`, `docs/WORK_STATE.md` must state that the DB is the master and that edits follow this document.
- Do not touch: `registrations*`, legacy uuid `models`/`trims`, `registration_*_aliases` (except as in §10), registration v2 tables.
- Work on its own branch. Do not run in parallel with design PRs (GRAFT_PLAN forbids design PRs from touching `automotive/vehicle_master/`).

## 3. Data model
| Table | Purpose | Source |
|---|---|---|
| Master identity | brand / model / generation / variant / trim + status | Seed from projections |
| `facts` | Current value per trim × `field_key`: value, unit, `value_state`, qualifiers, `authority`, `locked`, source_url, source_ref, quote, observed_at, effective_from/to, `revision` | Shape of `current_spec_facts.payload` |
| Price ledger | Append-only: amount_thb, `price_type`, `vat_included`, effective_from/to, source, authority, retracted_at | `current_price_ledger` |
| `promotions` | §7 | Replaces `campaign_quote.campaign_options` as storage; serving shape unchanged |
| `observations` | Immutable: what a source said (raw values, `trim_id` hint, snapshot ref). Trigger rejects UPDATE/DELETE | Pattern of `registration_observations_v2` |
| Change log | **Reuse `canonical_write_revisions`**, adding: field, before_revision, after_revision, actor_kind (`ADMIN`/`OFFICIAL`/`AI`/`EXCEL`), source (nullable), batch_id, reverts_id | Existing, empty |
| Inbox | **Reuse `admin_edit_sessions`**, adding kinds from §11 | Existing |
| Source registry | URL per brand/model, fetch_mode, last_success_at, fail_count, content_hash | Existing `sources` if compatible, else new |
| `agent_jobs` | Agent queue, attempts, cost, status, cooldowns | New |
| Excel | **Reuse `retail_lineup_workbook_exports` / `retail_lineup_plans` only if the existing code passes a full export → import round-trip test.** Otherwise build new and drop the old tables | Existing, empty |

- `value_state`: `KNOWN` · `NOT_APPLICABLE` (e.g. fuel tank on a BEV) · `ABSENT` (new: confirmed not present). **Stop storing `UNKNOWN` rows** (delete the existing one). Admin "clear value" stores a tombstone (`locked=true`, `value_state=null`) so AI cannot refill it.
- Every entity has `revision int`, incremented on every change.
- Field registry: extend `lib/spec-field-registry.ts` with type, unit, tolerance, multi-value flag, `stale_after_days`, field group, and classification (`SPEC` | `STRUCTURAL`).
- New trim/model IDs keep the current format `brand.model.gen.trim.slug`, must not collide, and never change when the name changes.

## 4. Permissions (enforced in the server write layer, not the UI)
| Action | ADMIN | AI / scraper / OFFICIAL |
|---|---|---|
| Edit/add/delete a fact, price, or promotion | Instant | Instant, subject to authority order |
| Add / delete / rename / reactivate a trim, or change `UNVERIFIED`→`CURRENT` | Instant | Propose |
| Create / delete / merge a model, create a generation | Instant | Propose |
| Identity and `STRUCTURAL` fields (brand, model name, segment, body_type, model-level powertrains, generation, aliases) | Instant | Propose |
| Change `model_year` per the MY rule | Instant | Instant (§6.A) |

An AI write to a `STRUCTURAL` field is automatically converted into a proposal.

## 5. Pipeline
`source (SCRAPE | AGENT | EXCEL | ADMIN_PANEL) → observations → reconcile → apply / propose → master → change log`
- ADMIN_PANEL and EXCEL have authority `ADMIN` and apply immediately. Excel shows a preview; on apply, the diff is always recomputed against current state.
- Reconcile is a pure function: input = observations + current state; output = plan (changes + proposals). It never writes to the DB itself.

### 5.1 Trim-set reconcile (per model), mandatory order
1. Batch gate: extraction failed or 0 rows → stop the whole batch.
2. Match by `trim_id` hint (Excel).
3. Match by normalized name / alias within the same model.
4. Model gate: observations < 50% of CURRENT trims → `SOURCE_BROKEN` (change nothing in that model).
5. Topology: missing / new / lineup count / markers (new model year, "new", "ใหม่", "ไมเนอร์เชนจ์", "โฉมใหม่", "facelift").
6. Lineup change > 50% or a facelift marker → one card for the whole model (no per-trim pairing).
7. Pair missing × new (§5.3) → rename/alias proposals.
8. Remaining: new → propose add; missing → propose discontinue after 7 consecutive days missing.

### 5.2 Normalize (pure, versioned with `normalizer_version`)
lowercase → strip leading brand/model name → strip model year → synonym map (`hybrid|hev|e:hev→hev`, `awd|4wd|4x4→awd`, Thai↔English) → remove spaces/dashes (keep decimal points, e.g. `1.5`).

### 5.3 Pairing
`score = 0.40·tokens + 0.30·price + 0.30·slot`
- tokens: Jaccard similarity; numeric/powertrain tokens weighted ×2.
- price: `max(0, 1 − |Δ%| / 10)`.
- slot: use already-matched trims as anchors; same gap between the same anchors = 1, adjacent gap = 0.5, otherwise 0.
- Hard reject (only when parsed on both sides): different powertrain class (ICE/HEV/PHEV/BEV), different displacement, different drivetrain. Penalty: different seat count −0.3.
- Greedy 1:1, highest score first. Score < 0.50 → no pair; ≥ 0.50 → propose.
- For trims whose name was set by an admin, the only allowed proposal is "match (add alias)"; never propose renaming them.

### 5.4 Prices
- Apply only after seeing the same value in 2 consecutive runs (ADMIN/EXCEL apply immediately).
- |Δ| ≤ 15% → apply. > 15% → `PRICE_JUMP` card; the old value stays until approved.
- All trims of a model changing together with no topology change → normal rules, no card.

## 6. Rule book
**Default rules when no case matches:** (1) unsure = change nothing, store the observation; (2) structure = propose, data = authority order; (3) blank / missing / not mentioned ≠ delete ≠ absent; (4) delete = hide; (5) never re-propose: a rejected proposal is not proposed again unless the source data actually changes.

### A. Identity
| Case | Decision |
|---|---|
| New model year (no facelift marker) | Same trim ID; update `model_year`; keep existing facts; update the differences; delete/`ABSENT` only when a source explicitly says removed. Old and new MY sold together → no separate trim |
| Facelift / minor change, same name | Propose a new generation; old one becomes HISTORICAL |
| New generation, same trim name | New trim ID; facts and price history do not carry over |
| Duplicate trim names in one model | Distinguish by tokens (seats/powertrain) if possible; otherwise propose |
| Website and price list use different names | Propose alias |
| Rebadged model across brands | Always separate vehicle IDs |
| AI proposes a model that may already exist (spelling/Thai name) | Check aliases + normalization first; card shows "possible duplicate of X" |
| Limited/special edition | Normal trim + `limited` flag |
| Special/two-tone paint surcharge | Not a trim; MSRP = base colour |
| Separately priced option package | Not a trim, not MSRP |
| Upcoming model launches | Propose model + link `upcoming_vehicles.launched_model_id` |
| `UNVERIFIED` trims (102 today) | Real but unconfirmed; hidden from the public site. `trim-verify` checks official sources: found → per-model card "confirm as CURRENT"; checked and not found → propose HISTORICAL. Both need admin approval |

### B. Prices
| Case | Decision |
|---|---|
| Price range / "starting from" without a trim | Skip |
| Price excludes VAT | Use as given, `vat_included=false`; site shows "ไม่รวม VAT" |
| Both list and promo price shown | MSRP = list price; promo price → promotions |
| Price 0 / blank / "contact dealer" | No change |
| Regional prices | Use national/Bangkok price |
| Two official sources disagree | Newer publication wins; unknown date → brand website; no card |
| Future effective date | Store `effective_from`; switch on that date |
| Battery lease / subscription | Skip |
| New trim pending approval | Price lives in the card, not the ledger |

### C. Facts
| Case | Decision |
|---|---|
| Different units | Convert per registry; ambiguous unit → skip |
| Rounding-level difference | Within registry tolerance → no change |
| Same-tier sources disagree | Keep current value; store observation (visible in the vehicle panel); no card |
| Value depends on option | `multi` fields store several values; others store the base trim value |
| Model-level document | Write to every trim the document names; never copy from sibling trims |
| AI fact without source_url and quote | Discard |
| Forum/social source | Discard |
| `ABSENT` | Only when the source has a row for that field and states it is not present |
| Admin lock / tombstone | AI never touches it |
| Staleness | Specs do not go stale within a generation; prices go stale after 60 days (used for queue priority only) |
| HISTORICAL trim | Admin can edit; AI does not enrich |

### D. Admin
| Case | Decision |
|---|---|
| Admin edits a field the system updates | Admin wins + lock |
| Admin unlocks | Next observation applies normally |
| Admin edits a trim with a pending proposal | Cancel proposals touching the same trim/field |
| Two admins edit simultaneously | Last save wins; both logged |
| Delete a trim/model with price or registration history | Hide; linked data stays |

### E. Inbox / proposals
| Case | Decision |
|---|---|
| Same issue found again | Update the existing card |
| Partial approval | Unticked items = rejected and remembered |
| Rejected, then source data really changes | May propose again |
| Pending > 30 days | Expire silently; if still true, may re-propose once |
| Missing trim reappears before approval | Cancel the card silently |
| HISTORICAL trim on sale again | Propose "reactivate" |
| All trims of a model gone | One card "discontinue whole model" |
| Nested proposals (new model + its trims) | Approve/reject the model = the whole set |
| While pending | Site shows current values; prices of matched trims still update |

### F. Sources
| Case | Decision |
|---|---|
| Site down / timeout / captcha | Retry next run; broken > 3 days → `SOURCE_BROKEN` card |
| Extracted < 50% | Skip that model; counts as a broken day |
| Content hash unchanged | Skip; no AI call |
| Pages for other markets | Fetch only registered URLs |

### G. Excel (authority ADMIN)
Columns: `trim_id · brand · model · trim_name · price_thb · vat_included · status · source_url · note` (+ one column per `field_key` for facts). `.xlsx`/`.csv`. Export = current data.
| Case | Decision |
|---|---|
| `trim_id` + new name | Rename |
| No `trim_id`, name matches | Update |
| No `trim_id`, no match | Create new trim (preview shows "will create") |
| Blank cell | No change |
| `#ลบ` | Clear value (tombstone) |
| `#ไม่มี` | `ABSENT` |
| `status = #เลิกขาย` | HISTORICAL |
| Trim/model not in the file | Untouched |
| Bad header / duplicate rows / unknown id / non-numeric price | Reject the whole file with row numbers |

### H. Revert
| Case | Decision |
|---|---|
| Revert an entry or a whole batch | Write compensating entries (`reverts_id`) |
| Field changed again later (revision mismatch) | Skip that entry; show "changed since" |
| Revert approval of a new trim/model | Hide it with its facts |
| Revert a revert / revert an admin edit | Allowed; restores value, authority, and lock |

## 7. Promotions
Columns: trim_id or model_id (`scope`), `type` (`PROMO_PRICE` | `DISCOUNT` | `FREEBIE` | `FINANCE`), promo_price/amount, description (condition text as written by the source), valid_from, valid_to, `valid_to_assumed`, last_seen_at, source, authority, status (`ACTIVE` | `EXPIRED`).
- Has an end date → EXPIRED automatically on that date.
- No end date (e.g. "while stocks last") → valid_to = last_seen_at + 30 days; extended while still seen; expires on its own once gone.
- "All trims" → applied to every CURRENT trim of the model.
- Never touches MSRP; never triggers `PRICE_JUMP`; never creates a card.
- Serving keeps the existing `campaign_quote` shape.

## 8. EV range and charging
- Existing field `ev.rated_range_km` with qualifiers `measurement_basis` and `range_scope` stays the raw fact, stored exactly as the source states.
- **Public display = NEDC only.** `ECO_STICKER_TH` counts as NEDC (UN R101). `standardized_wltp_km` / `standardized_epa_km` stay in the DB but are not displayed.
- Derived NEDC = raw × factor per basis, computed at read time, never stored as a fact. Display "ประมาณ (แปลงจาก X)" when converted.
- **Factors:** the system recomputes each factor automatically as the median of `NEDC-or-ECO_STICKER_TH ÷ other basis` over trims that have both (same `range_scope`), **only when the basis has ≥ 10 pairs**. Until then: CLTC = ×0.90. Bases with < 10 pairs and no fallback (EPA, WLTC) → no conversion; show the raw value with its basis label. Admin may override any factor. (1 Oct 2026: WLTP has 12 pairs, median ×1.09.)
- Charging: store raw text plus whatever parses: from_pct, to_pct, minutes, kw, ac_dc. No normalization yet.

## 9. AI agents
- **Model: `claude-haiku-4-5-20251001` for every skill. No other model.**
- **Budget source: the owner's Claude subscription monthly Agent SDK credit.** Agents run through the Claude Agent SDK authenticated with the owner's subscription login (not an API key). Use the full credit; **never incur paid usage**.
  - "Usage credits" (overage at API rates) must stay **disabled** on the account. The runner must not have `ANTHROPIC_API_KEY` set (it would bill the API instead).
  - The system tracks its own spend: tokens per call × Haiku rate, against `app_settings.agent_monthly_credit` (amount entered by admin from the claimed credit). Daily cap = remaining credit ÷ days left in the billing cycle. `app_settings.agent_cycle_start_day` = billing cycle reset day.
  - Hard stop on any quota/limit/credit error from the SDK; resume next day (or next cycle).
  - Provider is a config switch: `agent_provider = agent_sdk_subscription | api_key`. Switching to `api_key` later needs no code change (Anthropic recommends API keys for shared production automation).
- **Runner:** a separate worker process (one Docker image) that polls `agent_jobs` in Supabase. Never runs inside Vercel functions. Logged in once with the owner's subscription.
  - **Trial: the owner's own computer.** Provide a one-command start (`npm run agent-runner` and the Docker equivalent) and a short `docs/vehicle-db/RUNNER.md` (install, login, start, stop, check status) written for a beginner. While the computer is off, jobs simply wait in the queue; missed scheduled skills run once when the runner starts (no backfill of every missed slot).
  - **Production: a rented VPS**, same image, same config; the switch is moving the container, no code change. Only one runner may be active at a time (lock row in `agent_jobs`/`app_settings`; a second runner refuses to start).
  - The daily email (19:00) and inbox do not depend on the runner; they run from Vercel/Supabase cron.
  - `/admin/agents` shows runner heartbeat (last seen) and where it runs.
- Skill = module in `lib/agents/skills/<name>/` (prompt, zod output schema, allowed sources, quota share).

| Skill | Job | Schedule |
|---|---|---|
| `price-check` | MSRP from registered URLs (AI only when hash changed) | Daily; every 6 h on days 1–5 of the month |
| `promo-scan` | Promotions / freebies | Daily |
| `trim-verify` | Lineup reconcile (§5.1), incl. `UNVERIFIED` checks | After price-check; rules only, no AI except extraction |
| `spec-enrich` | Fill facts one field group at a time | Continuous loop (below) |
| `my-update` | Detect new model years | Weekly |
| `discovery` | New models from Ice provisional groups (`BRAND\|raw name`) + news/upcoming | Weekly, and after each Ice import |

**Daily order:** scheduled skills (price-check, promo-scan, trim-verify, and weekly ones on their day) run first; `spec-enrich` then uses everything left until the daily budget is exhausted.

**`spec-enrich` loop:** a worker (cron every few minutes) takes the next vehicle and enriches it immediately, one after another, until the daily budget is used up; it resumes from the same queue the next day.
- Eligible: trim CURRENT; has missing fields per registry; field not locked/tombstoned; not in cooldown.
- Priority: stale price → registration volume in the last 12 months (high first) → number of missing fields.
- Per vehicle: one document per fetch (a spec sheet fills every trim it names); save discovered URLs to the source registry; fill by field group.
- **Cooldown:** field group searched and nothing found → that vehicle × field group is skipped for 30 days (prevents spending the budget on the same unknowns daily).
- Every fact needs source_url + quote, else discarded.
- Failure → retry once, then `FAILED` (visible in the panel, no notification).
- Proposal cap: max 10 new inbox cards per day; extras wait for the next day.

## 10. Market analysis coupling
- **Market data source = Ice Full Package (§14).** The repo's own registration pipeline (`registrations`, `registration_facts_v2`, `registration_observations_v2`, views `registration_*`) stops being a display source. Keep the tables read-only; `registration_model_aliases` stays as an input to crosswalk matching.
- Market total = Ice total (e.g. 2569-08 = 62,417, all reg types). The old open blocker on the market-total definition is closed.
- Model IDs are never hard-deleted or changed. Model merge = ADMIN only; updates the crosswalk (§14.2) in the same transaction, logged.
- Vehicle-DB fields used to group market numbers (segment, body_type) are `STRUCTURAL`; AI cannot change them (a change regroups historical shares).
- `discovery` reads Ice provisional groups (`model_group_id` containing `|` or ending `__provisional`) and Ice groups without a crosswalk → first proposes a crosswalk to an existing model; if none fits, proposes a new model. Both are proposals.
- Registration volume (from Ice `reg_trend` via crosswalk) is used for agent queue priority.
- Vehicle-DB tyre/wheel and powertrain facts never feed or modify Ice numbers (CLAUDE.md rule 6).

## 11. Admin UI and notifications
- `/admin/vehicles/[id]` workbench: identity; facts by group (known / missing / locked); sources; disagreeing observations (view only, no alerts); history with revert; Enrich button; every field editable instantly (clear value, set "absent", unlock).
- `/admin/vehicles`: multi-select → run a skill; work queue from missing data; live coverage page.
- `/admin/inbox`: only 3 kinds: `STRUCTURE` (one card per model, approve all / untick items), `PRICE_JUMP`, `SOURCE_BROKEN`.
- `/admin/vehicles/import`: Excel preview → apply. `/admin/vehicles/log`: searchable change log, revert entry/batch.
- `/admin/agents`: today's budget used/remaining, vehicles enriched, queue size, FAILED jobs.
- **Notification: one email per day at 19:00 Asia/Bangkok, only when the inbox is not empty.** Content: counts per kind + link to `/admin/inbox`. No other notifications.

## 12. Phases (one PR per sub-step)
0. Move the master into the DB (§2). No other phase starts before the parity test passes.
1. Core: permission layer, change log + revert, observations, field registry, new `value_state`.
2. Workbench, inbox, coverage, log UI, daily email.
3. AI enrichment on demand (single vehicle → multi-select → queue), `spec-enrich` skill, budget + cooldown.
4. Trim-set reconcile (pure engine + tests) + Excel import/export.
5. Scheduled: `price-check`, `promo-scan`, `trim-verify`, `my-update`, `discovery`, continuous enrich loop.
6. NEDC display + factor recompute + charging parse.

Market track (can run in parallel with phases 1–6 after Phase 0; order within the track is fixed):
M1. Serving contract inventory (§15.1) — document only.
M2. Ice import per Ice's skill `tdr-package-import` (§14.1), incl. the one-time file restructure plan approved by กี้ before any file is moved.
M3. Crosswalk: auto-match + one-time review sheet + CHANGELOG handling (§14.2).
M4. Market engine on Ice data behind the serving contract; parity/acceptance tests (§15.2).
M5. Switch pages to the new engine; retire old registration views as display sources.

## 13. Required tests
- Phase 0: parity for every `current_*` view; all IDs unchanged; existing Python test cases pass against the new validation.
- Permissions: AI write to STRUCTURAL → becomes a proposal; AI cannot overwrite ADMIN; cannot refill a tombstone.
- Reconcile: +2% price (applied on 2nd run) / +20% (card); all trims up together; SV→SV+; trim inserted mid-lineup keeps later pairs correct; HEV→PHEV not paired; lineup change > 50% gives no rename proposals; 0 observations gives no discontinue proposals; new MY keeps existing facts.
- Excel: every row of the §6.G table.
- Revert: A→B→revert A = skipped; double revert = no-op; reverting an admin edit restores the lock.
- Promotions: expires on date; assumed 30 days extends while seen.
- Range: factor recomputed only at ≥ 10 pairs; CLTC fallback 0.90; EPA shown raw; ECO_STICKER_TH treated as NEDC.
- Agents: Haiku only; stops at daily cap and on SDK credit/limit errors; refuses to start if `ANTHROPIC_API_KEY` is set while `agent_provider = agent_sdk_subscription`; cooldown skips; max 10 cards/day.
- Market: model merge moves all registrations, no orphans; AI cannot change segment.
- Observations: UPDATE/DELETE rejected.
- Email: sent at 19:00 only when the inbox is non-empty.

- Market: crosswalk auto-match never auto-accepts a pair that fails the volume-series check; Ice CHANGELOG crosswalk entries create proposals; sums by TDR segment equal the Ice total minus "ไม่ระบุ"; powertrain numbers equal Ice `reg_powertrain` exactly.

## 14. Ice Full Package as the market base

### 14.1 Import
Follow Ice's skill `.claude/skills/tdr-package-import/SKILL.md` (replace it from `สำหรับ_AI/` on every package). In short: md5 + status "พร้อมส่ง" + `confirmed_by` 2 names → the `validate_package.py` **shipped inside the Full Package** passes (replaces the old `tools/validate_package.py`, which does not know `reg_powertrain`) → **replace the whole set** → post-import checks (`reg_province` = `reg_trend`; `reg_powertrain` sums = `reg_trend` ±0.5) → record `master_version` → notify Ice. Folder layout `data/packages/` and `ล่าสุด.json` exactly as in the skill. Never edit Ice numbers; report errors to Ice with sample rows.
Imported data lives in its own tables keyed by `panel_id` (CLAUDE.md rule 1: never mix panels in one request/export).

### 14.2 Crosswalk `ice_model_crosswalk`
Columns: `model_group_id`, `canonical_model_id` (nullable), `match_method` (`SERIES` | `NAME` | `ADMIN`), `score`, `status` (`AUTO` | `APPROVED` | `PROPOSED` | `REJECTED`), `master_version`, timestamps. Many TDR models may map to one Ice group (e.g. `hilux_travo_cab` + `hilux_travo_double_cab` → `toyota-hilux-travo`); one TDR model maps to at most one Ice group.
Ice does **not** ship its DLT raw-name map (confirmed by Ice). Matching signals, strongest first:
1. **Monthly series:** same brand (after brand alias); compare the last 24 monthly totals (Ice `reg_trend` vs legacy `registrations` mapped to the TDR model, summed over TDR models mapping to the same group). Correlation ≥ 0.98 and total ratio 0.9–1.1 = strong. Both sides come from the same DLT data, so the series is the fingerprint.
2. **Brand alias table** (seed: Deepal ↔ Changan, MG Maxus 7/9 ↔ MAXUS Mifa 7/9).
3. **Name similarity** (normalized, brand prefix removed) — never sufficient alone.
Acceptance: strong series AND name ≥ 0.8 → `AUTO`. Everything else with a candidate → one review sheet (`PROPOSED`), approved once by admin. No candidate → leave null; market pages show the Ice name without a link.
Ongoing, on every Ice import:
- Apply Ice's `id_changes.csv` (old_model_group_id → new_model_group_id, type): `เปลี่ยนรหัส` and `รวม` → move crosswalk rows, bookmarks and links from old to new automatically (old id retired, redirect to new); `แยก` → old id stays; propose (`STRUCTURE` card) whether the TDR model should also map to the new id. Never recompute moved units — the replace-all import already contains the new history.
- Ice groups appearing for the first time and provisional groups (`model_group_id` containing `|` or ending `__provisional`) → `discovery`.
Prototype (1 Oct 2026, names + 11-month totals only): 203/296 TDR nameplates auto-matched = 79% of units; 15% need review; 6% no candidate. Known traps: `bmw_3` vs `bmw-x3` (name-only false match), brand differences (Deepal/Changan, MG Maxus/MAXUS).

### 14.3 Which dimension comes from where
| Dimension | Source | Rule |
|---|---|---|
| Units, province, reg type, period | Ice | As delivered |
| Brand | Ice | Map to TDR brand for links only |
| Model | Ice `model_group_id` | Link to TDR model via crosswalk |
| Powertrain / fuel | **Ice only** (`reg_powertrain`, `fuel_group`) | Never regroup by vehicle-DB powertrain; name "TDR Powertrain Index". By `certainty`: `exact` → show `reg_est`; `family` (sibling models with the same engine spec; family total exact, split between siblings ≤ 2% error) → show `reg_est` + note "แบ่งระหว่างรุ่นในตระกูลโดย TDR"; `range` → show `reg_min`–`reg_max` |
| Wheel / tyre | **Ice only** | "TDR Wheel & Tyre Index"; always show coverage. Published start = `period_from` in the `tyre_province` / `rim_province` manifest — never hard-code a start period (criterion: years with coverage ≥ 95%; currently from 2564-01) |
| **Segment** | **TDR vehicle DB** via crosswalk | Sum only. Unmatched groups → "ไม่ระบุ"; show coverage line. Ice `dims` segment is not imported for display |
| **Body type** | **TDR vehicle DB** via crosswalk | Same as segment |
| Segment/body definitions | Method page | State that TDR segment definitions are TDR's own |
Ice display rules apply on every Ice-based view: no "ประมาณการ", no spec-source names on Ice panels, no claim that wheel/tyre comes from DLT, Bangkok note always, % change only when base ≥ 30, follow `access` and `free_scope` in each `panel.json`.

## 15. UI preservation — serving contract

### 15.1 Contract inventory (M1, document only)
Write `docs/vehicle-db/SERVING_CONTRACT.md`: every function/view a page calls for vehicle or market data, with its return type and the pages using it. Starting list (verify in code): `getCanonicalModels`, `getCanonicalModelBundle`, `getCanonicalRelatedModels`, `getCanonicalBrands`, `getCanonicalPrimaryMediaIndex`, `trimRow`/`modelRow`, `compare-canonical-data`, `getPublicMarket`, `periodTotal`, `compareMarketSliceRows`, `lib/registration-market.ts`, `lib/public-market.ts`, `public_model_market_teaser`, and the `current_*` views.

### 15.2 Rules
- Pages and components are not redesigned by engine PRs. Engine PRs change only code behind the contract.
- Each contract function keeps its signature and return shape. New data needs = new optional fields, never renamed or removed ones.
- Vehicle side: parity tests must be identical (Phase 0).
- Market side: values legitimately change (Ice definitions). Acceptance tests instead of parity: totals equal Ice per period; shape unchanged; every label/note on the page matches §14.3 and Ice display rules. Expected visible differences, listed in the PR: total (e.g. 61,805 → 62,417), powertrain groups (BEV / HEV / PHEV / เบนซิน / ดีเซล / LPG instead of ICE / MIXED / REEV / UNKNOWN), coverage line text, index names, Ice models without a TDR page shown unlinked.
- Design PRs (GRAFT_PLAN) consume the contract and must not call engine tables directly.
