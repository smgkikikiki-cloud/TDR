import { useId } from "react";
import Link from "next/link";
import { Button, Card, Skeleton } from "@/components/design";
import { BlockEmpty, BlockError } from "@/components/home/states";
import { ANON_COMPARE_DAILY_LIMIT } from "@/lib/anon-allowance";
import { formatNumber } from "@/lib/design/format";
import { getHomeCatalog } from "@/lib/home/catalog";
import { COMPARE_MAX_TRIMS, type CompareExample } from "@/lib/home/catalog-logic";

const baht = (n: number) => formatNumber(n);
function priceText(c: CompareExample) {
  if (c.min === null) return null;
  return c.max !== null && c.max !== c.min ? `฿${baht(c.min)}–${baht(c.max)}` : `฿${baht(c.min)}`;
}

export type CompareState =
  | { kind: "loading" }
  | { kind: "error" }
  | { kind: "empty" }
  | { kind: "ok"; examples: [CompareExample, CompareExample] };

/** Compare Specs block (PAGES P01): two real example cars with their trim count and price range, and the two compare
 *  limits read from the same constants the feature enforces. No photo: DESIGN §9 allows a car photo only with a verified
 *  credit, and Home has no credit data yet, so the example is shown as text. */
export function CompareBlock({ state }: { state: CompareState }) {
  if (state.kind === "loading") return <CompareSkeleton />;
  if (state.kind === "error") return <CompareFrame><BlockError title="เทียบรถตรงรุ่นย่อย" /></CompareFrame>;
  if (state.kind === "empty") return <CompareFrame><BlockEmpty title="เทียบรถตรงรุ่นย่อย" text="ยังไม่มีข้อมูลรุ่นย่อยและราคาพอสำหรับตัวอย่าง" /></CompareFrame>;
  return (
    <CompareFrame>
      <div className="tdr-home-cmp">
        {state.examples.map((c, i) => (
          <Fragment2 key={c.key} vs={i === 1}>
            <Card tone="raised" className="tdr-home-car">
              <span className="tdr-home-muted tdr-home-xs">{c.brand}</span>
              <b className="tdr-home-car__name">{c.model}</b>
              <span className="tdr-home-muted tdr-home-sm">{formatNumber(c.trims)} รุ่นย่อย{priceText(c) ? <> · <span className="tdr-home-mono">{priceText(c)}</span></> : null}</span>
            </Card>
          </Fragment2>
        ))}
        <div className="tdr-home-facts">
          <div className="tdr-home-fact"><span className="tdr-home-muted tdr-home-xs">เลือกได้สูงสุด</span><strong>{COMPARE_MAX_TRIMS}</strong><span className="tdr-home-muted tdr-home-xs">รุ่นย่อยต่อครั้ง</span></div>
          <div className="tdr-home-fact"><span className="tdr-home-muted tdr-home-xs">ไม่เข้าสู่ระบบ</span><strong>{ANON_COMPARE_DAILY_LIMIT}</strong><span className="tdr-home-muted tdr-home-xs">ครั้ง / วัน</span></div>
          <Button variant="secondary" href="/compare">เริ่มเปรียบเทียบ →</Button>
        </div>
      </div>
    </CompareFrame>
  );
}

/** Reads the catalogue and hands one of the four states to the block; a read failure becomes the error state. */
export async function CompareSection() {
  try {
    const examples = (await getHomeCatalog()).compare;
    return <CompareBlock state={examples.length >= 2 ? { kind: "ok", examples: [examples[0], examples[1]] } : { kind: "empty" }} />;
  } catch {
    return <CompareBlock state={{ kind: "error" }} />;
  }
}

/** Puts the "VS" mark between the two cars. */
function Fragment2({ vs, children }: { vs: boolean; children: React.ReactNode }) {
  return <>{vs ? <div className="tdr-home-vs" aria-hidden="true">VS</div> : null}{children}</>;
}

function CompareFrame({ children }: { children: React.ReactNode }) {
  const headingId = `home-cmp-${useId()}`;
  return (
    <section className="tdr-home-blk" aria-labelledby={headingId}>
      <div className="tdr-wrap">
        <div className="tdr-home-head">
          <div>
            <div className="tdr-eyebrow" lang="en">Compare Specs</div>
            <h2 id={headingId} className="tdr-home-h2 tdr-home-h2--ink">เทียบรถ<span className="tdr-home-hl">ตรงรุ่นย่อย</span></h2>
          </div>
          <Link className="tdr-home-more" href="/compare">เริ่มเปรียบเทียบรถ →</Link>
        </div>
        {children}
      </div>
    </section>
  );
}

export function CompareSkeleton() {
  return (
    <CompareFrame>
      <div className="tdr-home-cmp" aria-busy="true"><Skeleton height={120} /><span /><Skeleton height={120} /><Skeleton height={120} /></div>
    </CompareFrame>
  );
}
