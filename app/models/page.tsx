import { Suspense } from "react";
import Link from "next/link";
import { Button, Chip, KpiCard, PageHead, TextInput } from "@/components/design";
import { BodyTypeTile } from "@/components/models/BodyTypeTile";
import { ListSkeleton } from "@/components/models/ListSkeleton";
import { FilterRail } from "@/components/models/FilterRail";
import { ModelCard } from "@/components/models/ModelCard";
import { SortSelect } from "@/components/models/SortSelect";
import { BlockEmpty, BlockError } from "@/components/models/states";
import { getCanonicalBrands, getCanonicalModels, getCurrentTrimCountsByModel } from "@/lib/canonical-data";
import { BODY_LABEL } from "@/lib/body-labels";
import {
  BODY_FAMILIES, bodyParam, familyForSelection, familyParam, parseBodyParam, toggleBodyValue,
} from "@/lib/body-families";
import { isCurrentLifecycleStatus } from "@/lib/canonical-trim-status";
import { displayName } from "@/lib/display-name";
import { formatNumber } from "@/lib/design/format";
import {
  POWERTRAIN_OPTION_LABEL, PRODUCTION_LABEL, facetHit, matchesFilters, modelsHref, normalizeParams, pageWindow,
  parsePage, parseSort, sortModels, visibleOption, type FilterKey, type ModelListRow, type ModelsParams,
} from "@/lib/models/list";

export const metadata = { title: "Vehicle Database · รถที่จำหน่ายในประเทศไทย" };

type Opt = { value: string; label: string };
const opts = (values: string[], labels: Record<string, string> = {}): Opt[] => values.map((v) => ({ value: v, label: labels[v] || v }));

/** Individual body values for the rail (a family chip above sets several at once; these tick one at a time). */
const BODY_OPTIONS: Opt[] = [...BODY_FAMILIES.flatMap((f) => f.values), "TRUCK"]
  .map((v) => ({ value: v, label: BODY_LABEL[v] || v }));

const FACETS: { key: Exclude<FilterKey, "brand">; label: string; note?: string; options: Opt[] }[] = [
  { key: "body", label: "ประเภทตัวถัง", options: BODY_OPTIONS },
  { key: "powertrain", label: "ระบบขับเคลื่อน", options: opts(["ICE", "BEV", "HEV", "PHEV", "REEV"], POWERTRAIN_OPTION_LABEL) },
  { key: "segment", label: "ขนาดรถ (เก๋ง / SUV)", note: "สเกล A–E ใช้กับรถนั่ง กระบะและรถตู้ไม่มีค่านี้", options: opts(["A", "B", "C", "D", "E"]) },
  { key: "position", label: "ตำแหน่งตลาด", options: opts(["Mass", "Premium", "Luxury"]) },
  { key: "production", label: "แหล่งผลิต", options: opts(["CKD", "SKD", "CBU"], PRODUCTION_LABEL) },
];
const FILTER_LABEL: Record<FilterKey, string> = { brand: "แบรนด์", body: "ตัวถัง", powertrain: "ขับเคลื่อน", segment: "ขนาดรถ", position: "ตำแหน่ง", production: "แหล่งผลิต" };
const BRAND_RAIL_LIMIT = 10;

function Head({ lead, aside }: { lead?: string; aside?: React.ReactNode }) {
  return (
    <PageHead
      eyebrow="Vehicle Database"
      eyebrowLang="en"
      title={<>รถที่จำหน่ายใน<span className="tdr-models-hl">ประเทศไทย</span></>}
      lead={lead}
      aside={aside}
    />
  );
}

function SearchBox() {
  return (
    <form className="tdr-models-search" action="/search" method="get" role="search">
      <TextInput type="search" name="q" placeholder="ค้นหารุ่นรถหรือแบรนด์" aria-label="ค้นหารุ่นรถหรือแบรนด์" />
      <Button type="submit" variant="secondary">ค้นหา</Button>
    </form>
  );
}

