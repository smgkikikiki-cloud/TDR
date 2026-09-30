import { Card } from "@/components/design";

/** A block that failed to load: what failed and a way to retry, never a stack, never a blank page. */
export function BlockError({ title, retryHref }: { title: string; retryHref?: string }) {
  return (
    <Card tone="dashed" className="tdr-models-state">
      <div role="alert">
        <b className="tdr-card__title">{title}</b>
        <p className="tdr-models-muted">โหลดข้อมูลไม่สำเร็จ · {retryHref ? <a href={retryHref}>ลองอีกครั้ง</a> : "ลองอีกครั้งภายหลัง"}</p>
      </div>
    </Card>
  );
}

/** A block with nothing to show: a dashed card and one sentence ("ยังไม่มี…", never an empty area). */
export function BlockEmpty({ title, text, children }: { title: string; text?: string; children?: React.ReactNode }) {
  return (
    <Card tone="dashed" className="tdr-models-state">
      <b className="tdr-card__title">{title}</b>
      {text ? <p className="tdr-models-muted">{text}</p> : null}
      {children}
    </Card>
  );
}
