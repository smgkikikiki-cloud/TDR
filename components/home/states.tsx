import Link from "next/link";
import { Card } from "@/components/design";

/** Blocker 11 (design/GRAFT_PLAN.md): the market analysis engine is being replaced, so Home must not read market
 *  figures through the old one. These blocks are existing market capabilities that are temporarily not rewired, not
 *  unreleased features, so they never say "เร็วๆ นี้" (that label is only for the Ice-dependent Panels 1-4 and the
 *  province map). Each shows its approved title and no figures, and points to the live market page. When the new engine
 *  ships, each call site swaps this for the real block. */
export function MarketUpdating({ title }: { title: string }) {
  return (
    <Card tone="dashed" className="tdr-home-pending">
      <div className="tdr-card__head">
        <b className="tdr-card__title">{title}</b>
      </div>
      <p className="tdr-home-muted">อยู่ระหว่างปรับปรุงระบบวิเคราะห์ตลาด · <Link href="/market">ดูข้อมูลตลาดที่หน้า Automotive Intelligence</Link></p>
    </Card>
  );
}

/** A block that failed to load: what failed and a retry, never a stack, and never a blank page. */
export function BlockError({ title }: { title: string }) {
  return (
    <Card tone="dashed" className="tdr-home-error" >
      <div role="alert">
        <b className="tdr-card__title">{title}</b>
        <p className="tdr-home-muted">โหลดข้อมูลไม่สำเร็จ · <a href="/">ลองอีกครั้ง</a></p>
      </div>
    </Card>
  );
}

/** A block with nothing to show yet: a dashed card and a short sentence. */
export function BlockEmpty({ title, text }: { title: string; text: string }) {
  return (
    <Card tone="dashed" className="tdr-home-empty">
      <b className="tdr-card__title">{title}</b>
      <p className="tdr-home-muted">{text}</p>
    </Card>
  );
}
