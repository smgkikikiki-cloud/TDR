# PAGES.md — page-by-page design outline (agent-facing)

Read `DESIGN.md` (rules), `DATA_MAP.md` (where every number comes from), `reference/components.html` (shared components) first. Thai strings in quotes are exact UI copy. **Never invent copy, numbers or permissions**; anything marked `[COPY]` is owner-supplied text: render the block with `data-todo="copy"` and a visible dashed placeholder, never lorem ipsum.

## 0. Rules for every page
- **Shell:** header → page → footer (+ bottom bar ≤767px). Content max 1440, gutters per DESIGN §5. Sticky header, 84px (64px phone).
- **Block states — implement all four for every data block:** *loading* (skeleton with final dimensions, no spinners) · *empty* (dashed card, "ยังไม่มี…", never a blank area) · *locked* (see §0.1) · *error* (inline card + retry; a failing block must not blank the page).
- **§0.1 Locked content:** blurred **decorative placeholder** + `tdr-tier` badge + CTA. The DOM/JSON must contain **no real values** of locked data (no blurred real numbers, no CSS-blurred real image). Only a server-generated blurred derivative may be shown for images (see Analysis Report).
- **CTA hierarchy:** ≤1 solid `--accent` button per viewport; everything else outline/ghost.
- **Numbers** mono + tabular; source line under every chart/table; % change only when base ≥30.
- **Responsive/dark:** all 4 breakpoints × 2 themes (DESIGN §6). Tap targets ≥44px. No horizontal page scroll at 1440/1366/1280/1024/834/390.
- **Ref** = the file to copy structure from. If Ref is a PNG, open only that PNG.

## 1. Vehicle Database group
### P01 `/` Home — Ref `reference/home_v7.html` (+ `screens/home_v7_*`)
Blocks in order: hero (headline computed from latest data · KPI trio · red CTA "เริ่มดูฟรี 30 วัน →" + reassurance line · secondary link "ค้นหารุ่นรถ สเปก และราคา" | right: locked province probe "เร็วๆ นี้") → 4 shortcut cards (menu order) → Intelligence band (Panels 1–5 cards, trend + powertrain donut + brand share with pp) → Info & Top 5 sample → Vehicle Database (KPIs, body-type chips w/ icons, brand chips text-only) → Compare Specs (2 example cars) → Analysis Report (latest 3 cards; empty state) → plans (Freemium/Pro/Enterprise "Contact →") → About strip → footer. Data: DATA_MAP §Home. Ice-only blocks stay `soon` until the Ice import ships.
### P02 `/models` — Ref `reference/models_v1.html`
PageHead + search · KpiStrip(5) · BodyTypeTile×7 · left FilterRail (sheet ≤1023) · results bar (count, sort: ใหม่ล่าสุด/ราคาต่ำ→สูง/ราคาสูง→ต่ำ/ชื่อ) · active chips · ModelCard grid 3→2→1 · "โหลดเพิ่ม" 12 at a time · CompareTray (sticky, max 4). Tabs above results: "ขายแล้ว" | "กำลังมา" (→ P16 content inline). Filters/URL params unchanged from current `app/models/page.tsx` (`body, powertrain, segment, position, production, brand`); add `sort`, `page`.
### P03 `/models/[slug]` Model detail — no Ref (compose)
Breadcrumb (Vehicle Database › brand › model) → Hero: image 16:9 (official media + credit; none → placeholder), eyebrow brand·body, H1, badge chips (segment, powertrains, production, seats), price range ("ราคาปัจจุบัน"), BEV: "ระยะทางที่ผู้ผลิตประกาศ" + cycle, buttons "เพิ่มเข้าเทียบ" (outline) → consumer description (only if present) → **Trims accordion** "รุ่นย่อยที่จำหน่าย": row = name · powertrain summary · range · price (+ tag "ราคาโปรโมชัน" with end date, list price stays primary); expanded = 6 summary specs grid, description, campaign rows w/ conditions+source link, link "ดูสเปกทั้งหมดของรุ่นย่อยนี้ →" · discontinued trims collapsed → **Tech specs**: dimensions grid, powertrain cards (details) → **"ยอดจดของรุ่นนี้"**: Pro sees 12-month line + share; others see locked placeholder (§0.1) → **"การผลิตในไทย"** small card only if programs exist → other models of the brand (6 ModelCards). **Remove** the dark "industry zone" band and the news block (hide when empty). Data: DATA_MAP §Model.
### P04 `/models/[slug]/[trim]` Trim spec page
Header (model › trim, price, promo tag) → key-facts strip (price · range · battery kWh · power · seats — only those known) → **spec table by group**: ขนาดและน้ำหนัก · ระบบขับเคลื่อน · แบตเตอรี่และการชาร์จ · ล้อและยาง · ความปลอดภัย · ความสะดวกและเทคโนโลยี · ภาษีและกฎระเบียบ; row = label · value(+unit) · source badge ("ECO Sticker"/"OEM") + observed date on hover/tap; **unknown fields are omitted, never "-"**; group with no rows is omitted → sibling-trims switcher (select) → "ที่มา" list → "เพิ่มเข้าเทียบ". Field labels/order from `lib/spec-field-registry.ts`.
### P05 `/brands` — brand index (no logos)
PageHead · A–Z jump bar · client filter box · table rows: brand name · จำนวนรุ่น · ช่วงราคา · → link. Sort A–Z; default group by initial letter.
### P06 `/brands/[slug]`
Header (brand text eyebrow + H1) · KPI(รุ่นที่จำหน่าย, รุ่นย่อย, ช่วงราคา) · BodyTypeTile (counts for this brand) · ModelCard grid (same component/URL params as P02, brand preset) · "กำลังมา" strip if brand has upcoming (P16 cards, max 3).
### P07 Search — overlay + `/search?q=`
Header search icon opens overlay: input, live suggestions (6 models + brands as text chips), "ดูผลทั้งหมด →". Page: H1 `ผลการค้นหา "q"` · groups รุ่น (ModelCard grid) · แบรนด์ (chips) · กำลังมา (small cards) · empty: suggestions + popular body-type tiles.
### P08 `/compare`
Selector (search → model → trim; up to 4) · sticky column header (trim name, price, remove ×) · spec groups (same groups as P04) with switch "แสดงเฉพาะที่ต่างกัน" · winners highlight via existing `compare-winners` (bold + ✓, no colour-only) · share link · anonymous quota counter "เหลือ n/10 ครั้งวันนี้" · phone: first column pinned, horizontal swipe, 2 columns visible. Keep all logic in `lib/free-compare.ts`, `lib/compare-winners.ts`.

