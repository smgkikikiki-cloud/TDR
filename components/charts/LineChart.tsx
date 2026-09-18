"use client";

export type LineSeries = { key: string; label: string; color: string; points: (number | null)[] };

/**
 * Change over time: one line per series against one shared y axis.
 *
 * One axis, always. Two measures on two scales in one frame is the single
 * most misleading thing a chart can do -- the crossing point is an artefact of
 * whatever the two ranges happen to be. Series of different magnitudes belong
 * in two charts.
 *
 * A gap in a series is a gap: a null breaks the line rather than being
 * interpolated across, because a straight segment over missing months is a
 * claim the data does not make.
 */
export function LineChart({
  series, labels, width = 640, height = 220, formatValue, className,
}: {
  series: LineSeries[];
  /** One per point, e.g. "2026-07". Shown thinned out along the x axis. */
  labels: string[];
  width?: number;
  height?: number;
  formatValue: (value: number) => string;
  className?: string;
}) {
  const padL = 46, padR = 10, padT = 12, padB = 24;
  const values = series.flatMap((s) => s.points).filter((v): v is number => v !== null && Number.isFinite(v));
  const hi = values.length ? Math.max(...values) : 1;
  const lo = Math.min(0, ...(values.length ? values : [0]));
  const span = hi - lo || 1;
  const innerW = width - padL - padR;
  const innerH = height - padT - padB;
  const stepX = labels.length > 1 ? innerW / (labels.length - 1) : 0;
  const x = (i: number) => padL + i * stepX;
  const y = (v: number) => padT + innerH - ((v - lo) / span) * innerH;

  // Four gridlines is enough to read a level against without becoming a
  // second thing to look at.
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => lo + f * span);
  // Thin the x labels so they never collide, whatever the series length.
  const everyNth = Math.max(1, Math.ceil(labels.length / 6));

  return (
    <svg viewBox={`0 0 ${width} ${height}`} role="img" className={className}
         aria-label={series.map((s) => `${s.label}: ${s.points.filter((p) => p !== null).length} จุด`).join(", ")}
         style={{ width: "100%", height: "auto", display: "block" }}>
      {ticks.map((t) => (
        <g key={t}>
          <line x1={padL} y1={y(t)} x2={width - padR} y2={y(t)} stroke="currentColor" strokeOpacity={0.1} strokeWidth={1} />
          <text x={padL - 7} y={y(t)} textAnchor="end" dominantBaseline="middle" fontSize={10} fill="currentColor" opacity={0.55}>
            {formatValue(t)}
          </text>
        </g>
      ))}
      {labels.map((label, i) => i % everyNth === 0 ? (
        <text key={label} x={x(i)} y={height - 7} textAnchor="middle" fontSize={10} fill="currentColor" opacity={0.55}>
          {label}
        </text>
      ) : null)}
      {series.map((s) => {
        // A null ends the current run: the line stops rather than spanning it.
        const runs: string[] = [];
        let open = false;
        s.points.forEach((p, i) => {
          if (p === null || !Number.isFinite(p)) { open = false; return; }
          runs.push(`${open ? "L" : "M"} ${x(i).toFixed(1)} ${y(p).toFixed(1)}`);
          open = true;
        });
        return (
          <g key={s.key}>
            <path d={runs.join(" ")} fill="none" stroke={s.color} strokeWidth={2}
                  strokeLinecap="round" strokeLinejoin="round" />
            {s.points.map((p, i) => p === null || !Number.isFinite(p) ? null : (
              <circle key={i} cx={x(i)} cy={y(p)} r={4} fill={s.color} stroke="var(--white, #fff)" strokeWidth={2}>
                <title>{`${s.label} · ${labels[i]}: ${formatValue(p)}`}</title>
              </circle>
            ))}
          </g>
        );
      })}
    </svg>
  );
}
