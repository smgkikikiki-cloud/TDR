import Link from "next/link";
import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { Card, CardHead, Chip } from "@/components/design";
import { BreakingBadge } from "@/components/NewsBadge";
import { getPublishedNewsBySlug } from "@/lib/news";
import { formatThaiDate, isBreaking, splitParagraphs } from "@/lib/news-format";

export const dynamic = "force-dynamic";

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const a = await getPublishedNewsBySlug(slug);
  return a ? { title: a.title, description: a.summary || undefined } : {};
}

export default async function NewsArticlePage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const a = await getPublishedNewsBySlug(slug);
  if (!a) notFound();

  return (
    <div className="tdr-wrap">
      <article className="tdr-news-art">
        <nav className="tdr-news-art__crumbs" aria-label="เส้นทาง">
          <Link href="/news">ข่าว</Link><span aria-hidden="true">›</span><span>{a.title}</span>
        </nav>

        <div className="tdr-news__meta">
          {isBreaking(a.publishedAt) ? <BreakingBadge /> : null}
          <time dateTime={a.publishedAt}>{formatThaiDate(a.publishedAt, true)}</time>
        </div>
        <h1 className="tdr-news-art__title">{a.title}</h1>
        {a.summary ? <p className="tdr-news-art__lead">{a.summary}</p> : null}
        {a.tags.length ? (
          <div className="tdr-news__tags">
            {a.tags.map((t) => <Chip key={t.id} href={`/news?tag=${encodeURIComponent(t.slug)}`}>{t.name}</Chip>)}
          </div>
        ) : null}

        {a.heroImageUrl ? (
          <figure className="tdr-news-art__hero">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={a.heroImageUrl} alt={a.heroImageAlt || a.title} />
            {a.heroImageCredit ? <figcaption>ภาพ: {a.heroImageCredit}</figcaption> : null}
          </figure>
        ) : null}

        <div className="tdr-news-art__body">
          {splitParagraphs(a.body).map((p, i) => <p key={i}>{p}</p>)}
        </div>

        {a.related.length || a.externalLinks.length ? (
          <aside className="tdr-news-art__more" aria-label="แนะนำให้อ่านต่อ">
            <Card tone="raised">
              <CardHead title="แนะนำให้อ่านต่อ" />
              <ul>
                {a.related.map((r) => (
                  <li key={r.id}>
                    <Link href={`/news/${r.slug}`}>{r.title}</Link>
                    <time dateTime={r.publishedAt}>{formatThaiDate(r.publishedAt)}</time>
                  </li>
                ))}
                {a.externalLinks.map((l) => (
                  <li key={l.url}><a href={l.url} target="_blank" rel="noreferrer noopener">{l.title} ↗</a></li>
                ))}
              </ul>
            </Card>
          </aside>
        ) : null}
      </article>
    </div>
  );
}
