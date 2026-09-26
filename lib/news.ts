import { publicDb } from "@/lib/supabase";

export type PublishedNewsEvent = {
  id: string;
  title_th: string;
  title_en: string | null;
  event_date: string;
  event_type: string;
  summary_th: string | null;
  source_name: string | null;
  source_url: string | null;
  related_brand_id: string | null;
  related_model_id: string | null;
  related_plant_id: string | null;
  related_company_id: string | null;
};

const NEWS_COLUMNS = [
  "id",
  "title_th",
  "title_en",
  "event_date",
  "event_type",
  "summary_th",
  "source_name",
  "source_url",
  "related_brand_id",
  "related_model_id",
  "related_plant_id",
  "related_company_id",
].join(",");

export async function getPublishedNewsEvents(limit = 100): Promise<PublishedNewsEvent[]> {
  const db = publicDb();
  if (!db) return [];
  const { data, error } = await db
    .from("events")
    .select(NEWS_COLUMNS)
    .eq("published", true)
    .order("event_date", { ascending: false })
    .limit(limit);
  if (error) throw error;
  return (data || []) as PublishedNewsEvent[];
}

export async function getPublishedNewsEvent(id: string): Promise<PublishedNewsEvent | null> {
  const db = publicDb();
  if (!db || !id) return null;
  const { data, error } = await db
    .from("events")
    .select(NEWS_COLUMNS)
    .eq("id", id)
    .eq("published", true)
    .maybeSingle();
  if (error) throw error;
  return (data as PublishedNewsEvent | null) ?? null;
}

export function newsEventHref(id: string): string {
  return `/news/${encodeURIComponent(id)}`;
}
