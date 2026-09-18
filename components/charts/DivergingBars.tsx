"use client";

export type MoverRow = { key: string; label: string; sub?: string; value: number };

/** One bar per row, growing left or right from a centre line — the same
 *  "share gainers vs. losers" shape as vehreg's signed_bar, rebuilt as plain
 *  divs so it never needs a chart library or a fixed pixel width. */
export function DivergingBars({ rows, className, rowClassName, labelClassName, trackClassName, barClassName, valueClassName, positiveClassName, negativeClassName, formatValue }: {
  rows: MoverRow[];
  className?: string;
  rowClassName?: string;
  labelClassName?: string;
  trackClassName?: string;
  barClassName?: string;
  valueClassName?: string;
  positiveClassName?: string;
  negativeClassName?: string;
  formatValue: (value: number) => string;
}) {
  const maxAbs = Math.max(1, ...rows.map((r) => Math.abs(r.value)));
  return (
    <div className={className}>
      {rows.map((row) => {
        const positive = row.value >= 0;
        const halfWidth = (Math.abs(row.value) / maxAbs) * 50;
        return (
          <div className={rowClassName} key={row.key}>
            <div className={labelClassName}><b>{row.label}</b>{row.sub ? <span>{row.sub}</span> : null}</div>
            <div className={trackClassName}>
              <i
                className={positive ? positiveClassName : negativeClassName}
                style={positive ? { left: "50%", width: `${halfWidth}%` } : { right: "50%", width: `${halfWidth}%` }}
              />
            </div>
            <b className={`${valueClassName} ${positive ? positiveClassName : negativeClassName}`}>
              {positive ? "+" : ""}{formatValue(row.value)}
            </b>
          </div>
        );
      })}
    </div>
  );
}
