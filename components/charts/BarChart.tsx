"use client";

export type BarRow = { key: string; label: string; value: number; color?: string; sub?: string };

/** Ranked comparison: one horizontal bar per row, sorted as given.
 *
 *  Horizontal because the labels are brand and model names -- rotating those
 *  under a vertical axis is the commonest way a comparison becomes unreadable,
 *  and a phone has height to spare and no width. Each bar carries its own
 *  value at the end rather than a value axis, so the chart needs no gridlines
 *  and no second reading step.
 *
 *  Plain elements, not SVG: a bar chart is a list of proportions and CSS
 *  already does proportions. It reflows at any width without a viewBox.
 */
export function BarChart({
  rows, className, rowClassName, labelClassName, trackClassName, barClassName,
  valueClassName, formatValue, max,
}: {
  rows: BarRow[];
  className?: string;
  rowClassName?: string;
  labelClassName?: string;
  trackClassName?: string;
  barClassName?: string;
  valueClassName?: string;
  formatValue: (value: number) => string;
  /** Force a common scale across several charts; otherwise the largest row. */
  max?: number;
}) {
  const ceiling = Math.max(1, max ?? Math.max(...rows.map((r) => r.value), 0));
  return (
    <div className={className}>
      {rows.map((row) => (
        <div className={rowClassName} key={row.key}>
          <div className={labelClassName}>
            <b>{row.label}</b>{row.sub ? <span>{row.sub}</span> : null}
          </div>
          <div className={trackClassName}>
            <i
              className={barClassName}
              style={{ width: `${Math.max(0, (row.value / ceiling) * 100)}%`, background: row.color }}
              title={`${row.label}: ${formatValue(row.value)}`}
            />
          </div>
          <b className={valueClassName}>{formatValue(row.value)}</b>
        </div>
      ))}
    </div>
  );
}
