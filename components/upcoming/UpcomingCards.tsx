import Link from "next/link";
import { ConfidenceMeter, Flag, StageBar } from "@/components/design";
import type { UpcomingCard } from "@/lib/upcoming/boundary";

/** Small Upcoming cards (P06 strip, P07 group). Renders nothing when there are no rows, so while PR 12's source is
 *  absent the section is simply omitted. Stage and confidence use the shared StageBar / ConfidenceMeter (navy / blue,
 *  never green or red); a delayed car carries the amber flag. */
export function UpcomingCards({ title, rows, headingId }: { title: string; rows: UpcomingCard[]; headingId: string }) {
  if (!rows.length) return null;
  return (
    <section className="tdr-upcoming" aria-labelledby={headingId}>
      <h2 id={headingId}>{title}</h2>
      <ul className="tdr-upcoming__grid">
        {rows.map((r) => (
          <li key={r.slug} className="tdr-upcoming__card">
            {r.image ? <figure><img src={r.image.url} alt={r.name} loading="lazy" /><figcaption>ภาพ: {r.image.credit}</figcaption></figure> : null}
            <div className="tdr-eyebrow">{r.brandText}</div>
            <h3><Link href={`/upcoming/${r.slug}`}>{r.name}</Link>{r.nameProvisional ? <span className="tdr-models-tag">ชื่อชั่วคราว</span> : null}</h3>
            <StageBar step={r.stage.step} label={r.stage.label} />
            <ConfidenceMeter level={r.confidence.level} label={r.confidence.label} />
            {r.windowText ? <p className="tdr-models-muted">{r.windowText}</p> : null}
            <div className="tdr-chips">{r.delayed ? <Flag kind="delayed">ล่าช้า</Flag> : null}{r.tags.map((t) => <span key={t} className="tdr-models-tag">{t}</span>)}</div>
          </li>
        ))}
      </ul>
    </section>
  );
}
