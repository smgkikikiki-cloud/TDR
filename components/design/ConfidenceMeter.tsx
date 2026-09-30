import { clampStep } from "@/lib/design/format";

/** Four-step confidence meter. `level` is 1-based; the label text comes from the page. Blue fill, never green/red. */
export function ConfidenceMeter({ level, total = 4, label }: { level: number; total?: number; label: string }) {
  const on = clampStep(level, total);
  return (
    <div className="tdr-conf" role="img" aria-label={`${label} (${on}/${total})`}>
      {Array.from({ length: total }, (_, i) => <i key={i} className={i < on ? "tdr-conf__seg tdr-conf__seg--on" : "tdr-conf__seg"} aria-hidden="true" />)}
      <span className="tdr-conf__label">{label}</span>
    </div>
  );
}
