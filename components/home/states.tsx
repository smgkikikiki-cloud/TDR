import { Card, Flag } from "@/components/design";

/** Blocker 11 (design/GRAFT_PLAN.md): the market analysis engine is being replaced, so Home must not read market
 *  figures through the old one. Every market-dependent block renders this pending state with its approved title and
 *  no numbers. When the new engine ships, each call site swaps this for the real block; nothing else changes. */
export function MarketPending({ title, hint }: { title: string; hint?: string }) {
  return (
    <Card tone="dashed" className="tdr-home-pending">
      <div className="tdr-card__head">
        <b className="tdr-card__title">{title}</b>
        <Flag kind="soon">เร็วๆ นี้</Flag>
      </div>
      {hint ? <p className="tdr-home-muted">{hint}</p> : null}
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
