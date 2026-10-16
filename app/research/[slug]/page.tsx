import Link from "next/link";
import { notFound } from "next/navigation";
import { Card, PageHead } from "@/components/design";
import { getPublishedResearchArticlePreviewBySlug } from "@/lib/research";
import { ResearchUnlock } from "./ResearchUnlock";
import "../research.css";

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

  return <div className="designPage tdr-research">
    <div className="tdr-wrap">
      <nav className="tdr-research-crumbs" aria-label="เส้นทาง">
        <Link href="/research">บทวิเคราะห์เชิงลึก</Link>
        <span aria-hidden="true">/</span>
        <span aria-current="page">{article.titleTh}</span>
      </nav>

      <PageHead
        eyebrow="บทวิเคราะห์เชิงลึก"
        title={article.titleTh}
        lead={<span className="tdr-research-meta">
          {article.author ? <span>{article.author}</span> : null}
          <time dateTime={article.publishedAt}>{article.publishedAt.slice(0, 10)}</time>
        </span>}
      />

      <Card as="section" className="tdr-research-summary">
        <p>{article.summaryTh}</p>
      </Card>

      <ResearchUnlock slug={article.slug} />
    </div>
  </div>;
}
