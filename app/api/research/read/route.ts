import { NextRequest, NextResponse } from "next/server";
import { periodKeyForMetric } from "@/lib/access-policy";
import { AccessPolicyError, requireMemberAccess, requireUsage } from "@/lib/access-policy-server";
import { recordEvent } from "@/lib/telemetry";

export const dynamic = "force-dynamic";

function bearer(request: NextRequest) {
  const match = /^Bearer\s+(.+)$/i.exec(request.headers.get("authorization") || "");
  return match?.[1] || null;
}

/**
 * The one route that ever returns an article's full text.
 *
 * An anonymous reader never reaches this at all -- the public page renders
 * only the title, author and summary itself, and this route 401s without a
 * token. A signed-in reader unlocks an article by spending one unit of the
 * `research_full` quota (null on paid tiers = unlimited); reading the same
 * article again afterward is free forever, because research_article_reads
 * existing for (user, article) is checked before any quota is touched.
 */
export async function GET(request: NextRequest) {
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

    const { data: existingRead, error: readError } = await ctx.db
      .from("research_article_reads")
      .select("article_id")
      .eq("user_id", ctx.userId)
      .eq("article_id", article.id)
      .maybeSingle();
    if (readError) throw new AccessPolicyError(503, "could not check reading history");

    let quota: Awaited<ReturnType<typeof requireUsage>> | null = null;
    if (!existingRead) {
      quota = await requireUsage(ctx, "research_full", ctx.policy.researchFullMonthlyLimit, [article.id]);
      const { error: insertError } = await ctx.db.from("research_article_reads").insert({
        user_id: ctx.userId,
        article_id: article.id,
        period_key: periodKeyForMetric("research_full"),
      });
      // A concurrent double-submit racing this same unlock is the only
      // expected cause -- the read is already recorded either way, so this
      // is not an error worth failing the request over.
      if (insertError && insertError.code !== "23505") throw new AccessPolicyError(503, "could not record the unlock");
    }

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
      already_unlocked: Boolean(existingRead),
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