## 2. Automotive Intelligence group
### P09 `/intelligence` Hub — Ref `ice-mockups/16_AIHub.png` + home Intelligence band
PageHead (eyebrow, H1 "Automotive Intelligence", one-line description) · latest-period KPI trio · Panel cards ×5 (P1–P4 `soon`, P5 active) with tier badges legend (Freemium ✓ / 🔒 Pro) · trend + donut + brand-share (same as home band) · trial band "ทดลองฟรี 30 วัน" (anonymous only) · source line. Anonymous = public default snapshot.
### P10 `/intelligence/share` Panel 5 "ส่วนแบ่งตลาด"
Filter bar (period: month picker + presets 3M/6M/12M/YTD; compare: เดือนก่อน | ปีก่อน(Pro) | ไม่เทียบ; **dimension tabs**: แบรนด์ · ระบบขับเคลื่อน · ตัวถัง · Segment · ประเทศที่ผลิต · กลุ่มผู้ผลิต · รุ่น(Pro); filters brand/segment/body (Pro)) → KPI×4 → ranking (bars + pp delta) + sortable table → donut (powertrain) → 12-month trend → coverage line "คิดจากรถที่ระบุรุ่นได้ x คัน (y% ของยอดเดือนนี้)" → source line. Buttons: "สร้าง Info" (Pro, later), CSV hidden until export_columns defined. Rules by tier: DATA_MAP §Panel5. Logic stays in `lib/registration-market.ts`/`lib/public-market.ts`.
### P11 `/intelligence/{province,rim,tyre,trend}` Panels 1–4 — *not built in first graft* (cards say "เร็วๆ นี้")
Ref `ice-mockups/19..22_*.png`. Shared: filter bar (from–to month, presets, compare, body chips, brand multi, model (P4), fuel (P1)) · buttons Info/CSV with lock icon when not entitled · KPI×4 · province map (click = drill; sequential `--map-*`; comparison mode uses `--diverge-*`; base <30 gray) + sortable table · tap on touch opens bottom sheet. P1 stacked fuel bars · P2 rim-bucket matrix (≤14…21+) with `tdr-flag--estimate` "ประมาณการ · ครอบคลุม X%" · P3 tyre-size matrix (phone: pick province → top-10 bars) · P4 line (68 months) YoY/MoM/YTD per model/province.
### P12 Freemium choose/view — Ref `ice-mockups/17_FreeChoose.png`, `18_FreeView.png` (*later*)
Choose: 3 cards (จังหวัด / 20 รุ่นแรก / เชื้อเพลิง) each with what-you-see; confirm dialog "เลือกแล้วล็อกตลอดช่วงทดลอง". View: days-left bar, username watermark (`tdr-watermark`), copy/right-click disabled, latest period only; ends → trial-expired page (P25).
### P13 Info builder + CSV dialog — Ref `ice-mockups/23_InfoBuilder.png`, `24_CsvExport.png` (*later*)
Info: side panel (form: type การ์ด 1080² / สรุป A4 1080×1527 / Top 10 1080×1350 · group รุ่น/แบรนด์/จังหวัด/เบอร์ยาง · scope · style โพเดียม…) + live preview; export PNG/PDF server-side with watermark + file code `TDR-INFO-<period>-<hex4>` + `export_log`; one Info = one Panel. Top 10 icons: model = car image (verified library) else initials; brand = 2-letter circle (**no logos**); province = shape; tyre = tyre icon. CSV (Enterprise): dialog lists panel/period/filters/fixed columns, UTF-8 BOM, `#` header lines, quota per org per calendar month (`app_settings.csv_monthly_quota`, default 20). Full spec = Ice `08_info_export.md` (owner-supplied; not in this repo).

