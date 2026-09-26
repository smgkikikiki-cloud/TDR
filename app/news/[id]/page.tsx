import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getPublishedNewsEvent, newsEventHref } from "@/lib/news";
import { absoluteUrl } from "@/lib/site-url";

export const dynamic = "force-dynamic";

function descriptionFor(summary: string | null, title: string): string {
  const value = (summary || title).replace(/\s+/g, " ").trim();
  return value.length > 180 ? `${value.slice(0, 177)}…` : value;
}

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  const event = await getPublishedNewsEvent(id);
  if (!event) return { title: "ไม่พบข่าว | TDR" };
  const canonical = absoluteUrl(newsEventHref(event.id));
  const description = descriptionFor(event.summary_th, event.title_th);
  return {
    title: `${event.title_th} | TDR Automotive Intelligence`,
    description,
    alternates: { canonical },
    openGraph: {
      type: "article",
      title: event.title_th,
      description,
      url: canonical,
      publishedTime: event.event_date,
    },
    twitter: { card: "summary", title: event.title_th, description },
  };
}

export default async function NewsEventPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const event = await getPublishedNewsEvent(id);
  if (!event) notFound();

  const canonical = absoluteUrl(newsEventHref(event.id));
  const description = descriptionFor(event.summary_th, event.title_th);
  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "NewsArticle",
    headline: event.title_th,
    description,
    datePublished: event.event_date,
    dateModified: event.event_date,
    mainEntityOfPage: canonical,
    isAccessibleForFree: true,
    publisher: { "@type": "Organization", name: "Thailand Development Report (TDR)" },
  };

  return <div className="researchPage">
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd).replace(/</g, "\\u003c") }}
    />

    <nav className="sfCrumbs" aria-label="เส้นทาง">
      <Link href="/news">ข่าวอุตสาหกรรมยานยนต์ไทย</Link>
      <span aria-hidden="true">/</span>
      <b>{event.title_th}</b>
    </nav>

    <article className="researchHero">
      <div className="sfEyebrow">{event.event_type.toUpperCase()}</div>
      <h1>{event.title_th}</h1>
      <div className="researchMeta">
        <time dateTime={event.event_date}>{event.event_date}</time>
        {event.source_name ? <span>{event.source_name}</span> : null}
      </div>
      {event.summary_th ? <p className="researchSummary">{event.summary_th}</p> : null}
      {event.source_url ? <p><a href={event.source_url} target="_blank" rel="noreferrer nofollow">เปิดแหล่งข้อมูลต้นฉบับ ↗</a></p> : null}
    </article>

    <div className="eventStream">
      <div className="publicEmptyCard">
        <strong>TDR Event Record</strong>
        <p>รายการนี้เป็นอัปเดตข่าวที่เชื่อมเข้ากับฐานข้อมูลอุตสาหกรรมยานยนต์ของ TDR และจะถูกปรับปรุงเมื่อมีข้อมูลที่ยืนยันได้เพิ่มเติม</p>
        <Link href="/news">← กลับไปหน้าข่าวทั้งหมด</Link>
      </div>
    </div>
  </div>;
}
