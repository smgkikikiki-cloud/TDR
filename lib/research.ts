/**
 * Layer 4 content: "บทวิเคราะห์เชิงลึก" (deep-analysis pieces).
 *
 * Reads go through the service-role client on purpose, even for the
 * public list -- see the table comment on research_articles in
 * migration_v38. Every function here is safe to call from a Server
 * Component; nothing here is safe to import into a "use client" file
 * (adminDb() pulls in the service-role key).
 */
import { adminDb } from "@/lib/supabase";

export type ResearchArticlePreview = {
  id: string;
  slug: string;
  titleTh: string;
  summaryTh: string;
  author: string | null;
  publishedAt: string;
};

function toPreview(row: any): ResearchArticlePreview {
  return {
    id: row.id,
    slug: row.slug,
    titleTh: row.title_th,
    summaryTh: row.summary_th,
    author: row.author ?? null,
    publishedAt: row.published_at,
  };
}

/** A deployment may ship the research UI before migration_v38 has been applied
 * to its database. In that state research is simply an empty catalogue; an
 * optional content layer must not take the public homepage down.
 *
 * Supabase can report a missing relation in two ways depending on where it is
 * observed: PostgreSQL itself uses 42P01, while PostgREST returns PGRST205 when
 * the table is absent from its schema cache. Both describe the same expected
 * pre-migration state here. */
function researchTableMissing(error: any): boolean {
  const code = String(error?.code || "");
  if (code === "42P01" || code === "PGRST205") return true;
  const message = String(error?.message || "").toLowerCase();
  if (!message.includes("research_articles")) return false;
  return message.includes("does not exist")
    || message.includes("not found")
    || message.includes("could not find")
    || message.includes("schema cache");
}

/** Every published piece, newest first. What the public list and the
 *  admin-facing "which article did I unlock" checks both need -- never the
 *  body, which only the unlock route reads. */
export async function getPublishedResearchArticles(limit = 100): Promise<ResearchArticlePreview[]> {
  const db = adminDb();
  if (!db) return [];
  const { data, error } = await db
    .from("research_articles")
    .select("id,slug,title_th,summary_th,author,published_at")
    .eq("status", "published")
    .order("published_at", { ascending: false })
    .limit(limit);
  if (error) {
    if (researchTableMissing(error)) return [];
    throw error;
  }
  return (data || []).map(toPreview);
}

/** One published piece by its public slug, or null -- metadata only, never
 *  body_th. A draft or a slug nobody has published never resolves here --
 *  the article page's notFound() relies on that.
 *
 *  This is the only place the public article page reads from: body_th is
 *  never selected here, so it is structurally impossible for the public
 *  rendering path to leak it, even by accident. The one place in the
 *  codebase that ever selects body_th is app/api/research/read/route.ts,
 *  the protected unlock route, which reads it with its own query rather
 *  than through this file -- so a leak stays a one-file, one-query
 *  surface, not something a future change to this module could reopen. */
export async function getPublishedResearchArticlePreviewBySlug(slug: string): Promise<ResearchArticlePreview | null> {
  const db = adminDb();
  if (!db || !slug) return null;
  const { data, error } = await db
    .from("research_articles")
    .select("id,slug,title_th,summary_th,author,published_at")
    .eq("slug", slug)
    .eq("status", "published")
    .maybeSingle();
  if (error) {
    if (researchTableMissing(error)) return null;
    throw error;
  }
  return data ? toPreview(data) : null;
}