## 3. Analysis Report & Upcoming
### P14 `/analysis` list
PageHead · filters (หมวด: รายงานรายเดือน/รายงานเจาะลึก/ชุดข้อมูล · ระดับ: สมาชิก / Pro / Enterprise · ปี) · featured latest (large) · card grid: **tall thumbnail** (top crop of the infographic; teaser image unless the viewer is entitled) · title · one-line summary · category · period · date · TierBadge · empty state. Never expose a clear image of a gated report (list, OG image, share).
### P15 `/analysis/[slug]`
Header: eyebrow category · H1 · summary · meta (งวด · ผู้เขียน · วันที่ · TierBadge) → key takeaways (public: first 1–2; rest for entitled) → **InfographicViewer** → method note (`[COPY]`) → related reports.
InfographicViewer: entitled = full-width `display` image via signed URL (short-lived, no-store), multi-image stacked, click/tap = lightbox with zoom/pan/pinch, on-screen watermark (username, ~8% opacity), "ดาวน์โหลด PNG" only if `downloadable` (server watermark + `export_log`). Not entitled = **teaser** image (top ~18% sharp, rest heavily blurred, generated server-side; original never referenced) + lock block over the blurred part: lock icon, "รายงานนี้สำหรับสมาชิก Pro", solid accent "อัปเกรดเป็น Pro", ghost "ทดลองฟรี 30 วัน" (if not signed up). Freemium in trial: button "ใช้สิทธิ์อ่าน (เหลือ n จาก 2)" → confirm dialog → unlock consumed on confirm, re-open free. Alt text (`alt_th`) on every image. Access matrix: DATA_MAP §Analysis.
### P16 `/upcoming` (+ "กำลังมา" tab in P02) — no Ref; components in `reference/components.html`
PageHead "รถที่กำลังมา" + summary counts per stage · filters (stage chips, body, powertrain, year, brand text) · sort "เปิดตัวเร็วสุด" (no window last) / "อัปเดตล่าสุด" · UpcomingCard: 16:9 image (licensed or covered-car illustration) · name (+ "ชื่อชั่วคราว" badge when not official) · StageBar (6 steps, navy fill up to current, text label) · ConfidenceMeter (4 segments + label) · launch-window text · tags (body, powertrain, "ตลาดโลกเท่านั้น" when GLOBAL_ONLY) · "อัปเดต x วัน/เดือนก่อน" · DELAYED = amber flag. **Never green/red** for stage/confidence. Public, no login.
### P17 `/upcoming/[slug]`
Hero (image, name, brand, badges) · StageBar large + state · Timeline (`stage_history`) · WindowBar (range bar whose width follows precision: year widest → day narrowest; label in พ.ศ.) · confidence + note · expected specs/price (only if given, flagged "ประมาณการ") · sources (list; leak-type sources hidden publicly if `public=false`, count still shown) · disclaimer "การคาดการณ์เป็นความเห็นของ TDR ไม่ใช่การยืนยันจากผู้ผลิต" · predecessor/competitor links · "อัปเดตล่าสุด <date>". LAUNCHED → 301 to the real model page.

