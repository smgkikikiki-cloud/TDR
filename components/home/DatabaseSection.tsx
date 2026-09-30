import { useId } from "react";
import Link from "next/link";
import { Chip, KpiCard, Skeleton } from "@/components/design";
import { BodyIconSvg } from "@/components/home/BodyIcons";
import { BlockEmpty, BlockError } from "@/components/home/states";
import { formatNumber } from "@/lib/design/format";
import { getHomeCatalog } from "@/lib/home/catalog";
import type { HomeCatalog } from "@/lib/home/catalog-logic";

export type DatabaseState =
  | { kind: "loading" }
  | { kind: "error" }
  | { kind: "empty" }
  | { kind: "ok"; catalog: HomeCatalog };

/** Vehicle Database block (PAGES P01): live counts, body-type chips and brand chips, all from the canonical catalogue.
 *  Brands are text chips, never logos (DESIGN §9). The four states are one component so /design/home-states can show them. */
export function DatabaseBlock({ state }: { state: DatabaseState }) {
  if (state.kind === "loading") return <DatabaseSkeleton />;
  if (state.kind === "error") return <DatabaseFrame><BlockError title="ฐานข้อมูลรถยนต์" /></DatabaseFrame>;
  if (state.kind === "empty") return <DatabaseFrame><BlockEmpty title="ฐานข้อมูลรถยนต์" text="ยังไม่มีข้อมูลรุ่นที่ยังจำหน่าย" /></DatabaseFrame>;
  const catalog = state.catalog;
  return (
    <DatabaseFrame subhead={`รวมรถ ${formatNumber(catalog.models)} รุ่นที่ขายในไทยวันนี้ ครบทุกรุ่นย่อย สเปก และราคา อัปเดตต่อเนื่องทุกครั้งที่มีรุ่นใหม่หรือปรับราคา`}>
      <div className="tdr-kpis tdr-home-stats">
        <KpiCard size="lg" label="รุ่นที่ยังจำหน่าย" value={catalog.models} />
        <KpiCard size="lg" label="รุ่นย่อยที่ยังจำหน่าย" value={catalog.trims} />
        <KpiCard size="lg" label="แบรนด์" value={catalog.brands} />
      </div>
      <div className="tdr-home-lbl">เลือกตามประเภทตัวถัง</div>
      <div className="tdr-chips">
        {catalog.bodies.map((b) => {
          const face = <><BodyIconSvg icon={b.icon} />{b.label}</>;
          return b.href
            ? <Chip key={b.key} href={b.href} count={b.count}>{face}</Chip>
            : <Chip key={b.key} count={b.count}>{face}</Chip>;
        })}
      </div>
      <div className="tdr-home-lbl">เลือกตามแบรนด์</div>
      <div className="tdr-chips">
        {catalog.brandChips.map((b) => <Chip key={b.slug} href={`/brands/${b.slug}`}>{b.name}</Chip>)}
        <Chip href="/brands" className="tdr-home-chip-more">ทุกแบรนด์ ({formatNumber(catalog.brands)}) →</Chip>
      </div>
    </DatabaseFrame>
  );
}

/** Reads the catalogue and hands one of the four states to the block; a read failure becomes the error state. */
export async function DatabaseSection() {
  try {
    const catalog = await getHomeCatalog();
    return <DatabaseBlock state={catalog.models ? { kind: "ok", catalog } : { kind: "empty" }} />;
  } catch {
    return <DatabaseBlock state={{ kind: "error" }} />;
  }
}

function DatabaseFrame({ children, subhead }: { children: React.ReactNode; subhead?: string }) {
  const headingId = `home-db-${useId()}`;
  return (
    <section className="tdr-home-blk" aria-labelledby={headingId}>
      <div className="tdr-wrap">
        <div className="tdr-home-head">
          <div>
            <div className="tdr-eyebrow" lang="en">Vehicle Database</div>
            <h2 id={headingId} className="tdr-home-h2 tdr-home-h2--ink">ฐานข้อมูลรถยนต์<span className="tdr-home-hl">ในประเทศไทย</span></h2>
            {subhead ? <p className="tdr-home-subhead">{subhead}</p> : null}
          </div>
          <Link className="tdr-home-more" href="/models">ดูฐานข้อมูลรถทั้งหมด →</Link>
        </div>
        {children}
      </div>
    </section>
  );
}

/** Shown while the catalogue loads: the final layout, no spinner. */
export function DatabaseSkeleton() {
  return (
    <DatabaseFrame>
      <div className="tdr-kpis tdr-home-stats" aria-busy="true">
        <Skeleton height={96} /><Skeleton height={96} /><Skeleton height={96} />
      </div>
      <div className="tdr-home-lbl"><Skeleton height={16} width={160} /></div>
      <div className="tdr-chips" aria-hidden="true">{Array.from({ length: 6 }, (_, i) => <Skeleton key={i} height={36} width={120} radius="pill" />)}</div>
    </DatabaseFrame>
  );
}
