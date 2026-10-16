import Link from "next/link";
import { Card, Chip, PageHead } from "@/components/design";
import { BreakingBadge } from "@/components/NewsBadge";
import { getPublishedNews, getUsedNewsTags } from "@/lib/news";
import { formatThaiDate, isBreaking } from "@/lib/news-format";

export const dynamic = "force-dynamic";

/** P26 /news: PageHead + simple list rows + empty state. Newest first; a story published in the
 *  last 24 hours carries the BREAKING badge. Not in the top nav (MERGE_DECISIONS); footer only. */
export default async function NewsPage({ searchParams }: { searchParams: Promise<{ tag?: string }> }) {
  const { tag } = await searchParams;
  const [news, tags] = await Promise.all([getPublishedNews({ tagSlug: tag || undefined }), getUsedNewsTags()]);
  const now = Date.now();

  return (
    <div className="tdr-wrap tdr-news">
      <PageHead eyebrow="NEWS" eyebrowLang="en" title="ข่าว" />

      {tags.length ? (
        <nav className="tdr-news__filters" aria-label="กรองตามแท็ก">
          <Chip href="/news" aria-current={!tag ? "true" : undefined}>ทั้งหมด</Chip>
          {tags.map((t) => (
            <Chip key={t.id} href={`/news?tag=${encodeURIComponent(t.slug)}`} aria-current={tag === t.slug ? "true" : undefined}>{t.name}</Chip>
          ))}
        </nav>
      ) : null}

      {news.length ? (
        <div className="tdr-news__list">
          {news.map((a) => (
            <article key={a.id} className="tdr-news__item">
              {a.heroImageUrl ? (
                <Link href={`/news/${a.slug}`} className="tdr-news__thumb" tabIndex={-1} aria-hidden="true">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={a.heroImageUrl} alt="" loading="lazy" />
                </Link>
              ) : null}
              <div>
                <div className="tdr-news__meta">
                  {isBreaking(a.publishedAt, now) ? <BreakingBadge /> : null}
                  <time dateTime={a.publishedAt}>{formatThaiDate(a.publishedAt)}</time>
                </div>
                <h2 className="tdr-news__title"><Link href={`/news/${a.slug}`}>{a.title}</Link></h2>
                {a.summary ? <p className="tdr-news__summary">{a.summary}</p> : null}
                {a.tags.length ? (
                  <div className="tdr-news__tags">
                    {a.tags.map((t) => <Chip key={t.id} href={`/news?tag=${encodeURIComponent(t.slug)}`}>{t.name}</Chip>)}
                  </div>
                ) : null}
              </div>
            </article>
          ))}
        </div>
      ) : (
        <Card tone="dashed">
          <b className="tdr-card__title">{tag ? "ยังไม่มีข่าวในแท็กนี้" : "ยังไม่มีข่าวเผยแพร่"}</b>
        </Card>
      )}
    </div>
  );
}
