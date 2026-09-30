# DESIGN.md — TDR design rules (read before any UI change)

Decisions by the owner (กี้) live in `docs/MERGE_DECISIONS.md`; it wins over this file. Conflict → ask. Thai strings in quotes are exact UI copy.

## 1. Sources of truth (priority order)
1. `docs/MERGE_DECISIONS.md`
2. this file
3. `design/tokens.json` → generated `design/tokens.css` (never hand-edit; `node --experimental-strip-types scripts/build-design-tokens.ts`)
4. `design/components.css` (`tdr-btn`, `tdr-chip`, `tdr-tier`, `tdr-flag`, `tdr-kpi`, `tdr-delta`, `tdr-watermark`)
5. `design/reference/home_v7.html` — approved homepage (layout, components, copy, breakpoints, dark mode). `reference/screens/*.png` = same page at 1440/1024/834/390 × light/dark (rendered with fallback fonts: trust the HTML for type, PNGs for layout/spacing)
6. `design/reference/ice-mockups/NN_*.png` — Ice's desktop mockups for pages without our own reference. **Skip 02–05 (news/industrial: removed).**
`tokens.ice-original.json` is archive only.

Token-efficient use: open the reference HTML only for the section you're building (search by class/heading); view a PNG only when comparing that page.

## 2. Workflow
- One task per PR (tokens / shell / one page) on `design/<task>` (has Vercel preview). Never commit to main.
- Copy from references; don't invent. Page with no reference → compose from reference components, owner reviews before merge.
- No scope creep: no data/permission/payment logic in design PRs.
- Unsure → ask; never guess copy, numbers, permissions, colours.
- Add every migrated file to `design/migrated.json` → `strict` in the same PR.
- Before PR: `npm run check` passes; attach preview screenshots at 1440/1024/834/390, light+dark.

