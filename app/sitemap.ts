import type { MetadataRoute } from "next";
import { getPublishedNewsEvents, newsEventHref } from "@/lib/news";
import { absoluteUrl } from "@/lib/site-url";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const events = await getPublishedNewsEvents(5000);
  return [
    {
      url: absoluteUrl("/news"),
      lastModified: events[0]?.event_date || new Date().toISOString(),
      changeFrequency: "daily",
      priority: 0.8,
    },
    ...events.map((event) => ({
      url: absoluteUrl(newsEventHref(event.id)),
      lastModified: event.event_date,
      changeFrequency: "monthly" as const,
      priority: 0.7,
    })),
  ];
}
