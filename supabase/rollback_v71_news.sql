-- Removes the News feature tables (deletes all news content). The bucket must be
-- emptied from the Supabase dashboard / Storage API before it can be dropped.
drop table if exists public.news_related;
drop table if exists public.news_article_tags;
drop table if exists public.news_articles;
drop table if exists public.news_tags;
