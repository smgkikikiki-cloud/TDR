import type { Metadata } from "next";
import Link from "next/link";
import { PageIntro } from "@/components/PageIntro";
import { absoluteUrl } from "@/lib/site-url";
import { getPublishedNewsEvents, newsEventHref } from "@/lib/news";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "ข่าวอุตสาหกรรมยานยนต์ไทย | TDR Automotive Intelligence",
  description: "อัปเดตการลงทุน การเปิดตัวรถ การผลิต โรงงาน ซัพพลายเออร์ การส่งออก และความเคลื่อนไหวสำคัญของอุตสาหกรรมยานยนต์ไทยจาก TDR",
  alternates: {
    canonical: absoluteUrl("/news"),
    types: { "application/rss+xml": absoluteUrl("/news/feed.xml") },
  },
  openGraph: {
    type: "website",
    title: "ข่าวอุตสาหกรรมยานยนต์ไทย | TDR",
    description: "อัปเดตเหตุการณ์สำคัญในอุตสาหกรรมยานยนต์ไทย พร้อมเชื่อมโยงกับฐานข้อมูล TDR",
    url: absoluteUrl("/news"),
  },
};

export default async function News() {
  const rows = await getPublishedNewsEvents(100);
  return <>
    <PageIntro
      eyebrow="TDR NEWSWIRE"
      title="ข่าวอุตสาหกรรมยานยนต์ไทย"
      description="อัปเดตการลงทุน การผลิต การเปิดตัวรถ โรงงาน ซัพพลายเออร์ การส่งออก และความเคลื่อนไหวที่เชื่อมกลับไปยังฐานข้อมูล TDR"
    />
    <div className="eventStream">
      {rows.length ? rows.map((event) => {
        const href = newsEventHref(event.id);
        return <article key={event.id} className="eventRow">
          <time dateTime={event.event_date}>{event.event_date}</time>
          <div>
            <small>{event.event_type.toUpperCase()}</small>
            <h2><Link href={href}>{event.title_th}</Link></h2>
            {event.summary_th ? <p>{event.summary_th}</p> : null}
            <p>
              <Link href={href}>อ่านอัปเดต →</Link>
              {event.source_url ? <>{" · "}<a href={event.source_url} target="_blank" rel="noreferrer nofollow">{event.source_name || "แหล่งข้อมูล"} ↗</a></> : null}
            </p>
          </div>
        </article>;
      }) : <div className="publicEmptyCard">ยังไม่มี Event ที่เผยแพร่</div>}
    </div>
  </>;
}
