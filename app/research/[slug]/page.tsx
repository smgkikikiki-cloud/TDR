import Link from "next/link";
import { notFound } from "next/navigation";
import { getPublishedResearchArticlePreviewBySlug } from "@/lib/research";
import { ResearchUnlock } from "./ResearchUnlock";

export const dynamic = "force-dynamic";

/**
 * The title, author, date and summary are public and server-rendered --
 * readable, shareable, indexable, exactly like everything else on the
 * site. The full body is the one thing that isn't: ResearchUnlock (a
 * client component, because it needs the reader's own session) is what
 * decides whether a reader ever sees it.
 */
export default async function ResearchArticlePage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const article = await getPublishedResearchArticlePreviewBySlug(slug);
  if (!article) notFound();

  return <div className="researchPage">
    <nav className="sfCrumbs" aria-label="เส้นทาง">
      <Link href="/research">บทวิเคราะห์เชิงลึก</Link>
      <span aria-hidden="true">/</span>
      <b>{article.titleTh}</b>
    </nav>

    <article className="researchHero">
      <div className="sfEyebrow">บทวิเคราะห์เชิงลึก</div>
      <h1>{article.titleTh}</h1>
      <div className="researchMeta">
        {article.author ? <span>{article.author}</span> : null}
        <time>{article.publishedAt.slice(0, 10)}</time>
      </div>
      <p className="researchSummary">{article.summaryTh}</p>
    </article>

    <ResearchUnlock slug={article.slug} />
  </div>;
}
