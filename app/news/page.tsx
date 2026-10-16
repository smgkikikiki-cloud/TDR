import Link from "next/link";
import { BreakingBadge } from "@/components/NewsBadge";
import { getPublishedNews, getUsedNewsTags } from "@/lib/news";
import { isBreaking } from "@/lib/news-format";

export const dynamic = "force-dynamic";

const dateTh = (iso: string) => new Intl.DateTimeFormat("th-TH", { dateStyle: "long", timeZone: "Asia/Bangkok" }).format(new Date(iso));

/** Newest first, top to bottom. An article published in the last 24 hours blinks red. */
export default async function NewsPage({ searchParams }: { searchParams: Promise<{ tag?: string }> }) {
  const { tag } = await searchParams;
  const [news, tags] = await Promise.all([getPublishedNews({ tagSlug: tag || undefined }), getUsedNewsTags()]);
  const now = Date.now();

  return <section className="sfBlock">
    <div className="sfZoneHead">
      <div>
        <div className="sfEyebrow">NEWS</div>
        <h1>ข่าว</h1>
      </div>
      <span>{news.length} ข่าว</span>
    </div>

    {tags.length ? <div className="newsTagRow" aria-label="กรองตามแท็ก">
      <Link href="/news" className={!tag ? "on" : undefined}>ทั้งหมด</Link>
      {tags.map((t) => <Link key={t.id} href={`/news?tag=${encodeURIComponent(t.slug)}`} className={tag === t.slug ? "on" : undefined}>{t.name}</Link>)}
    </div> : null}

    {news.length ? <div className="newsList">
      {news.map((a) => <article key={a.id} className="newsItem">
        {a.heroImageUrl ? <Link href={`/news/${a.slug}`} className="newsThumb" tabIndex={-1} aria-hidden="true">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={a.heroImageUrl} alt="" loading="lazy" />
        </Link> : null}
        <div className="newsItemBody">
          <div className="newsMeta">
            {isBreaking(a.publishedAt, now) ? <BreakingBadge /> : null}
            <time dateTime={a.publishedAt}>{dateTh(a.publishedAt)}</time>
          </div>
          <Link href={`/news/${a.slug}`}><h2>{a.title}</h2></Link>
          {a.summary ? <p>{a.summary}</p> : null}
          {a.tags.length ? <div className="newsTags">{a.tags.map((t) => <Link key={t.id} href={`/news?tag=${encodeURIComponent(t.slug)}`}>#{t.name}</Link>)}</div> : null}
        </div>
      </article>)}
    </div> : <div className="sfEmpty"><b>{tag ? "ไม่มีข่าวในแท็กนี้" : "ยังไม่มีข่าวเผยแพร่"}</b></div>}
  </section>;
}
