/**
 * News feed reads. Service-role client on purpose (see migration_v71_news):
 * server-only, never import into a "use client" file.
 *
 * Like research, a deployment may ship this UI before migration_v71 is applied;
 * in that state the feed is simply empty rather than taking the page down.
 */
import { adminDb } from "@/lib/supabase";
import type { ExternalLink } from "@/lib/news-format";

export type NewsTag = { id: string; slug: string; name: string };

export type NewsPreview = {
  id: string;
  slug: string;
  title: string;
  summary: string | null;
  heroImageUrl: string | null;
  heroImageAlt: string | null;
  heroImageCredit: string | null;
  publishedAt: string;
  tags: NewsTag[];
};

export type NewsArticle = NewsPreview & {
  body: string;
  externalLinks: ExternalLink[];
  related: NewsPreview[];
};

export function newsTableMissing(error: any): boolean {
  const code = String(error?.code || "");
  if (code === "42P01" || code === "PGRST205") return true;
  const message = String(error?.message || "").toLowerCase();
  return message.includes("news_") && (message.includes("does not exist") || message.includes("schema cache") || message.includes("could not find"));
}

const PREVIEW_COLUMNS = "id,slug,title_th,summary_th,hero_image_url,hero_image_alt,hero_image_credit,published_at";

async function tagsFor(db: any, articleIds: string[]): Promise<Map<string, NewsTag[]>> {
  const map = new Map<string, NewsTag[]>();
  if (!articleIds.length) return map;
  const { data, error } = await db
    .from("news_article_tags")
    .select("article_id,news_tags(id,slug,name_th)")
    .in("article_id", articleIds);
  if (error) { if (newsTableMissing(error)) return map; throw error; }
  for (const row of data || []) {
    const tag = Array.isArray(row.news_tags) ? row.news_tags[0] : row.news_tags;
    if (!tag) continue;
    const list = map.get(row.article_id) || [];
    list.push({ id: tag.id, slug: tag.slug, name: tag.name_th });
    map.set(row.article_id, list);
  }
  for (const list of map.values()) list.sort((a, b) => a.name.localeCompare(b.name, "th"));
  return map;
}

function toPreview(row: any, tags: Map<string, NewsTag[]>): NewsPreview {
  return {
    id: row.id,
    slug: row.slug,
    title: row.title_th,
    summary: row.summary_th ?? null,
    heroImageUrl: row.hero_image_url ?? null,
    heroImageAlt: row.hero_image_alt ?? null,
    heroImageCredit: row.hero_image_credit ?? null,
    publishedAt: row.published_at,
    tags: tags.get(row.id) || [],
  };
}

/** Published articles, newest first; optionally only those carrying one tag. */
export async function getPublishedNews(opts: { limit?: number; tagSlug?: string } = {}): Promise<NewsPreview[]> {
  const db = adminDb();
  if (!db) return [];
  let ids: string[] | null = null;
  if (opts.tagSlug) {
    const { data: tag, error: tagError } = await db.from("news_tags").select("id").eq("slug", opts.tagSlug).maybeSingle();
    if (tagError) { if (newsTableMissing(tagError)) return []; throw tagError; }
    if (!tag) return [];
    const { data: links, error: linkError } = await db.from("news_article_tags").select("article_id").eq("tag_id", tag.id);
    if (linkError) throw linkError;
    ids = (links || []).map((l: any) => l.article_id);
    if (!ids.length) return [];
  }
  let query = db.from("news_articles").select(PREVIEW_COLUMNS).eq("status", "published")
    .order("published_at", { ascending: false }).limit(opts.limit ?? 100);
  if (ids) query = query.in("id", ids);
  const { data, error } = await query;
  if (error) { if (newsTableMissing(error)) return []; throw error; }
  const rows = data || [];
  const tags = await tagsFor(db, rows.map((r: any) => r.id));
  return rows.map((r: any) => toPreview(r, tags));
}

/** Tags that at least one published article carries, for the filter row. */
export async function getUsedNewsTags(): Promise<NewsTag[]> {
  const news = await getPublishedNews({ limit: 200 });
  const byId = new Map<string, NewsTag>();
  for (const a of news) for (const t of a.tags) byId.set(t.id, t);
  return [...byId.values()].sort((a, b) => a.name.localeCompare(b.name, "th"));
}

export async function getPublishedNewsBySlug(slug: string): Promise<NewsArticle | null> {
  const db = adminDb();
  if (!db || !slug) return null;
  const { data, error } = await db.from("news_articles")
    .select(`${PREVIEW_COLUMNS},body_th,external_links`).eq("slug", slug).eq("status", "published").maybeSingle();
  if (error) { if (newsTableMissing(error)) return null; throw error; }
  if (!data) return null;

  const { data: relRows, error: relError } = await db.from("news_related")
    .select("related_id,sort_order").eq("article_id", data.id).order("sort_order");
  if (relError) throw relError;
  const relIds = (relRows || []).map((r: any) => r.related_id);
  let related: any[] = [];
  if (relIds.length) {
    const { data: relArticles, error } = await db.from("news_articles").select(PREVIEW_COLUMNS)
      .in("id", relIds).eq("status", "published");
    if (error) throw error;
    const order = new Map(relIds.map((id: string, i: number) => [id, i]));
    related = (relArticles || []).sort((a: any, b: any) => (order.get(a.id) as number) - (order.get(b.id) as number));
  }
  const tags = await tagsFor(db, [data.id, ...related.map((r) => r.id)]);
  return {
    ...toPreview(data, tags),
    body: data.body_th,
    externalLinks: Array.isArray(data.external_links) ? data.external_links : [],
    related: related.map((r) => toPreview(r, tags)),
  };
}
