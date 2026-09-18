"use client";

export type Slice = { label: string; value: number; color: string };

function arcPath(cx: number, cy: number, rOuter: number, rInner: number, startDeg: number, endDeg: number) {
  const toXY = (deg: number, radius: number) => {
    const rad = (deg * Math.PI) / 180;
    return [cx + radius * Math.cos(rad), cy + radius * Math.sin(rad)];
  };
  const large = endDeg - startDeg > 180 ? 1 : 0;
  const [x1, y1] = toXY(startDeg, rOuter);
  const [x2, y2] = toXY(endDeg, rOuter);
  const [x3, y3] = toXY(endDeg, rInner);
  const [x4, y4] = toXY(startDeg, rInner);
  return `M ${x1} ${y1} A ${rOuter} ${rOuter} 0 ${large} 1 ${x2} ${y2} L ${x3} ${y3} A ${rInner} ${rInner} 0 ${large} 0 ${x4} ${y4} Z`;
}

/** A donut, not a pie: the hole holds the total so the chart carries a number,
 *  not just shape. Scales by its SVG viewBox, so it is exactly as
 *  phone-friendly as any other fluid-width element on the page. */
export function DonutChart({
  data, size = 176, thickness, centerValue, centerLabel, className,
}: {
  data: Slice[]; size?: number; thickness?: number; centerValue?: string; centerLabel?: string; className?: string;
}) {
  const total = data.reduce((s, d) => s + d.value, 0);
  const cx = size / 2, cy = size / 2;
  const rOuter = size / 2;
  const rInner = rOuter - (thickness ?? size * 0.19);
  let angle = -90;
  const arcs = data
    .filter((d) => d.value > 0)
    .map((d) => {
      const frac = total > 0 ? d.value / total : 0;
      const start = angle;
      const end = frac >= 1 ? angle + 359.99 : angle + frac * 360;
      angle = end;
      return { ...d, start, end, frac };
    });

  return (
    <svg
      viewBox={`0 0 ${size} ${size}`}
      role="img"
      aria-label={data.map((d) => `${d.label} ${total > 0 ? ((d.value / total) * 100).toFixed(1) : 0}%`).join(", ")}
      className={className}
      style={{ width: "100%", height: "auto", display: "block" }}
    >
      {total <= 0
        ? <circle cx={cx} cy={cy} r={(rOuter + rInner) / 2} fill="none" stroke="currentColor" strokeOpacity={0.12} strokeWidth={rOuter - rInner} />
        : arcs.map((a) => (
          <path key={a.label} d={arcPath(cx, cy, rOuter, rInner, a.start, a.end)} fill={a.color}>
            <title>{`${a.label}: ${(a.frac * 100).toFixed(1)}%`}</title>
          </path>
        ))}
      {centerValue ? (
        <text x={cx} y={cy - (centerLabel ? size * 0.02 : 0)} textAnchor="middle" dominantBaseline="middle" fontSize={size * 0.15} fontWeight={800} fill="currentColor">
          {centerValue}
        </text>
      ) : null}
      {centerLabel ? (
        <text x={cx} y={cy + size * 0.13} textAnchor="middle" dominantBaseline="middle" fontSize={size * 0.06} fill="currentColor" opacity={0.6}>
          {centerLabel}
        </text>
      ) : null}
    </svg>
  );
}

/** Legend as a wrapping list, never a fixed row, so it folds under the donut
 *  on a phone instead of forcing horizontal scroll. */
export function Legend({ data, className, itemClassName, swatchClassName, valueClassName }: {
  data: Slice[]; className?: string; itemClassName?: string; swatchClassName?: string; valueClassName?: string;
}) {
  const total = data.reduce((s, d) => s + d.value, 0);
  return (
    <ul className={className}>
      {data.map((d) => (
        <li className={itemClassName} key={d.label}>
          <span className={swatchClassName} style={{ background: d.color }} aria-hidden="true" />
          <span>{d.label}</span>
          <b className={valueClassName}>{total > 0 ? `${((d.value / total) * 100).toFixed(1)}%` : "—"}</b>
        </li>
      ))}
    </ul>
  );
}
