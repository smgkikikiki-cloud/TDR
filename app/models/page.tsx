import { Suspense } from "react";
import Link from "next/link";
import { Button, KpiCard, PageHead, TextInput } from "@/components/design";
import { ListSkeleton } from "@/components/models/ListSkeleton";
import { ModelsExplorer, type ExplorerModel } from "@/components/models/ModelsExplorer";
import { BlockEmpty, BlockError } from "@/components/models/states";
import { getCanonicalBrands, getCanonicalModels, getCurrentTrimCountsByModel } from "@/lib/canonical-data";
import { isCurrentLifecycleStatus } from "@/lib/canonical-trim-status";
import { formatNumber } from "@/lib/design/format";
import { modelsHref, normalizeParams, type ModelsParams } from "@/lib/models/list";

export const metadata = { title: "Vehicle Database · รถที่จำหน่ายในประเทศไทย" };

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

  const current = (all as ExplorerModel[]).filter((r) => isCurrentLifecycleStatus(r.status));
  const brandCount = new Set(current.map((r) => r.brands?.slug).filter(Boolean)).size;
  const trimTotal = current.reduce((n, r) => n + (trimCounts.get(r.id) || 0), 0);
  const assembled = current.filter((r) => r.production_type === "CKD" || r.production_type === "SKD").length;
  const imported = current.filter((r) => r.production_type === "CBU").length;
  const lead = `รวมรถ ${formatNumber(current.length)} รุ่นที่ขายในไทยวันนี้ ครบทุกรุ่นย่อย สเปก และราคา อัปเดตต่อเนื่องทุกครั้งที่มีรุ่นใหม่หรือปรับราคา`;

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

    <ModelsExplorer sp={sp} current={current} brands={brands} trimCounts={trimCounts} brandCount={brandCount} />
  </div>;
}
