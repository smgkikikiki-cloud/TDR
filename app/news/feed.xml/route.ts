import { getPublishedNewsEvents, newsEventHref } from "@/lib/news";
import { absoluteUrl } from "@/lib/site-url";

function xml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

export async function GET() {
  const events = await getPublishedNewsEvents(100);
  const items = events.map((event) => {
    const link = absoluteUrl(newsEventHref(event.id));
    const description = event.summary_th || event.title_th;
    return `<item><title>${xml(event.title_th)}</title><link>${xml(link)}</link><guid isPermaLink="true">${xml(link)}</guid><pubDate>${new Date(`${event.event_date}T00:00:00+07:00`).toUTCString()}</pubDate><category>${xml(event.event_type)}</category><description>${xml(description)}</description></item>`;
  }).join("");

  const body = `<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>TDR Automotive Intelligence - ข่าวอุตสาหกรรมยานยนต์ไทย</title><link>${xml(absoluteUrl("/news"))}</link><description>ข่าว การลงทุน การผลิต การเปิดตัวรถ โรงงาน ซัพพลายเออร์ และการส่งออกในอุตสาหกรรมยานยนต์ไทย</description><language>th-TH</language>${items}</channel></rss>`;

  return new Response(body, {
    headers: {
      "Content-Type": "application/rss+xml; charset=utf-8",
      "Cache-Control": "public, s-maxage=900, stale-while-revalidate=3600",
    },
  });
}
