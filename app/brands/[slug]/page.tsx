import { Suspense } from "react";
import { notFound } from "next/navigation";
import { KpiCard, PageHead } from "@/components/design";
import { ListSkeleton } from "@/components/models/ListSkeleton";
import { ModelsExplorer, type ExplorerModel } from "@/components/models/ModelsExplorer";
import { UpcomingCards } from "@/components/upcoming/UpcomingCards";
import { BlockEmpty, BlockError } from "@/components/models/states";
import { getCanonicalBrand, getCanonicalModelsByBrand, getCurrentTrimCountsByModel } from "@/lib/canonical-data";
import { isCurrentLifecycleStatus } from "@/lib/canonical-trim-status";
import { displayName } from "@/lib/display-name";
import { brandKpis } from "@/lib/brands";
import { bahtRangeText, normalizeParams, type ModelsParams } from "@/lib/models/list";
import { UPCOMING_CARD_MAX, safeUpcoming, upcomingSource } from "@/lib/upcoming/boundary";

/** Brand page (P06). The model grid is the same explorer as /models (same URL params, brand fixed as a preset), so
 *  filters, sort and the 12-at-a-time load behave identically; its body-family tiles open `/models?brand=<slug>&body=<values>`.
 *  No news block. The "กำลังมา" strip (up to 3 upcoming cars of this brand) goes through the Upcoming boundary
 *  (lib/upcoming/boundary.ts): PR 12 owns the source, and while it is absent the strip is omitted. */
async function BrandBody({ slug, brand, sp }: { slug: string; brand: any; sp: ModelsParams }) {
  const name = displayName(brand);

  let models: ExplorerModel[], trimCounts: Map<string, number>;
  try {
    const [rows, counts] = await Promise.all([getCanonicalModelsByBrand(brand.id), getCurrentTrimCountsByModel()]);
    models = (rows as ExplorerModel[]).filter((m) => isCurrentLifecycleStatus(m.status));
    trimCounts = counts;
  } catch {
    return <div className="tdr-wrap">
      <PageHead eyebrow={brand.country_origin || "แบรนด์"} title={name} />
      <BlockError title={`รถของ ${name}`} retryHref={`/brands/${slug}`} />
    </div>;
  }

  const upcoming = await safeUpcoming(() => upcomingSource.forBrand({ slug: brand.slug, canonicalId: brand.canonical_id, name }, UPCOMING_CARD_MAX));
  const kpi = brandKpis(models, trimCounts);
  const range = bahtRangeText(kpi.min, kpi.max);

  return <div className="tdr-wrap">
    <PageHead
      eyebrow={brand.country_origin || "แบรนด์"}
      title={name}
      lead={brand.notes || "รุ่นปัจจุบันที่จำหน่ายอย่างเป็นทางการในประเทศไทย"}
    />
    <div className="tdr-brands-kpis">
      <KpiCard label="รุ่นที่จำหน่าย" value={kpi.models} />
      <KpiCard label="รุ่นย่อย" value={kpi.trims} />
      <KpiCard label="ช่วงราคา" value={range || "ยังไม่ประกาศราคา"} />
    </div>
    {models.length ? (
      <ModelsExplorer sp={sp} current={models} brands={[]} trimCounts={trimCounts} brandCount={0} basePath={`/brands/${slug}`} fixedBrand={{ slug: brand.slug, name }} tilesToCatalogue />
    ) : (
      <BlockEmpty title="ยังไม่มีรถของแบรนด์นี้" text={`ยังไม่มีรุ่นที่ยังจำหน่ายของ ${name} ในฐานข้อมูล`} />
    )}
    <UpcomingCards title="กำลังมา" rows={upcoming} headingId="brand-upcoming" />
  </div>;
}

export default async function BrandPage({ params, searchParams }: {
  params: Promise<{ slug: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { slug } = await params;
  const sp = normalizeParams(await searchParams);
  delete sp.brand; // the brand is the page itself, never a filter on it
  // Looked up before the Suspense boundary so an unknown brand is a real 404, not a 200 with a not-found body.
  const brand: any = await getCanonicalBrand(slug);
  if (!brand) notFound();
  return <Suspense key={`${slug}?${JSON.stringify(sp)}`} fallback={<ListSkeleton />}><BrandBody slug={slug} brand={brand} sp={sp} /></Suspense>;
}
