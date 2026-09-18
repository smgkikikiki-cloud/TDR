"use client";

import { DonutChart, Legend, type Slice } from "@/components/charts/PieChart";
import { BarChart } from "@/components/charts/BarChart";
import { LineChart } from "@/components/charts/LineChart";
import { DivergingBars } from "@/components/charts/DivergingBars";
import { colorFor } from "@/components/charts/palette";
import { compactNumber, groupedNumber } from "@/components/charts/format";
import type { PublicMarket } from "@/lib/public-market";

const units = (value: number) => groupedNumber(value);
const compact = compactNumber;

/** Every chart on this page draws from one month of one aggregate, so the
 *  colour a brand gets is assigned once, by rank in that month, and reused --
 *  a brand that is blue in the donut is blue in the ranking beside it. */
function brandColors(market: PublicMarket) {
  const colors = new Map<string, string>();
  market.brands.forEach((brand, index) => colors.set(brand.key, colorFor(index)));
  return colors;
}

export function MarketCharts({ market }: { market: PublicMarket }) {
  const colors = brandColors(market);

  const slices: Slice[] = [
    ...market.brands.map((b) => ({ label: b.label, value: b.registrations, color: colors.get(b.key)! })),
    ...(market.others ? [{ label: "แบรนด์อื่น", value: market.others.registrations, color: "#c3c8d2" }] : []),
  ];

  const trendPoints = market.trend.map((t) => t.total);
  const hasTrend = trendPoints.filter((v) => v !== null).length >= 2;

  return <>
    <section className="marketGrid">
      <figure className="marketCard">
        <figcaption>
          <b>ส่วนแบ่งตลาดรายแบรนด์</b>
          <span>{market.period} · {units(market.totalRegistrations)} คัน</span>
        </figcaption>
        <div className="marketDonutWrap">
          <DonutChart data={slices} size={190}
                      centerValue={compact(market.totalRegistrations)} centerLabel="คันจดทะเบียน" />
          <Legend data={slices} className="marketLegend" itemClassName="marketLegendItem"
                  swatchClassName="marketSwatch" valueClassName="marketLegendValue" />
        </div>
      </figure>

      <figure className="marketCard">
        <figcaption>
          <b>อันดับแบรนด์</b>
          <span>{market.period}</span>
        </figcaption>
        <BarChart
          rows={market.brands.map((b) => ({
            key: b.key, label: b.label, value: b.registrations,
            color: colors.get(b.key), sub: `${groupedNumber(b.sharePct, 1)}%`,
          }))}
          formatValue={units}
          className="marketBars" rowClassName="marketBarRow" labelClassName="marketBarLabel"
          trackClassName="marketBarTrack" barClassName="marketBarFill" valueClassName="marketBarValue" />
      </figure>
    </section>

    <section className="marketGrid">
      <figure className="marketCard">
        <figcaption>
          <b>ยอดจดทะเบียนรวมรายเดือน</b>
          <span>ย้อนหลัง {market.trend.length} เดือน</span>
        </figcaption>
        {hasTrend ? (
          <LineChart
            className="marketLine"
            labels={market.trend.map((t) => t.period.slice(2))}
            series={[{ key: "total", label: "ยอดรวม", color: "#012061", points: trendPoints }]}
            formatValue={compact} />
        ) : (
          <div className="sfEmpty"><b>ยังไม่มีข้อมูลย้อนหลังพอจะวาดเส้น</b></div>
        )}
      </figure>

      <figure className="marketCard">
        <figcaption>
          <b>เปลี่ยนแปลงจากเดือนก่อน</b>
          <span>{market.previousPeriod} → {market.period}</span>
        </figcaption>
        {market.movers.length ? (
          <DivergingBars
            rows={market.movers.map((m) => ({
              key: m.key, label: m.label, sub: `${groupedNumber(m.sharePct, 1)}% ส่วนแบ่ง`, value: m.delta,
            }))}
            formatValue={units}
            className="marketMovers" rowClassName="marketMoverRow" labelClassName="marketMoverLabel"
            trackClassName="marketMoverTrack" valueClassName="marketMoverValue"
            positiveClassName="marketUp" negativeClassName="marketDown" />
        ) : (
          <div className="sfEmpty"><b>ยังไม่มีเดือนก่อนหน้าให้เทียบ</b></div>
        )}
      </figure>
    </section>
  </>;
}
