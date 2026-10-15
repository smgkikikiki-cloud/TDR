"use client";

import { DonutChart, Legend, type Slice } from "@/components/charts/PieChart";
import { BarChart } from "@/components/charts/BarChart";
import { LineChart } from "@/components/charts/LineChart";
import { Card, CardHead } from "@/components/design";
import { compactNumber, groupedNumber } from "@/components/charts/format";
import type { PublicMarket } from "@/lib/public-market";

const MINUS = "−";

/** Brand colour = its rank in this month (design tokens --chart-cat-1…8, fixed order), reused in the donut and the ranking:
 *  a brand that is navy in the donut is navy in the bars. Colour is never the only cue: every slice and bar carries its number. */
function brandColors(market: PublicMarket) {
  const colors = new Map<string, string>();
  market.brands.forEach((brand, index) => colors.set(brand.key, `var(--chart-cat-${(index % 8) + 1})`));
  return colors;
}

/** Month-on-month change in units with arrow and sign (DESIGN §3: a change never relies on colour alone). */
function signedUnits(value: number) {
  if (value === 0) return "0";
  return value > 0 ? `▲ +${groupedNumber(value)}` : `▼ ${MINUS}${groupedNumber(Math.abs(value))}`;
}

export function MarketCharts({ market, title }: { market: PublicMarket; title: string }) {
  const colors = brandColors(market);

  const slices: Slice[] = [
    ...market.brands.map((b) => ({ label: b.label, value: b.registrations, color: colors.get(b.key)! })),
    ...(market.others ? [{ label: "อื่นๆ", value: market.others.registrations, color: "var(--border-strong)" }] : []),
  ];

  const trendPoints = market.trend.map((t) => t.total);
  const hasTrend = trendPoints.filter((v) => v !== null).length >= 2;
  const maxMove = Math.max(1, ...market.movers.map((m) => Math.abs(m.delta)));

  return <div className="tdr-market-grid">
    <Card as="section" className="tdr-market-card">
      <CardHead title={`ส่วนแบ่งตลาด · ${title}`} aside={<span className="tdr-market-sub">{market.period} · {groupedNumber(market.totalRegistrations)} คัน</span>} />
      <div className="tdr-market-donut">
        <DonutChart data={slices} size={190} className="tdr-market-donut__svg"
                    centerValue={compactNumber(market.totalRegistrations)} centerLabel="คันจดทะเบียน" />
        <Legend data={slices} className="tdr-market-legend" itemClassName="tdr-market-legend__item"
                swatchClassName="tdr-market-legend__swatch" valueClassName="tdr-market-legend__value" />
      </div>
    </Card>

    <Card as="section" className="tdr-market-card">
      <CardHead title={`อันดับ · ${title}`} aside={<span className="tdr-market-sub">{market.period}</span>} />
      <BarChart
        rows={market.brands.map((b) => ({
          key: b.key, label: b.label, value: b.registrations,
          color: colors.get(b.key), sub: `${groupedNumber(b.sharePct, 1)}%`,
        }))}
        formatValue={groupedNumber}
        className="tdr-market-bars" rowClassName="tdr-market-bars__row" labelClassName="tdr-market-bars__label"
        trackClassName="tdr-market-bars__track" barClassName="tdr-market-bars__fill" valueClassName="tdr-market-bars__value" />
    </Card>

    <Card as="section" className="tdr-market-card">
      <CardHead title="ยอดจดทะเบียนรวมรายเดือน" aside={<span className="tdr-market-sub">ย้อนหลัง {market.trend.length} เดือน</span>} />
      {hasTrend ? (
        <LineChart
          className="tdr-market-line"
          labels={market.trend.map((t) => t.period.slice(2))}
          series={[{ key: "total", label: "ยอดรวม", color: "var(--brand-blue)", points: trendPoints }]}
          formatValue={compactNumber} />
      ) : (
        <div className="tdr-market-empty"><b>ยังไม่มีข้อมูลย้อนหลังพอจะวาดเส้น</b></div>
      )}
    </Card>

    <Card as="section" className="tdr-market-card">
      <CardHead title="เปลี่ยนแปลงจากเดือนก่อน" aside={<span className="tdr-market-sub">{market.previousPeriod ?? "—"} → {market.period}</span>} />
      {market.movers.length ? (
        <ul className="tdr-market-movers">
          {market.movers.map((m) => {
            const up = m.delta >= 0;
            return (
              <li className="tdr-market-movers__row" key={m.key}>
                <div className="tdr-market-movers__label"><b>{m.label}</b><span>{groupedNumber(m.sharePct, 1)}% ส่วนแบ่ง</span></div>
                <div className="tdr-market-movers__track" aria-hidden="true">
                  <i className={up ? "is-up" : "is-down"}
                     style={up ? { left: "50%", width: `${(Math.abs(m.delta) / maxMove) * 50}%` } : { right: "50%", width: `${(Math.abs(m.delta) / maxMove) * 50}%` }} />
                </div>
                <b className={up ? "tdr-market-movers__value is-up" : "tdr-market-movers__value is-down"}>{signedUnits(m.delta)}</b>
              </li>
            );
          })}
        </ul>
      ) : (
        <div className="tdr-market-empty"><b>ยังไม่มีเดือนก่อนหน้าให้เทียบ</b></div>
      )}
    </Card>
  </div>;
}
