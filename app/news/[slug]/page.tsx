import Link from "next/link";
import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { BreakingBadge } from "@/components/NewsBadge";
import { getPublishedNewsBySlug } from "@/lib/news";
import { isBreaking, splitParagraphs } from "@/lib/news-format";

export const dynamic = "force-dynamic";

const dateTimeTh = (iso: string) => new Intl.DateTimeFormat("th-TH", { dateStyle: "long", timeStyle: "short", timeZone: "Asia/Bangkok" }).format(new Date(iso));

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const a = await getPublishedNewsBySlug(slug);
  return a ? { title: a.title, description: a.summary || undefined } : {};
}

export default async function NewsArticlePage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const a = await getPublishedNewsBySlug(slug);
  if (!a) notFound();

  return <article className="newsArticle">
    <nav className="sfCrumbs" aria-label="เส้นทาง">
      <Link href="/news">ข่าว</Link>
      <span aria-hidden="true">/</span>
      <b>{a.title}</b>
    </nav>

    <header className="newsArticleHead">
      <div className="newsMeta">
        {isBreaking(a.publishedAt) ? <BreakingBadge /> : null}
        <time dateTime={a.publishedAt}>{dateTimeTh(a.publishedAt)}</time>
      </div>
      <h1>{a.title}</h1>
      {a.summary ? <p className="newsLead">{a.summary}</p> : null}
      {a.tags.length ? <div className="newsTags">{a.tags.map((t) => <Link key={t.id} href={`/news?tag=${encodeURIComponent(t.slug)}`}>#{t.name}</Link>)}</div> : null}
    </header>

    {a.heroImageUrl ? <figure className="newsHero">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={a.heroImageUrl} alt={a.heroImageAlt || a.title} />
    </figure> : null}

    <div className="newsBody">
      {splitParagraphs(a.body).map((p, i) => <p key={i}>{p}</p>)}
    </div>

    {a.related.length || a.externalLinks.length ? <aside className="newsReadMore" aria-label="แนะนำให้อ่านต่อ">
      <h2>แนะนำให้อ่านต่อ</h2>
      <ul>
        {a.related.map((r) => <li key={r.id}>
          <Link href={`/news/${r.slug}`}>{r.title}</Link>
          <time dateTime={r.publishedAt}>{dateTimeTh(r.publishedAt)}</time>
        </li>)}
        {a.externalLinks.map((l) => <li key={l.url}>
          <a href={l.url} target="_blank" rel="noreferrer noopener">{l.title} ↗</a>
        </li>)}
      </ul>
    </aside> : null}
  </article>;
}
