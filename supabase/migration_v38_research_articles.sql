-- Layer 4: บทวิเคราะห์เชิงลึก ("Research"), a real content model.
--
-- Until now app/research/page.tsx hardcoded an empty array and
-- app/api/research/route.ts served a two-line stub -- there was nowhere
-- for an admin to write a piece, and nothing for a reader to unlock. This
-- gives the admin authoring surface (app/admin/actions.ts's
-- saveResearchArticle, reused via the generic /admin/library table
-- config) somewhere to write to, and the public/member routes something
-- real to read.
--
-- Same posture as the rest of the admin-authored tables: RLS enabled with
-- zero policies. Every reader of this table -- the public list, the
-- article page, the full-text unlock route -- goes through the
-- service-role client server-side (lib/research.ts, app/api/research/
-- read/route.ts), same as admin_edit_sessions and canonical_input_batches.
-- The RLS/grant posture below is defense in depth, not the enforcement
-- path: PostgREST access with the anon/authenticated key is never how a
-- reader is meant to reach this table, published or not.

create table if not exists public.research_articles (
  id uuid primary key default gen_random_uuid(),
  slug text not null unique,
  title_th text not null,
  title_en text,
  summary_th text not null,
  body_th text not null,
  author text,
  status text not null default 'draft' check (status in ('draft', 'published')),
  published_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  constraint research_articles_published_has_timestamp
    check (status <> 'published' or published_at is not null)
);

create index if not exists research_articles_published_idx
  on public.research_articles(published_at desc)
  where status = 'published';

alter table public.research_articles enable row level security;
revoke all on table public.research_articles from public, anon, authenticated;
grant select, insert, update, delete on table public.research_articles to service_role;

comment on table public.research_articles is
  'Editorial deep-analysis pieces ("บทวิเคราะห์เชิงลึก"). Server-only: the public list, the article page, and the full-text unlock route all read through the service-role client. RLS is enabled with zero policies as defense in depth.';

-- One row per (member, article) the first time they unlock the full text.
-- Existence of the row *is* the entitlement: a member who has ever
-- unlocked an article rereads it free, forever, without spending another
-- month's quota -- app/api/research/read/route.ts checks this before it
-- ever calls tdr_consume_usage. period_key records which cycle the
-- unlock was actually spent from, for audit/support only; it is never
-- read back to decide whether the gate opens.
create table if not exists public.research_article_reads (
  user_id uuid not null references auth.users(id) on delete cascade,
  article_id uuid not null references public.research_articles(id) on delete cascade,
  period_key text not null,
  unlocked_at timestamptz not null default now(),
  primary key (user_id, article_id)
);

create index if not exists research_article_reads_user_idx
  on public.research_article_reads(user_id);

alter table public.research_article_reads enable row level security;
revoke all on table public.research_article_reads from public, anon, authenticated;
grant select, insert on table public.research_article_reads to service_role;

comment on table public.research_article_reads is
  'Per-member unlock log for research_articles. A row existing is the entitlement to reread that article free; see the table comment on why period_key is audit-only.';
