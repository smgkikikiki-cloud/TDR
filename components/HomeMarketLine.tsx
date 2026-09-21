"use client";

import { LineChart } from "@/components/charts/LineChart";
import { compactNumber } from "@/components/charts/format";

export function HomeMarketLine({ labels, points }: { labels: string[]; points: (number | null)[] }) {
  return (
    <LineChart
      labels={labels}
      series={[{ key: "total", label: "ยอดจดทะเบียน", color: "#012061", points }]}
      formatValue={compactNumber}
      height={230}
      className="homeMarketLine"
    />
  );
}
