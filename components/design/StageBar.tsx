import { clampStep } from "@/lib/design/format";

/** Six-step progress bar (upcoming vehicle stage). `step` is 1-based; the label text comes from the page.
 *  Navy fill only; never green/red for stage. */
export function StageBar({ step, total = 6, label }: { step: number; total?: number; label: string }) {
  const on = clampStep(step, total);
  return (
    <div role="img" aria-label={`${label} (${on}/${total})`}>
      <div className="tdr-stagebar" aria-hidden="true">
        {Array.from({ length: total }, (_, i) => <i key={i} className={i < on ? "tdr-stagebar__seg tdr-stagebar__seg--on" : "tdr-stagebar__seg"} />)}
      </div>
      <div className="tdr-stagebar__label">{label}</div>
    </div>
  );
}
