# SCHEMA_PLAN.md — new tables, storage, pipelines (drafts for review; migrations are written in the feature PRs)

Repo posture (keep): RLS enabled with **no policies**; every read/write goes through the service-role client server-side; migrations are new files `supabase/migration_vNN_*.sql` (Retail Lineup Bootstrap owns merged **v53–v56**, never renumbered; this plan uses **v57 = upcoming**, **v58 = analysis**, fixed up front so parallel PRs don't collide. This supersedes the earlier v53/v54 reservation, made before Retail Lineup landed v53–v56; see docs/MERGE_DECISIONS.md). Never edit `automotive/vehicle_master/**` or canonical tables. `research_articles` was never deployed to production, so it is replaced, not migrated.

## 1. `upcoming_vehicles` (editorial; not Vehicle Master)
```sql
-- NOTE: OEM_CONFIRMED may carry any confidence — confidence is TDR's opinion on the Thailand launch window, not on the stage.
create table if not exists public.upcoming_vehicles (
  id uuid primary key default gen_random_uuid(),
  slug text not null unique,
  display_name text not null,
  name_kind text not null check (name_kind in ('OFFICIAL','WORKING','SEGMENT_CODE')),
  brand_text text not null,
  brand_canonical_id text,
  predecessor_model_id text,
  launched_model_id text,
  body_type text, segment text,
  powertrains text[] not null default '{}',
  production_type text check (production_type in ('CBU','CKD','SKD','UNKNOWN')),
  production_country text,
  stage text not null check (stage in ('RUMOR','REPORTED','OEM_TEASED','OEM_CONFIRMED','LAUNCH_DATE_SET','PRE_ORDER')),
  state text not null default 'ACTIVE' check (state in ('ACTIVE','DELAYED','CANCELLED','LAUNCHED')),
  thailand_scope text not null check (thailand_scope in ('TH_CONFIRMED','TH_EXPECTED','GLOBAL_ONLY')),
  confidence text not null check (confidence in ('LOW','MEDIUM','HIGH','CONFIRMED')),
  confidence_note text,
  window_precision text check (window_precision in ('YEAR','HALF','QUARTER','MONTH','DAY')),
  window_from date, window_to date, window_label_override text,
  expected_price_min numeric, expected_price_max numeric,
  summary_th text,
  last_verified_at date not null,
  sources jsonb not null default '[]',        -- [{kind:'OEM'|'MEDIA'|'LEAK'|'GOV', url, title, publisher, date, public:boolean}]
  stage_history jsonb not null default '[]',  -- [{stage, date, note}]
  image_path text,
  image_license text not null default 'NONE' check (image_license in ('OWN','PRESS_KIT','LICENSED','NONE')),
  image_credit text,
  status text not null default 'draft' check (status in ('draft','published')),
  published_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (stage <> 'RUMOR' or confidence in ('LOW','MEDIUM')),
  check (stage not in ('LAUNCH_DATE_SET','PRE_ORDER') or confidence = 'CONFIRMED'),
  check (window_from is null or window_precision is not null),
  check (window_to is null or window_from is null or window_to >= window_from),
  check (window_precision is distinct from 'DAY' or (window_from is not null and window_to is not null and window_from = window_to)),
  check (window_precision is null or window_from is not null),
  check (image_path is null or image_license <> 'NONE'),
  check (status <> 'published' or (published_at is not null and jsonb_array_length(sources) >= 1))
);
alter table public.upcoming_vehicles enable row level security;
create index on public.upcoming_vehicles (status, state, window_from nulls last);
```
Display rules: window text derived from precision+dates in Buddhist era (YEAR "ปี 2570", HALF "ครึ่งแรก/ครึ่งหลัง ปี 2570", QUARTER "ไตรมาส 3 ปี 2569", MONTH "ต.ค. 2569", DAY "15 ต.ค. 2569"; from≠to = "a – b"); `window_label_override` wins if set. Sort "soonest" = `window_from` asc nulls last. When launched: admin sets `launched_model_id`, `state='LAUNCHED'`; public route 301 → model page; row kept for history. Images live in public bucket `upcoming-images` only when `image_license <> 'NONE'` (no brand logos; owner uploads only).

## 2. Analysis Report tables
```sql
-- NOTE: teaser sharp strip is public on purpose (≤18% height).
-- NOTE: required_tier 'MEMBER' = readable in full by any signed-in member in trial or paid; anonymous and expired-trial users get teaser.
create table if not exists public.analysis_reports (
  id uuid primary key default gen_random_uuid(),
  slug text not null unique,
  title_th text not null, title_en text,
  summary_th text not null,
  category text not null check (category in ('MONTHLY','DEEP_DIVE','DATASET')),
  period_label text,
  required_tier text not null default 'PRO' check (required_tier in ('MEMBER','PRO','ENTERPRISE')),
  author text, tags text[] not null default '{}',
  key_takeaways jsonb not null default '[]',   -- array of strings; first 2 are public
  method_note text,
  downloadable boolean not null default false,
  status text not null default 'draft' check (status in ('draft','published')),
  published_at timestamptz,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  check (status <> 'published' or published_at is not null)
);
create table if not exists public.analysis_report_images (
  id uuid primary key default gen_random_uuid(),
  report_id uuid not null references public.analysis_reports(id) on delete cascade,
  position int not null,
  original_path text not null,   -- private bucket analysis-originals
  display_path text not null,    -- private bucket analysis-derived (2000w webp)
  thumb_path text not null,      -- private analysis-derived (clear, 600w) — used only for MEMBER-tier reports via signed URL
  teaser_path text not null,     -- PUBLIC bucket analysis-public (900w webp, blurred)
  teaser_thumb_path text not null, -- PUBLIC (600w, blurred)
  width int not null, height int not null, bytes int not null, sha256 text not null,
  alt_th text not null check (length(trim(alt_th)) > 0),
  unique (report_id, position)
);
create table if not exists public.analysis_report_unlocks (
  user_id uuid not null references auth.users(id) on delete cascade, report_id uuid not null references public.analysis_reports(id) on delete cascade,
  unlocked_at timestamptz not null default now(), source text not null default 'FREEMIUM_ALLOWANCE',
  primary key (user_id, report_id)
);
alter table public.analysis_reports enable row level security;
alter table public.analysis_report_images enable row level security;
alter table public.analysis_report_unlocks enable row level security;
```
Allowance rule (server): Freemium in trial may hold ≤2 rows in `analysis_report_unlocks` for PRO-tier reports; unlock endpoint is idempotent and transactional (advisory lock like `tdr_consume_usage`).

## 3. Storage
| Bucket | Public | Contents |
| --- | --- | --- |
| `analysis-originals` | no | uploaded PNG originals (never served directly) |
| `analysis-derived` | no | `display` webp, clear `thumb`; served only via signed URL (60–300 s, `no-store`) after the entitlement check |
| `analysis-public` | **yes** | **blurred only**: `teaser` + `teaser_thumb`. Invariant: the only clear pixels are the top strip of the teaser, capped at 18% of height and ≤ 400 px tall at 900w; everything below is blurred+downscaled. No other region of any report is ever clear here |
| `upcoming-images` | yes | licensed images only |

## 4. Upload & processing pipeline (Analysis)
1. Admin selects PNG(s) → **direct-to-storage signed upload** (Vercel functions cap request bodies at ~4.5 MB; 25 MB files cannot pass through a route).
2. Processing route (Node, `sharp`) reads the original from storage and validates: magic bytes = PNG; width 1200–4000 px; height ≤ 20,000 px; **total ≤ 60 megapixels** (set `limitInputPixels`; memory guard); bytes ≤ 25 MB; strip metadata; convert to sRGB; compute sha256. Reject with a Thai error message on any failure and delete the object.
3. Derivatives: `display` (2000w webp q≈82) · `thumb` (600w, crop = top of image, aspect ≤ 3:4) · **`teaser`**: top 18% of the image kept sharp, remaining 82% gaussian-blurred (σ ≈ 24 at 900w) **and** downscaled first so text is unreadable; add a fade at the seam · `teaser_thumb` (same treatment at 600w).
4. Record rows in `analysis_report_images`; admin sees the teaser preview before publishing.
5. Tier change MEMBER→PRO/ENTERPRISE (gated): nothing to purge (clear derivatives are private by construction). Deleting a report deletes all objects.
6. Entitled view: server checks tier/unlock → `createSignedUrl(display_path, 120)`; response headers `Cache-Control: private, no-store`. Never put original/display URLs in HTML for non-entitled viewers, in list JSON, in OG tags, or in sitemap.
7. Download (if `downloadable`): server composites a tiled username watermark onto a **downscaled copy (≤ 4000 px wide, from `display`-source quality)**, not the 60 MP original (serverless memory/time),, streams it, writes `export_log` (`TDR-RPT-<period>-<hex4>`). Watermark text must be rendered with an embedded Thai font (resvg/satori with IBM Plex Sans Thai buffer) — serverless has no Thai system fonts.

## 5. New/changed app settings & contact
`contact_messages(id, name, org, email, phone, topic, message, created_at, ip_hash)` · `free_trial(user_id pk, started_at, ends_at, breakdown, phone unique, fingerprint)` (from Ice `02_tiers_matrix`) · env: `CONTACT_NOTIFY_EMAIL`, `ALLOW_UNCONFIRMED_PACKAGES` (local only).

## 6. Required tests (in the feature PR)
- `check-analysis-privacy`: for a gated report, render list/detail/OG/JSON for anonymous & wrong-tier users → assert no `analysis-originals`/`analysis-derived` path or signed URL appears; assert `analysis-public` objects are never byte-identical to `display`; decode each teaser and assert the sharp region ≤ 18% of height (measure Laplacian variance per band: bands below the cap must fall under a threshold, i.e. text unreadable).
- Upcoming constraint tests: each `check` above accepts/rejects the listed cases; published without a source rejected; LAUNCHED hidden from list.
- Unlock: concurrent double-confirm consumes 1 allowance; third PRO-report unlock rejected.

## 7. Boundary with vehicle facts (AGENTS.md)
`upcoming_vehicles.body_type / powertrains / production_type / expected_price_*` are **pre-launch estimates**, labelled "ประมาณการ" in the UI. They never feed Compare, registration market, or catalogue counts. Once `launched_model_id` is set, canonical data wins and these fields are ignored for display.