function Tabs({ sp, tab }: { sp: ModelsParams; tab: "sold" | "upcoming" }) {
  return (
    <nav className="tdr-models-tabs" aria-label="สถานะรุ่น">
      <Link prefetch={false} href={modelsHref({ sort: sp.sort }, {})} aria-current={tab === "sold" ? "page" : undefined}>ขายแล้ว</Link>
      <Link prefetch={false} href="/models?tab=upcoming" aria-current={tab === "upcoming" ? "page" : undefined}>กำลังมา</Link>
    </nav>
  );
}

export default async function ModelsPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = normalizeParams(await searchParams);
  if (sp.tab === "upcoming") return <UpcomingTab sp={sp} />;
  return <Suspense key={JSON.stringify(sp)} fallback={<ListSkeleton />}><SoldTab sp={sp} /></Suspense>;
}

function UpcomingTab({ sp }: { sp: ModelsParams }) {
  const tab = "upcoming" as const;
  // PR 12 (Upcoming, P16) owns this tab's data. Until it lands there is no query, no card and no count here:
  // only the integration point, an honest empty state.
  return <div className="tdr-wrap">
    <Head aside={<SearchBox />} />
    <Tabs sp={sp} tab={tab} />
    <div data-upcoming-owner="PR-12">
      <BlockEmpty title="กำลังมา" text="ยังไม่มีข้อมูลรถที่กำลังมา" />
    </div>
  </div>;
}

