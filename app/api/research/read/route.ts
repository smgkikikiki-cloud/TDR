import { NextRequest, NextResponse } from "next/server";
import { AccessPolicyError, requireMemberAccess, unlockResearchArticle } from "@/lib/access-policy-server";
import { recordEvent } from "@/lib/telemetry";

export const dynamic = "force-dynamic";

function bearer(request: NextRequest) {
  const match = /^Bearer\s+(.+)$/i.exec(request.headers.get("authorization") || "");
  return match?.[1] || null;
}

/**
 * The one route that ever returns an article's full text, and the one
 * place in the codebase that ever selects body_th (see
 * lib/research.ts::getPublishedResearchArticlePreviewBySlug, which the
 * public article page reads instead and never selects it).
 *
 * POST, not GET: unlocking spends a quota unit and writes a permanent
 * entitlement row (research_article_reads), so it must never be something
 * a prefetcher, browser extension or proxy can trigger just by resolving a
 * URL -- GET is meant to be safe/idempotent, and this isn't.
 *
 * An anonymous reader never reaches this at all -- the public page renders
 * only the title, author and summary itself, and this route 401s without
 * a token. A signed-in reader unlocks an article by spending one unit of
 * the `research_full` quota (null on paid tiers = unlimited); reading the
 * same article again afterward is free forever. The existence check, the
 * quota spend and the read-record insert all happen inside one Postgres
 * transaction (tdr_unlock_research_article, migration_v50) rather than as
 * three separate round trips -- see unlockResearchArticle's own doc
 * comment for the two correctness bugs that fixes.
 */
export async function POST(request: NextRequest) {
  const accessToken = bearer(request);
  if (!accessToken) {
    return NextResponse.json({ error: "เข้าสู่ระบบเพื่ออ่านบทวิเคราะห์ฉบับเต็ม" }, { status: 401 });
  }

  const slug = request.nextUrl.searchParams.get("slug");
  if (!slug) return NextResponse.json({ error: "missing slug" }, { status: 400 });

  try {
    const ctx = await requireMemberAccess(accessToken);

    const { data: article, error: articleError } = await ctx.db
      .from("research_articles")
      .select("id,slug,title_th,summary_th,body_th,author,published_at")
      .eq("slug", slug)
      .eq("status", "published")
      .maybeSingle();
    if (articleError) throw new AccessPolicyError(503, "could not load the article");
    if (!article) return NextResponse.json({ error: "ไม่พบบทวิเคราะห์นี้" }, { status: 404 });

    const { alreadyUnlocked, quota } = await unlockResearchArticle(ctx, article.id, ctx.policy.researchFullMonthlyLimit);

    await recordEvent({ eventName: "research_full_opened", userId: ctx.userId, props: { article_id: article.id } });

    return NextResponse.json({
      article: {
        slug: article.slug,
        title_th: article.title_th,
        summary_th: article.summary_th,
        body_th: article.body_th,
        author: article.author,
        published_at: article.published_at,
      },
      already_unlocked: alreadyUnlocked,
      quota,
    }, { headers: { "Cache-Control": "private, no-store" } });
  } catch (error) {
    if (error instanceof AccessPolicyError) {
      return NextResponse.json({ error: error.message }, { status: error.status });
    }
    console.error("research read error", error);
    return NextResponse.json({ error: "โหลดบทวิเคราะห์ไม่สำเร็จ" }, { status: 500 });
  }
}