## 4. Account & commerce
### P18 `/pricing` — Ref `ice-mockups/10_Pricing.png`
3 PricingCards: Freemium "ทดลองฟรี 30 วัน" ฿0 · Pro (highlighted) ฿1,099/เดือน | ฿11,490/ปี (toggle เดือน/ปี; "ประหยัด 12.9%", "เฉลี่ย ฿958/เดือน") accent CTA "อัปเกรดเป็น Pro" · Enterprise "ติดต่อทีม TDR" navy "Contact →" → `/contact?topic=enterprise` (no price, no phone). Comparison table (rows = Ice `02_tiers_matrix` capabilities incl. our merged rules; ✓/— with text for a11y). Payment-methods strip (card, PromptPay, TrueMoney, ShopeePay, Rabbit LINE Pay) as text chips. FAQ `[COPY]`. "ราคารวม VAT 7%".
### P19 Auth — Ref `ice-mockups/11_SignUp.png`, `12_OTP.png`, `13_Login.png`
`/signup` (email, password, phone, accept terms) · `/signup/otp` (6 boxes, resend timer, change number; success → P12 choose) · `/login` (email+password, forgot link) · `/login/forgot`. Split layout: left navy panel (`--surface-inverse`, logo on white plate, trial benefits), right form; phone: form only. Inline field errors, disabled-while-submitting, rate-limit message. Non-production shows "โหมดทดสอบ OTP" banner. Old `/member/login` → redirect.
### P20 `/checkout`, `/checkout/success` — Ref `ice-mockups/14_Checkout.png`
Summary card (plan, interval, price incl. VAT) · payment method radios (card, PromptPay, TrueMoney, ShopeePay, Rabbit LINE Pay; behind `PaymentProvider` interface — design only) · tax-invoice form (individual/company toggle: name, tax id, address) · total line "รวม VAT 7%" · accent "ชำระเงิน". Success: confirmation, plan/period, "ไปที่ Automotive Intelligence →", invoice link. Renewal notice text: "เราจะแจ้งเตือนก่อนต่ออายุ/หมดอายุ 7 วัน".
### P21 `/account` "บัญชีของฉัน" — Ref `ice-mockups/15_Account.png`
Tabs: **ภาพรวม** (tier badge, status, expiry, trial days left, upgrade CTA) · **การชำระเงิน** (history, invoices, payment method, cancel) · **โปรไฟล์** (email, phone verified, type individual/company, marketing consent) · **องค์กร** (Enterprise only: invite 1 more account, CSV quota used/limit). Replaces `/member/billing`, `/member/profile`.

## 5. Site pages
### P22 `/about` — Ref `ice-mockups/08_About.png` · content `[COPY]`
### P23 `/contact` — Ref `ice-mockups/09_Contact.png`
Form: ชื่อ · องค์กร · อีเมล · เบอร์ · หัวข้อ (select; `?topic=enterprise` preselects) · ข้อความ → table `contact_messages` + email notice (recipient from env). Success state; spam guard (honeypot + rate limit).
### P24 `/terms`, `/privacy` — reading template
Max-width 720px prose, desktop TOC sidebar, "อัปเดตล่าสุด" date; body `[COPY]` (owner/Ice supplies).
### P25 System pages
404 (search box + shortcuts) · trial-expired (what they keep: Compare Specs unlimited; what's locked; CTA "อัปเกรดเป็น Pro") · UpgradeDialog (locked action → what unlocks + prices + CTA) · payment-failed notice.
### P26 `/news`, `/companies` — kept, minimal
PageHead + simple list rows + empty state. Not in nav; `/news` stays in footer.
### P27 Admin `/admin/*` (21 sections)
Token/font swap only (no per-page redesign). Add: `/admin/upcoming` (list + form per SCHEMA_PLAN validation), `/admin/analysis` (multi-upload, drag-order, teaser preview, required alt), `/admin/packages` (Ice package import; later). Admin never uses accent CTA styling for destructive actions.

## 6. Redirect table (301)
`/market`→`/intelligence/share` · `/reports`→`/intelligence` · `/member`→`/intelligence` · `/member/market`→`/intelligence/share` · `/member/login`→`/login` · `/member/profile`,`/member/billing`→`/account` · `/research`→`/analysis` · `/research/[slug]`→`/analysis/[slug]` · `/plants`,`/production`(+slug)→`/models` (already) · `/upcoming` (old redirect) → new P16. `/api/*` unchanged in design PRs.
