-- TDR News: lightweight editorial news feed ("ข่าว"), authored in /admin/news.
--
-- Editorial only: articles may be tagged and linked to each other but never
-- redefine vehicle facts (AGENTS.md, canonical vehicle boundary).
--
-- Same posture as research_articles (migration_v38): RLS enabled with zero
-- policies; every reader and writer goes through the service-role client
-- server-side (lib/news.ts, app/admin/news-actions.ts). Hero images live in a
-- PUBLIC Storage bucket so <img> can load them; only service_role can write it.

create table if not exists public.news_tags (
  id uuid primary key default gen_random_uuid(),
  slug text not null unique,
  name_th text not null unique,
  created_at timestamptz not null default now()
);

create table if not exists public.news_articles (
  id uuid primary key default gen_random_uuid(),
  slug text not null unique,
  title_th text not null,
  summary_th text,
  body_th text not null,
  hero_image_url text,
  hero_image_alt text,
  -- Photo credit shown under the hero (DESIGN.md §9: images carry a credit).
  hero_image_credit text,
  -- Extra "read more" links to outside pages, one {"title","url"} per element.
  external_links jsonb not null default '[]'::jsonb,
  status text not null default 'draft' check (status in ('draft', 'published')),
  published_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint news_articles_published_has_timestamp
    check (status <> 'published' or published_at is not null)
);

create index if not exists news_articles_published_idx
  on public.news_articles(published_at desc)
  where status = 'published';

create table if not exists public.news_article_tags (
  article_id uuid not null references public.news_articles(id) on delete cascade,
  tag_id uuid not null references public.news_tags(id) on delete cascade,
  primary key (article_id, tag_id)
);
create index if not exists news_article_tags_tag_idx on public.news_article_tags(tag_id);

-- "แนะนำให้อ่านต่อ": an ordered list of other articles, set by the editor.
create table if not exists public.news_related (
  article_id uuid not null references public.news_articles(id) on delete cascade,
  related_id uuid not null references public.news_articles(id) on delete cascade,
  sort_order int not null default 0,
  primary key (article_id, related_id),
  check (article_id <> related_id)
);

alter table public.news_tags enable row level security;
alter table public.news_articles enable row level security;
alter table public.news_article_tags enable row level security;
alter table public.news_related enable row level security;
revoke all on table public.news_tags, public.news_articles, public.news_article_tags, public.news_related
  from public, anon, authenticated;
grant select, insert, update, delete on table
  public.news_tags, public.news_articles, public.news_article_tags, public.news_related
  to service_role;

comment on table public.news_articles is
  'Editorial news feed. Server-only: public pages and /admin/news read and write through the service-role client; RLS enabled with zero policies as defense in depth.';

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('news-images', 'news-images', true, 4194304,
        array['image/jpeg', 'image/png', 'image/webp', 'image/avif'])
on conflict (id) do nothing;
