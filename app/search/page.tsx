import { Suspense } from "react";
import { Button, Chip, PageHead, Skeleton, TextInput } from "@/components/design";
import { BodyTypeTile } from "@/components/models/BodyTypeTile";
import { ModelCard } from "@/components/models/ModelCard";
import { BlockEmpty, BlockError } from "@/components/models/states";
import { getCanonicalModels, searchCanonicalCatalog } from "@/lib/canonical-data";
import { UpcomingCards } from "@/components/upcoming/UpcomingCards";
import { UPCOMING_CARD_MAX, safeUpcoming, upcomingSource } from "@/lib/upcoming/boundary";
import { isCurrentLifecycleStatus } from "@/lib/canonical-trim-status";
import { BODY_FAMILIES, familyParam } from "@/lib/body-families";
import { displayName } from "@/lib/display-name";
import { formatNumber } from "@/lib/design/format";
import { normalizeQuery, popularBrands } from "@/lib/search/catalog";

function SearchForm({ q }: { q: string }) {
  return (
    <form className="tdr-search-form" action="/search" method="get" role="search">
      <TextInput type="search" name="q" defaultValue={q} placeholder="เช่น Hilux, BYD…" aria-label="คำค้น" autoComplete="off" />
      <Button type="submit" variant="secondary">ค้นหา</Button>
    </form>
  );
}

/** Nothing typed, or nothing found: popular brands as text chips and the six body families as tiles. */
function Suggestions({ models }: { models: any[] }) {
  const brands = popularBrands(models, 8);
  return (
    <div className="tdr-search-suggest">
      {brands.length ? (
        <>
          <h2>แบรนด์</h2>
          <div className="tdr-chips">{brands.map((b) => <Chip key={b.slug} href={`/brands/${b.slug}`} count={b.count}>{b.name}</Chip>)}</div>
        </>
      ) : null}
      <h2>ประเภทตัวถัง</h2>
      <nav className="tdr-models-tiles" aria-label="ประเภทตัวถัง">
        {BODY_FAMILIES.map((f) => (
          <BodyTypeTile key={f.key} icon={f.icon} label={f.label} href={`/models?body=${encodeURIComponent(familyParam(f))}`}
            count={models.filter((m) => !!m.body_type && f.values.includes(m.body_type)).length} />
        ))}
      </nav>
    </div>
  );
}

function SearchSkeleton() {
  return (
    <div className="tdr-search-sk" aria-busy="true">
      <Skeleton height={28} width={160} />
      <div className="tdr-models-grid">{Array.from({ length: 6 }, (_, i) => <Skeleton key={i} height={300} />)}</div>
    </div>
  );
}

/** The current models for the empty-state suggestions (popular brands, body-family counts). */
async function currentModels(): Promise<any[]> {
  const all = (await getCanonicalModels(600)) as any[];
  return all.filter((r) => isCurrentLifecycleStatus(r.status));
}

async function Results({ q }: { q: string }) {
  if (!q) {
    try { return <Suggestions models={await currentModels()} />; } catch { return <BlockError title="ค้นหา" retryHref="/search" />; }
  }
  let found: { models: any[]; brands: any[] };
  try {
    found = await searchCanonicalCatalog(q);
  } catch {
    return <BlockError title="ผลการค้นหา" retryHref={`/search?q=${encodeURIComponent(q)}`} />;
  }
  // "กำลังมา": PR 12 owns the source; through the boundary it is no rows (group omitted) until then. A failure there omits only that group.
  const upcoming = await safeUpcoming(() => upcomingSource.matching(q, UPCOMING_CARD_MAX));

  if (!found.models.length && !found.brands.length && !upcoming.length) {
    let suggestions: React.ReactNode = null;
    try { suggestions = <Suggestions models={await currentModels()} />; } catch { /* the empty message still stands */ }
    return (
      <>
        <BlockEmpty title={`ไม่พบ “${q}” ในฐานข้อมูล`} text="ลองพิมพ์ชื่อรุ่นหรือชื่อแบรนด์เป็นภาษาไทยหรืออังกฤษ" />
        {suggestions}
      </>
    );
  }
  return (
    <>
      {found.models.length ? (
        <section className="tdr-search-group" aria-labelledby="search-models">
          <h2 id="search-models">รุ่น <span className="tdr-models-mono">{formatNumber(found.models.length)}</span></h2>
          <div className="tdr-models-grid">{found.models.map((m: any) => <ModelCard key={m.id} r={m} />)}</div>
        </section>
      ) : null}
      {found.brands.length ? (
        <section className="tdr-search-group" aria-labelledby="search-brands">
          <h2 id="search-brands">แบรนด์ <span className="tdr-models-mono">{formatNumber(found.brands.length)}</span></h2>
          <div className="tdr-chips">{found.brands.map((b: any) => <Chip key={b.slug} href={`/brands/${b.slug}`}>{displayName(b)}</Chip>)}</div>
        </section>
      ) : null}
      <UpcomingCards title="กำลังมา" rows={upcoming} headingId="search-upcoming" />
    </>
  );
}

export const metadata = { title: "ค้นหา · Vehicle Database" };

export default async function SearchPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const raw = (await searchParams).q;
  const q = normalizeQuery(Array.isArray(raw) ? raw[0] : raw);
  return (
    <div className="tdr-wrap">
      <PageHead eyebrow="ค้นหา" title={q ? `ผลการค้นหา "${q}"` : "ค้นหาฐานข้อมูล"} lead={q ? undefined : "พิมพ์คำค้นเพื่อเริ่มค้นฐานข้อมูล"} />
      <SearchForm q={q} />
      <Suspense key={q} fallback={<SearchSkeleton />}><Results q={q} /></Suspense>
    </div>
  );
}