async function SoldTab({ sp }: { sp: ModelsParams }) {
  const tab = "sold" as const;

  let all: any[], brands: any[], trimCounts: Map<string, number>;
  try {
    [brands, all, trimCounts] = await Promise.all([getCanonicalBrands(150), getCanonicalModels(600), getCurrentTrimCountsByModel()]);
  } catch {
    return <div className="tdr-wrap">
      <Head aside={<SearchBox />} />
      <Tabs sp={sp} tab={tab} />
      <BlockError title="ฐานข้อมูลรถยนต์" retryHref={modelsHref(sp, {})} />
    </div>;
  }

  const current = (all as (ModelListRow & { status?: unknown; id: string })[]).filter((r) => isCurrentLifecycleStatus(r.status));
  const sort = parseSort(sp.sort);
  const page = parsePage(sp.page);
  const selectedBody = parseBodyParam(sp.body);
  const filtered = sortModels(current.filter((r) => matchesFilters(r, sp)), sort);
  const win = pageWindow(filtered, page);

  const brandCount = new Set(current.map((r) => r.brands?.slug).filter(Boolean)).size;
  const trimTotal = current.reduce((n, r) => n + (trimCounts.get(r.id) || 0), 0);
  const assembled = current.filter((r) => r.production_type === "CKD" || r.production_type === "SKD").length;
  const imported = current.filter((r) => r.production_type === "CBU").length;
  const activeBrand = (brands as any[]).find((b) => b.slug === sp.brand);
  const bodyPool = current.filter((r) => matchesFilters(r, sp, "body"));
  const activeFamily = familyForSelection(selectedBody);

  const activeChips: { key: FilterKey; label: string; href: string }[] = [];
  for (const key of ["body", "powertrain", "segment", "position", "production", "brand"] as FilterKey[]) {
    const raw = sp[key];
    if (!raw) continue;
    let label = raw;
    if (key === "body") label = activeFamily?.label || selectedBody.map((v) => BODY_LABEL[v] || v).join(" + ");
    else if (key === "brand") label = displayName(activeBrand, raw);
    else if (key === "powertrain") label = POWERTRAIN_OPTION_LABEL[raw] || raw;
    else if (key === "production") label = PRODUCTION_LABEL[raw] || raw;
    activeChips.push({ key, label, href: modelsHref(sp, { [key]: null }) });
  }

  // Brand options for the rail: the biggest brands under the other filters, plus the active one so it can be undone.
  const brandPool = current.filter((r) => matchesFilters(r, sp, "brand"));
  const perBrand = new Map<string, number>();
  for (const r of brandPool) if (r.brands?.slug) perBrand.set(r.brands.slug, (perBrand.get(r.brands.slug) || 0) + 1);
  const brandOptions = [...perBrand.entries()]
    .map(([slug, count]) => ({ slug, count, name: displayName((brands as any[]).find((b) => b.slug === slug) || { slug }) }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, "en"));
  const shownBrands = brandOptions.slice(0, BRAND_RAIL_LIMIT);
  if (sp.brand && !shownBrands.some((b) => b.slug === sp.brand)) shownBrands.push({ slug: sp.brand, count: perBrand.get(sp.brand) || 0, name: displayName(activeBrand, sp.brand) });

  const sortParams: Record<string, string> = {};
  for (const [k, v] of Object.entries(sp)) if (v && k !== "sort" && k !== "page") sortParams[k] = v;

  const lead = `รวมรถ ${formatNumber(current.length)} รุ่นที่ขายในไทยวันนี้ ครบทุกรุ่นย่อย สเปก และราคา อัปเดตต่อเนื่องทุกครั้งที่มีรุ่นใหม่หรือปรับราคา`;
  const facetBlocks = FACETS.map((f) => {
    const pool = current.filter((r) => matchesFilters(r, sp, f.key));
    const options = f.options
      .map((opt) => {
        const on = f.key === "body" ? selectedBody.includes(opt.value) : sp[f.key] === opt.value;
        const count = pool.filter((r) => facetHit(r, f.key, opt.value)).length;
        const href = f.key === "body"
          ? modelsHref(sp, { body: bodyParam(toggleBodyValue(selectedBody, opt.value)) })
          : modelsHref(sp, { [f.key]: on ? null : opt.value });
        return { ...opt, on, count, href };
      })
      .filter((o) => visibleOption(o.count, o.on));
    return { f, options };
  }).filter((b) => b.options.length > 0);

  return <div className="tdr-wrap">
    <Head lead={lead} aside={<SearchBox />} />

    <div className="tdr-models-kpis">
      <KpiCard label="รุ่นที่ยังจำหน่าย" value={current.length} />
      <KpiCard label="รุ่นย่อย" value={trimTotal} />
      <KpiCard label="แบรนด์" value={brandCount} />
      <KpiCard label="ประกอบในไทย (CKD/SKD)" value={assembled} />
      <KpiCard label="นำเข้าทั้งคัน (CBU)" value={imported} />
    </div>
    <p className="tdr-models-note">นับจากรุ่นที่ยังจำหน่ายอยู่ในฐานข้อมูล TDR รุ่นที่เลิกจำหน่ายแล้วไม่ถูกนับ</p>

    <Tabs sp={sp} tab={tab} />

    <nav className="tdr-models-tiles" aria-label="ประเภทตัวถัง">
      <BodyTypeTile href={modelsHref(sp, { body: null })} label="ทั้งหมด" count={bodyPool.length} on={selectedBody.length === 0} />
      {BODY_FAMILIES.map((family) => {
        const on = activeFamily?.key === family.key;
        return (
          <BodyTypeTile key={family.key} icon={family.icon} label={family.label} on={on}
            count={bodyPool.filter((r) => !!r.body_type && family.values.includes(r.body_type)).length}
            href={modelsHref(sp, { body: on ? null : familyParam(family) })} />
        );
      })}
    </nav>

    <div className="tdr-models-layout">
      <FilterRail label={`ตัวกรอง${activeChips.length ? ` · ${activeChips.length}` : ""}`} resultLabel={`ดูผลลัพธ์ ${formatNumber(filtered.length)} รุ่น`}>
        <div className="tdr-models-rail__head">
          <b>กรองรุ่นรถ</b>
          {activeChips.length ? <Link prefetch={false} href={modelsHref({ sort: sp.sort }, {})}>ล้างทั้งหมด</Link> : null}
        </div>
        {facetBlocks.map(({ f, options }) => (
          <div className="tdr-models-fg" key={f.key}>
            <h3>{f.label}</h3>
            {f.note ? <p className="tdr-models-fg__note">{f.note}</p> : null}
            {options.map((o) => (
              <Link key={o.value} prefetch={false} href={o.href} className={o.on ? "tdr-models-fo tdr-models-fo--on" : "tdr-models-fo"} aria-current={o.on ? "true" : undefined}>
                <i aria-hidden="true">{o.on ? "✓" : ""}</i><span>{o.label}</span><em>{formatNumber(o.count)}</em>
              </Link>
            ))}
          </div>
        ))}
        <div className="tdr-models-fg">
          <h3>แบรนด์</h3>
          {shownBrands.map((b) => {
            const on = sp.brand === b.slug;
            return (
              <Link key={b.slug} prefetch={false} href={modelsHref(sp, { brand: on ? null : b.slug })} className={on ? "tdr-models-fo tdr-models-fo--on" : "tdr-models-fo"} aria-current={on ? "true" : undefined}>
                <i aria-hidden="true">{on ? "✓" : ""}</i><span>{b.name}</span><em>{formatNumber(b.count)}</em>
              </Link>
            );
          })}
          <Link className="tdr-models-more" href="/brands">ดูทั้ง {formatNumber(brandCount)} แบรนด์ →</Link>
        </div>
      </FilterRail>

      <div className="tdr-models-results">
        <div className="tdr-models-rbar">
          <h2>{activeBrand ? displayName(activeBrand) : "รถทั้งหมด"} <span className="tdr-models-mono">{formatNumber(filtered.length)} รุ่น</span></h2>
          <SortSelect value={sort} params={sortParams} />
        </div>

        {activeChips.length ? (
          <div className="tdr-chips tdr-models-active">
            {activeChips.map((c) => (
              <Chip key={c.key} prefetch={false} href={c.href} className="tdr-chip--on" aria-label={`เอาตัวกรอง ${FILTER_LABEL[c.key]} ${c.label} ออก`}>
                {FILTER_LABEL[c.key]} · {c.label} <span className="tdr-chip__x" aria-hidden="true">✕</span>
              </Chip>
            ))}
            <Link className="tdr-models-clear" prefetch={false} href={modelsHref({ sort: sp.sort }, {})}>ล้างทั้งหมด</Link>
          </div>
        ) : null}

        {win.items.length ? (
          <>
            <div className="tdr-models-grid">
              {win.items.map((r) => <ModelCard key={r.id} r={r} trimCount={trimCounts.get(r.id)} />)}
            </div>
            <div className="tdr-models-more-row">
              {win.hasMore
                ? <Link className="tdr-btn tdr-btn--secondary" prefetch={false} href={modelsHref(sp, { page: String(win.nextPage) })} scroll={false}>โหลดเพิ่ม · แสดง {formatNumber(win.shown)} จาก {formatNumber(win.total)}</Link>
                : <span className="tdr-models-muted">แสดงครบ {formatNumber(win.total)} รุ่น</span>}
            </div>
          </>
        ) : (
          <BlockEmpty title="ไม่มีรุ่นที่ตรงกับตัวกรองนี้" text="ลองเอาตัวกรองบางอันออก">
            <Link className="tdr-models-clear" prefetch={false} href={modelsHref({ sort: sp.sort }, {})}>ล้างทั้งหมด</Link>
          </BlockEmpty>
        )}
        <p className="tdr-models-src-line">ราคาจาก Price Ledger ของ TDR (ราคาขายปลีกที่ประกาศ) · รุ่นที่ไม่มีราคาจะแสดง &ldquo;ยังไม่ประกาศราคา&rdquo; · สเปกจาก TDR Vehicle Master</p>
      </div>
    </div>
  </div>;
}