## 3. Colour
- Only `var(--token)`. No #hex/rgb()/hsl() in app/ or components/ (guard fails on strict files).
- Brand navy/blue (`--brand-navy`, `--brand-blue`, `--action-primary`) = main voice: headings, nav, secondary buttons, Intelligence band (`--surface-inverse`).
- Red (Ice's red restriction is cancelled):
  - `--accent` solid primary CTA, **max 1 per viewport**; other buttons in that view are outline.
  - `--red-text` for emphasis only: section eyebrows, key words in headings (`<span class="hl">`), "ดูทั้งหมด →" links, free price / savings. Never body text.
- Deltas: `--delta-up` green with ▲ and `+`; `--delta-down` red with ▼ and `−`. Arrow + sign always; never colour alone.
- Sequential map: `--map-1…5` (light→dark). Selected province: `--accent`.
- Diverging map: `--diverge-1` (big drop) … `--diverge-3` (≈0 or base <30) … `--diverge-5` (big rise). Legend with +/−; tap shows number.
- Categorical charts (donut/stacked): `--chart-cat-1…5` in that order; >5 groups → "อื่นๆ"; every slice has a visible number/table.
- Dark mode from day one: `data-theme` on `<html>` + `prefers-color-scheme`. TDR logo on dark sits on a white plate.

## 4. Type
- Headings `--font-display` (Anuphan), body `--font-sans` (IBM Plex Sans Thai), **all numbers** `--font-mono` (IBM Plex Mono) + `tabular-nums`. Load via `next/font/google`.
- Body 16px (phone 15), min 12px.
- Thai: no letter-spacing (only English uppercase eyebrows); buttons/nav/badges `nowrap`; headings `word-break: keep-all` and **no single-word last line** (wrap the tail phrase in nowrap).
- Thousands separators; Buddhist-era dates ("ส.ค. 2569").

## 5. Shape & spacing
- Radius: badge `--radius-sm`, button/input `--radius-md`, card `--radius-lg`, big panel 16px, chip/tier `--radius-pill`.
- Cards: `--border`, **no shadow**. `--shadow-pop` only for floating things (menus, sheets, dialogs, Info preview) and the main `--accent` button.
- Hit targets ≥44px. Side gutter: 96px (≥1400), 40px (1024–1399), 24px (768–1023), 16px (≤767).

## 6. Breakpoints (tablet is required)
| Width | Change |
| --- | --- |
| ≥1400 | as reference 1440 |
| 1280–1399 | tighter nav gaps, logo 32px, gutter 40 |
| 1024–1279 | hide header "แพ็กเกจ" link; 3-col grids → 2 |
| 768–1023 | nav → ☰; two-column sections stack |
| ≤767 | single column; bottom bar 4 items (หน้าแรก · Intelligence · ฐานข้อมูล · บัญชี); primary CTA full width |
No horizontal overflow at 1440/1366/1280/1024/834/390 (header has overflowed at 1024 and 1280 before).

## 7. Shell
- Header: TDR logo (`design/assets/brand/`), nav **Automotive Intelligence · Vehicle Database · Compare Specs · Analysis Report** (this order, English), theme toggle, "แพ็กเกจ" link, "เข้าสู่ระบบ" (outline), "สมัครสมาชิก" (navy outline).
- Footer: `--surface-inverse`, logo on white plate, เกี่ยวกับ TDR · ติดต่อเรา · แพ็กเกจ · ข่าวและการเปลี่ยนแปลง (/news) · เงื่อนไขการใช้บริการ · นโยบายความเป็นส่วนตัว, source line.
- No Auto News, no Industrial Update.

## 8. Data display
- Every page with numbers: small source line "ที่มา: กรมการขนส่งทางบก (Open Data Common)".
- Bangkok note: place of registration, not place of use.
- Wheel/tyre values: `tdr-flag--estimate` "ประมาณการ" + "ครอบคลุม X%".
- % change only when base ≥30, else "–".
- Share vs previous month in **pp** with arrow; units on hover/tap.
- Never hard-code numbers or number-derived sentences (e.g. "รถใหม่ 35% เป็น EV แล้ว"); compute from latest period.
- Locked content: static decorative placeholder + `tdr-tier` badge, never hidden and never real data blurred (see §10.5). Only the Analysis teaser (server-generated) may show a sharp strip.
- `.tdr-watermark` is a deterrent, not protection: it does not stop screenshots. Say so wherever it's described.
- Map/diverge midpoint (`--diverge-3`) and any fill under 3:1 against the page needs a 1px `--border-strong` outline (defined in tokens.json; diverge-2/3/4 and map-1/2 need it); chart slice colours in light mode are ≥3:1 vs white.
- Tier badges: `tdr-tier--free` = plan/quota "Free"; `tdr-tier--member` "สมาชิก" = Analysis report `required_tier = MEMBER`; `--pro`; `--enterprise`. Never reuse `--free` for a report's tier.
- Freemium screens and every exported file: username watermark.

## 9. Logos & images
- **No car-brand logos anywhere** (no `resolveBrandLogo()` / `logo_url` in strict files). Use brand names as text chips or generic line icons.
- Body types: the 6 side-view line icons from the reference (sedan, SUV, pickup, MPV, hatchback, van).
- Car photos only from the verified image library with credit; none → show none.
- TDR logo only from `design/assets/brand/`; never redraw/recolour.

## 10. Copy
- Thai, short, factual; no superlatives ("ดีที่สุด", "ละเอียดที่สุด").
- Buttons state the benefit: "เริ่มดูฟรี 30 วัน →", "ดูครบ 77 จังหวัด ฟรี →", "อัปเกรดเป็น Pro".
- Under the signup CTA: "✓ ไม่ต้องใช้บัตร · ✓ ยืนยันด้วยเบอร์โทร · ✓ ครบ 30 วันไม่ตัดเงิน".
- Prices incl. VAT: Pro ฿1,099/เดือน or ฿11,490/ปี ("ประหยัด 12.9%", "เฉลี่ย ฿958/เดือน"). Enterprise: **no price, no phone**; navy button "Contact →" to the contact page.

## 10.5 Locked content & new features (added 29 ก.ย.)
- Locked block = static decorative placeholder + `tdr-tier` badge. DOM/JSON/OG/sitemap must contain **no real values**. Never CSS-blur real data or real files.
- Per-page specs: `design/PAGES.md` (P01–P27, redirects). Data sources: `design/DATA_MAP.md`. New tables/buckets: `design/SCHEMA_PLAN.md`. Order of work: `design/GRAFT_PLAN.md`.
- Top menu unchanged (4 items); Upcoming lives at `/upcoming` + a tab in /models (PAGES.md P16); shared components in `design/reference/components.html`.
- Every page implements 4 states: loading / empty / locked / error.

## 11. Done when
- [ ] Matches reference (structure, order, components, copy) at 4 widths × 2 themes
- [ ] `npm run check` passes; changed files listed in `design/migrated.json`
- [ ] No horizontal overflow at the 6 widths
- [ ] No car logos; source line present; deltas have arrow + sign
- [ ] ≤1 solid red button per viewport
- [ ] PR has 8 preview screenshots + changed-file list
