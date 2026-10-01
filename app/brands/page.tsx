import { Suspense } from "react";
import { PageHead } from "@/components/design";
import { BrandIndex } from "@/components/brands/BrandIndex";
import { BrandIndexSkeleton } from "@/components/brands/BrandIndexSkeleton";
import { BlockEmpty, BlockError } from "@/components/models/states";
import { getCanonicalBrands, getCanonicalModels } from "@/lib/canonical-data";
import { isCurrentLifecycleStatus } from "@/lib/canonical-trim-status";
import { buildBrandIndex } from "@/lib/brands";

export const metadata = { title: "แบรนด์รถในตลาดไทย · Vehicle Database" };

function Head() {
  return (
    <PageHead
      eyebrow="Vehicle Database"
      eyebrowLang="en"
      title="แบรนด์รถในตลาดไทย"
      lead="แบรนด์รถยนต์ที่มีจำหน่ายในประเทศไทย"
    />
  );
}

async function Index() {
  let rows;
  try {
    const [brands, models] = await Promise.all([getCanonicalBrands(250), getCanonicalModels(600)]);
    rows = buildBrandIndex(brands, (models as any[]).filter((m) => isCurrentLifecycleStatus(m.status)));
  } catch {
    return <div className="tdr-wrap"><Head /><BlockError title="แบรนด์รถ" retryHref="/brands" /></div>;
  }
  return (
    <div className="tdr-wrap">
      <Head />
      {rows.length ? <BrandIndex rows={rows} /> : <BlockEmpty title="ยังไม่มีข้อมูลแบรนด์" text="ยังไม่มีแบรนด์ที่มีรุ่นจำหน่ายอยู่ในฐานข้อมูล" />}
    </div>
  );
}

export default function BrandsPage() {
  return <Suspense fallback={<BrandIndexSkeleton />}><Index /></Suspense>;
}
