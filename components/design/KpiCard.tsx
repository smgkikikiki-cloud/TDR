import type { ReactNode } from "react";
import { formatNumber } from "@/lib/design/format";

/** Label + mono value (+ unit, delta, note). Numbers get thousands separators; never hard-code figures. */
export function KpiCard({ label, value, unit, delta, note, size = "md" }: {
  label: string; value: number | string; unit?: string; delta?: ReactNode; note?: ReactNode; size?: "md" | "lg";
}) {
  return (
    <div className={size === "lg" ? "tdr-kpi tdr-kpi--lg" : "tdr-kpi"}>
      <span className="tdr-kpi__label">{label}</span>
      <span className="tdr-kpi__value">{formatNumber(value)}{unit ? <span className="tdr-kpi__unit">{unit}</span> : null}</span>
      {delta ? <span>{delta}</span> : null}
      {note ? <span className="tdr-kpi__note">{note}</span> : null}
    </div>
  );
}
