"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { browserDb } from "@/lib/supabase-browser";
import { bodyLabel } from "@/lib/body-labels";
import {
  comparisonMarketWindow,
  missingReportPeriods,
  monthLabel,
  normalizeReportPeriod,
  periodRangeLabel,
  resolveMarketWindow,
  type MarketComparison,
  type MarketWindow,
} from "@/lib/registration-market";
import { coverageForPeriod, defaultMarketPeriod, periodKey, provisionalMarketPeriods, type CoverageRowLike } from "@/lib/member-market";
import styles from "./market.module.css";

type BrandOption = { id: string; name: string };
type ModelOption = { id: string; name: string; brandId: string; brandName: string; segment: string | null; bodyType: string | null; powertrains: string[] };
type MarketRow = Record<string, any>;
type MarketResponse = {
  dimension: string;
  period: string;
  window: string;
  period_from: string;
  period_to: string;
  rows: MarketRow[];
  comparison: null | { mode: MarketComparison; window: { from: string; to: string }; movement: MarketRow[] };
};
type FilterState = {
  period: string;
  window: MarketWindow;
  compare: "none" | MarketComparison;
  dimension: "model" | "brand" | "segment" | "body_type" | "powertrain";
  registrationType: string;
  brand: string;
  model: string;
  segment: string;
  bodyType: string;
  powertrain: string;
  allScopes: boolean;
};
type TrendPoint = { period: string; total: number };
type RankingMetric = "share" | "registrations";

type ScopeKey = "registrationType" | "brand" | "model" | "segment" | "bodyType" | "powertrain" | "allScopes";

const DIMENSIONS: Array<{ value: FilterState["dimension"]; label: string }> = [
  { value: "model", label: "รุ่น" },
  { value: "brand", label: "แบรนด์" },
  { value: "segment", label: "Segment" },
  { value: "body_type", label: "ตัวถัง" },
  { value: "powertrain", label: "Powertrain" },
];
const WINDOWS: Array<{ value: MarketWindow; label: string; compact: string }> = [
  { value: "month", label: "เดือน", compact: "1M" },
  { value: "rolling3", label: "3 เดือน", compact: "3M" },
  { value: "rolling6", label: "6 เดือน", compact: "6M" },
  { value: "rolling12", label: "12 เดือน", compact: "12M" },
  { value: "ytd", label: "YTD", compact: "YTD" },
];
const FILTER_BY_DIMENSION: Record<FilterState["dimension"], keyof FilterState | undefined> = {
  brand: "brand",
  model: "model",
  segment: "segment",
  body_type: "bodyType",
  powertrain: "powertrain",
};

function n(value: unknown) { return Number(value || 0).toLocaleString("th-TH"); }
function pct(value: unknown, digits = 2) {
  const number = Number(value);
  return Number.isFinite(number) ? `${number.toFixed(digits)}%` : "—";
}
function pp(value: unknown) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return `${number > 0 ? "+" : ""}${number.toFixed(2)} pp`;
}
function rankDelta(value: unknown) {
  if (value == null) return "ใหม่/หลุด";
  const number = Number(value);
  if (!Number.isFinite(number) || number === 0) return "—";
  return `${number > 0 ? "↑" : "↓"}${Math.abs(number)}`;
}

async function jsonFetch(path: string, token: string) {
  const response = await fetch(path, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
  const body = await response.json();
  if (!response.ok) throw Object.assign(new Error(body.error || "โหลดข้อมูลไม่สำเร็จ"), { status: response.status, body });
  return body;
}

function marketPath(
  filters: FilterState,
  period = filters.period,
  limit = 100,
  includeComparison = true,
  dimension: string = filters.dimension,
) {
  const params = new URLSearchParams({ dimension, period, window: filters.window, limit: String(limit) });
  if (includeComparison && filters.compare !== "none") params.set("compare", filters.compare);
  if (filters.registrationType) params.set("registration_type", filters.registrationType);
  if (filters.brand) params.set("brand", filters.brand);
  if (filters.model) params.set("model", filters.model);
  if (filters.segment) params.set("segment", filters.segment);
  if (filters.bodyType) params.set("body_type", filters.bodyType);
  if (filters.powertrain) params.set("powertrain", filters.powertrain);
  if (filters.allScopes) params.set("market_scope", "ALL");
  return `/api/report/market?${params.toString()}`;
}

export function MarketWorkspace({ brands, models }: { brands: BrandOption[]; models: ModelOption[] }) {
  const router = useRouter();
  const [token, setToken] = useState("");
  const [coverage, setCoverage] = useState<CoverageRowLike[]>([]);
  const [filters, setFilters] = useState<FilterState>({
    period: "", window: "month", compare: "previous", dimension: "model",
    registrationType: "", brand: "", model: "", segment: "", bodyType: "", powertrain: "", allScopes: false,
  });
  const [applied, setApplied] = useState<FilterState | null>(null);
  const [data, setData] = useState<MarketResponse | null>(null);
  const [trend, setTrend] = useState<TrendPoint[]>([]);
  const [trendIncomplete, setTrendIncomplete] = useState(false);
  const [status, setStatus] = useState<"loading" | "ready" | "forbidden" | "error">("loading");
  const [message, setMessage] = useState("");
  const [showFilters, setShowFilters] = useState(false);
  const [rankingMetric, setRankingMetric] = useState<RankingMetric>("share");
  // Filter/dimension state and the displayed dataset must never diverge: only
  // the response to the most recently dispatched request is allowed to reach
  // `data`/`applied` (the single source both the chips and the rows read
  // from). Any older, superseded response is discarded outright rather than
  // merged or partially applied, so the two can never show different scopes.
  const requestIdRef = useRef(0);

  const periods = useMemo(() => coverage.map((row) => periodKey(row.period)).filter(Boolean).sort(), [coverage]);
  const available = useMemo(() => new Set(periods.map((period) => normalizeReportPeriod(period)).filter(Boolean) as string[]), [periods]);
  const provisional = useMemo(() => provisionalMarketPeriods(coverage), [coverage]);
  const bodyTypes = useMemo(() => [...new Set(models.map((row) => row.bodyType).filter(Boolean) as string[])].sort(), [models]);
  const segments = useMemo(() => [...new Set(models.map((row) => row.segment).filter(Boolean) as string[])].sort(), [models]);
  const powertrains = useMemo(() => [...new Set(models.flatMap((row) => row.powertrains).filter(Boolean))].sort(), [models]);
  const modelOptions = useMemo(() => filters.brand ? models.filter((row) => row.brandId === filters.brand) : models, [filters.brand, models]);

  function windowAvailable(period: string, window: MarketWindow) {
    if (!period) return false;
    return missingReportPeriods(resolveMarketWindow(period, window), available).length === 0;
  }
  function comparisonAvailable(period: string, window: MarketWindow, comparison: MarketComparison) {
    if (!windowAvailable(period, window)) return false;
    return missingReportPeriods(comparisonMarketWindow(resolveMarketWindow(period, window), comparison), available).length === 0;
  }

  async function loadMarket(next: FilterState, accessToken: string, rows: CoverageRowLike[]) {
    const requestId = ++requestIdRef.current;
    setStatus("loading");
    setMessage("");
    try {
      const body = await jsonFetch(marketPath(next), accessToken) as MarketResponse;
      // A newer request was dispatched while this one was in flight -- its
      // response (or the state it will set) is the authoritative one, so
      // this stale response must not touch state at all.
      if (requestIdRef.current !== requestId) return;

      const trendPeriods = rows.map((row) => periodKey(row.period)).filter((period) => period && period <= next.period).sort().slice(-6);
      const trendFilters = { ...next, window: "month" as MarketWindow, compare: "none" as const };
      const points = await Promise.all(trendPeriods.map(async (period) => {
        try {
          const trendBody = await jsonFetch(marketPath(trendFilters, period, 1, false, "oem_group"), accessToken) as MarketResponse;
          return { period, total: Number(trendBody.rows?.[0]?.market_total || 0) };
        } catch { return null; }
      }));
      if (requestIdRef.current !== requestId) return;

      // Main data, applied scope and trend settle together in one commit.
      // Flipping to "ready" (which re-enables every control and lifts the
      // dimming overlay) the moment the main response lands -- before trend
      // has caught up -- let the dashboard show the new ranking next to a
      // trend chart still drawn from the previous scope. Nothing becomes
      // visible as "current" until every piece of this request is in.
      const nextTrend = points.filter(Boolean) as TrendPoint[];
      setData(body);
      setApplied(next);
      setTrend(nextTrend);
      setTrendIncomplete(nextTrend.length !== trendPeriods.length);
      setStatus("ready");
    } catch (error: any) {
      if (requestIdRef.current !== requestId) return;
      if (error?.status === 401) {
        await browserDb()?.auth.signOut();
        router.replace("/member/login");
        return;
      }
      // A failed request must never leave the interactive controls (filters,
      // which drives dimension/period/window/compare and the filter-drawer
      // fields) representing a scope other than the one `applied`/`data`
      // still show. `applied` is only ever written by a successful commit
      // above, and the requestId guard just proved no newer request has
      // touched it since this one started, so it is exactly the last
      // committed state to roll the optimistic control update back to.
      if (applied) setFilters(applied);
      setStatus(error?.status === 403 ? "forbidden" : "error");
      const missing = error?.body?.missing_periods;
      setMessage(Array.isArray(missing) && missing.length ? `ช่วงข้อมูลไม่ครบ: ${missing.map(periodKey).join(", ")}` : (error?.message || "โหลดข้อมูลไม่สำเร็จ"));
    }
  }

  useEffect(() => {
    let cancelled = false;
    async function boot() {
      const db = browserDb();
      if (!db) { setStatus("error"); setMessage("deployment นี้ยังไม่ได้ตั้งค่า Supabase client"); return; }
      const { data: sessionData } = await db.auth.getSession();
      if (!sessionData.session) { router.replace("/member/login"); return; }
      const accessToken = sessionData.session.access_token;
      try {
        const body = await jsonFetch("/api/report/registration?dimension=coverage&limit=120", accessToken);
        if (cancelled) return;
        const rows = (body.rows || []) as CoverageRowLike[];
        const period = defaultMarketPeriod(rows);
        if (!period) throw new Error("ยังไม่มีข้อมูลจดทะเบียนในระบบ");
        const initial: FilterState = {
          period, window: "month", compare: "previous", dimension: "model",
          registrationType: "", brand: "", model: "", segment: "", bodyType: "", powertrain: "", allScopes: false,
        };
        setToken(accessToken);
        setCoverage(rows);
        setFilters(initial);
        await loadMarket(initial, accessToken, rows);
      } catch (error: any) {
        if (cancelled) return;
        setStatus(error?.status === 403 ? "forbidden" : "error");
        setMessage(error?.message || "โหลดข้อมูลไม่สำเร็จ");
      }
    }
    boot();
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router]);

  const movementByKey = useMemo(() => new Map((data?.comparison?.movement || []).map((row) => [row.entity_key, row])), [data]);
  const gainers = useMemo(() => (data?.comparison?.movement || []).filter((row) => Number(row.share_change_pp) > 0).sort((a, b) => Number(b.share_change_pp) - Number(a.share_change_pp)).slice(0, 6), [data]);
  const losers = useMemo(() => [...(data?.comparison?.movement || [])].filter((row) => Number(row.share_change_pp) < 0).sort((a, b) => Number(a.share_change_pp) - Number(b.share_change_pp)).slice(0, 6), [data]);
  const maxMove = Math.max(0.01, ...gainers.map((row) => Math.abs(Number(row.share_change_pp))), ...losers.map((row) => Math.abs(Number(row.share_change_pp))));
  const maxTrend = Math.max(1, ...trend.map((point) => point.total));
  const leader = data?.rows?.[0];
  const marketTotal = Number(leader?.market_total || 0);
  const mappingCoverage = Number(leader?.window_mapping_coverage_pct ?? coverageForPeriod(coverage, applied?.period || "")?.mapped_unit_pct ?? 0);
  const ignoredFilter = applied ? FILTER_BY_DIMENSION[applied.dimension] : undefined;
  const ignoredValue = ignoredFilter && applied ? applied[ignoredFilter] : null;
  const selectedCoverage = coverageForPeriod(coverage, applied?.period || filters.period);
  const topRows = (data?.rows || []).slice(0, 10);
  const maxRegistrations = Math.max(1, ...topRows.map((row) => Number(row.registrations || 0)));
  const dimensionLabel = DIMENSIONS.find((item) => item.value === applied?.dimension)?.label || "ตลาด";

  const trendPoints = useMemo(() => trend.map((point, index) => {
    const x = trend.length <= 1 ? 500 : 40 + index * (920 / (trend.length - 1));
    const y = 185 - (point.total / maxTrend) * 140;
    return { ...point, x, y };
  }), [trend, maxTrend]);
  const trendPolyline = trendPoints.map((point) => `${point.x},${point.y}`).join(" ");
  const trendArea = trendPoints.length ? `M ${trendPoints[0].x} 190 L ${trendPolyline.replaceAll(",", " ").replaceAll(" ", " ")} L ${trendPoints.at(-1)!.x} 190 Z` : "";
  const trendChange = trend.length > 1 && trend[0].total > 0 ? ((trend.at(-1)!.total - trend[0].total) / trend[0].total) * 100 : null;

  const scopeChips = useMemo(() => {
    if (!applied) return [] as Array<{ key: ScopeKey; label: string }>;
    const chips: Array<{ key: ScopeKey; label: string }> = [];
    if (applied.registrationType) chips.push({ key: "registrationType", label: applied.registrationType });
    if (applied.brand) chips.push({ key: "brand", label: brands.find((row) => row.id === applied.brand)?.name || applied.brand });
    if (applied.model) chips.push({ key: "model", label: models.find((row) => row.id === applied.model)?.name || applied.model });
    if (applied.segment) chips.push({ key: "segment", label: applied.segment });
    if (applied.bodyType) chips.push({ key: "bodyType", label: bodyLabel(applied.bodyType) });
    if (applied.powertrain) chips.push({ key: "powertrain", label: applied.powertrain });
    if (applied.allScopes) chips.push({ key: "allScopes", label: "ALL SCOPES" });
    return chips;
  }, [applied, brands, models]);

  const filterCount = scopeChips.length;

  async function applyNow(next: FilterState) {
    setFilters(next);
    if (!token || !next.period) return;
    await loadMarket(next, token, coverage);
  }

  async function changePeriod(period: string) {
    const nextWindow = windowAvailable(period, filters.window) ? filters.window : "month";
    const nextCompare = filters.compare !== "none" && comparisonAvailable(period, nextWindow, filters.compare) ? filters.compare : "none";
    await applyNow({ ...filters, period, window: nextWindow, compare: nextCompare });
  }

  async function changeWindow(window: MarketWindow) {
    const nextCompare = filters.compare !== "none" && comparisonAvailable(filters.period, window, filters.compare) ? filters.compare : "none";
    await applyNow({ ...filters, window, compare: nextCompare });
  }

  async function changeDimension(dimension: FilterState["dimension"]) {
    const next: FilterState = { ...filters, dimension };
    const ownFilter = FILTER_BY_DIMENSION[dimension];
    if (ownFilter) (next as any)[ownFilter] = "";
    await applyNow(next);
  }

  function changeBrand(brand: string) {
    setFilters((current) => {
      const selectedModel = models.find((row) => row.id === current.model);
      return { ...current, brand, model: selectedModel && brand && selectedModel.brandId !== brand ? "" : current.model };
    });
  }

  async function submitFilters(event: FormEvent) {
    event.preventDefault();
    if (!token || !filters.period) return;
    setShowFilters(false);
    await loadMarket(filters, token, coverage);
  }

  async function clearScope(key?: ScopeKey) {
    const base = { ...(applied || filters) };
    if (!key) {
      Object.assign(base, { registrationType: "", brand: "", model: "", segment: "", bodyType: "", powertrain: "", allScopes: false });
    } else if (key === "allScopes") base.allScopes = false;
    else (base as any)[key] = "";
    await applyNow(base);
  }

  async function drill(row: MarketRow) {
    const base = { ...(applied || filters) };
    const key = String(row.entity_key || "");
    if (!key || base.dimension === "model") return;
    if (base.dimension === "brand") Object.assign(base, { brand: key, model: "", dimension: "model" as const });
    if (base.dimension === "segment") Object.assign(base, { segment: key, model: "", dimension: "model" as const });
    if (base.dimension === "body_type") Object.assign(base, { bodyType: key, model: "", dimension: "model" as const });
    if (base.dimension === "powertrain") Object.assign(base, { powertrain: key, model: "", dimension: "model" as const });
    await applyNow(base);
  }

  function downloadCsv() {
    if (!data || !applied) return;
    const header = ["rank", "entity", "registrations", "market_share_pct", "share_change_pp", "rank_change"];
    const lines = [header.join(","), ...data.rows.map((row) => {
      const move = movementByKey.get(row.entity_key);
      return [row.market_rank, JSON.stringify(row.entity_label), row.registrations, row.market_share_pct, move?.share_change_pp ?? "", move?.rank_change ?? ""].join(",");
    })];
    const blob = new Blob(["\ufeff" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `tdr-market-${applied.dimension}-${applied.period}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  if (status === "loading" && !data) return <main className={styles.shell}><div className={styles.stateCard}>กำลังเปิด Market Intelligence…</div></main>;
  if (status === "forbidden") return <main className={styles.shell}><section className={styles.stateCard}><h1>บัญชีนี้ยังไม่มีสิทธิ์ Market Intelligence</h1><p>{message}</p><Link href="/pricing">ดูแพ็กเกจ</Link></section></main>;
  if (status === "error" && !data) return <main className={styles.shell}><section className={styles.stateCard}><h1>เปิด Market Intelligence ไม่สำเร็จ</h1><p>{message}</p><button onClick={() => location.reload()}>ลองใหม่</button></section></main>;

  const isLoading = status === "loading";

  return (
    <main className={styles.shell}>
      <section className={styles.commandBar}>
        <div className={styles.commandTop}>
          <nav className={styles.dimensionTabs} aria-label="จัดอันดับตาม">
            {DIMENSIONS.map((item) => <button key={item.value} type="button" disabled={isLoading} className={filters.dimension === item.value ? styles.activeTab : ""} onClick={() => changeDimension(item.value)}>{item.label}</button>)}
          </nav>

          <div className={styles.commandControls}>
            <select className={styles.periodSelect} aria-label="เดือนข้อมูล" value={filters.period} disabled={isLoading} onChange={(event) => changePeriod(event.target.value)}>
              {periods.map((period) => <option key={period} value={period}>{monthLabel(period)}{provisional.has(period) ? " · provisional" : ""}</option>)}
            </select>
            <div className={styles.windowTabs} aria-label="ช่วงเวลา">
              {WINDOWS.map((item) => <button key={item.value} type="button" className={filters.window === item.value ? styles.activeWindow : ""} disabled={isLoading || !windowAvailable(filters.period, item.value)} onClick={() => changeWindow(item.value)}>{item.compact}</button>)}
            </div>
            <select className={styles.compareSelect} aria-label="เปรียบเทียบ" value={filters.compare} disabled={isLoading} onChange={(event) => applyNow({ ...filters, compare: event.target.value as FilterState["compare"] })}>
              <option value="none">ไม่เทียบ</option>
              <option value="previous" disabled={!comparisonAvailable(filters.period, filters.window, "previous")}>เทียบช่วงก่อน (เฉพาะ Δ ส่วนแบ่ง/อันดับ)</option>
              <option value="yoy" disabled={!comparisonAvailable(filters.period, filters.window, "yoy")}>YoY (เฉพาะ Δ ส่วนแบ่ง/อันดับ)</option>
            </select>
            <button className={styles.filterButton} type="button" disabled={isLoading} onClick={() => setShowFilters(true)}>⌄ ตัวกรอง{filterCount ? ` (${filterCount})` : ""}</button>
            <button className={styles.exportButton} type="button" onClick={downloadCsv}>↓ Export CSV</button>
          </div>
        </div>

        <div className={styles.scopeRow}>
          <button type="button" className={styles.scopeHome} disabled={isLoading} onClick={() => clearScope()}>ตลาดทั้งหมด</button>
          {scopeChips.map((chip) => <button type="button" className={styles.scopeChip} key={chip.key} disabled={isLoading} onClick={() => clearScope(chip.key)}>{chip.label}<span>×</span></button>)}
          {isLoading && data ? <span className={styles.updating}>กำลังอัปเดต…</span> : null}
        </div>
      </section>

      {provisional.has(applied?.period || "") ? <div className={styles.danger}>เดือนนี้มีปริมาณต่ำกว่า 40% ของ baseline 6 เดือน จึงถือว่า provisional — อย่าใช้อันดับหรือส่วนแบ่งเป็นข้อสรุปตลาด</div> : null}
      {mappingCoverage < 90 ? <div className={styles.warning}>Canonical model mapping coverage {pct(mappingCoverage, 1)} — ranking ระดับ Model / Segment / Body / Powertrain จะไม่รวมหน่วยที่ map รุ่นไม่ได้</div> : null}
      {ignoredValue ? <div className={styles.info}>ระบบเปิด filter ของ dimension ที่กำลังจัดอันดับออกอัตโนมัติ เพื่อให้ denominator และคู่แข่งในตลาดถูกต้อง</div> : null}
      {message && status === "error" ? <div className={styles.danger}>{message}</div> : null}

      <div className={`${styles.dashboardBody} ${isLoading && data ? styles.isUpdating : ""}`} aria-busy={isLoading}>
      <section className={styles.primaryGrid}>
        <article className={`${styles.panel} ${styles.rankingPanel}`}>
          <div className={styles.panelHead}>
            <div><span>MARKET RANKING</span><h1>10 อันดับ · {dimensionLabel}</h1><small>{applied ? `${periodRangeLabel(data?.period_from, data?.period_to) || monthLabel(applied.period)} · ${WINDOWS.find((item) => item.value === applied.window)?.label}` : ""}</small></div>
            <div className={styles.metricToggle}><button type="button" className={rankingMetric === "share" ? styles.activeMetric : ""} onClick={() => setRankingMetric("share")}>Share</button><button type="button" className={rankingMetric === "registrations" ? styles.activeMetric : ""} onClick={() => setRankingMetric("registrations")}>ยอดจดทะเบียน</button></div>
          </div>

          <div className={styles.rankChart}>
            {topRows.map((row) => {
              const move = movementByKey.get(row.entity_key);
              const width = rankingMetric === "share"
                ? Math.max(1.5, Math.min(100, Number(row.market_share_pct || 0)))
                : Math.max(1.5, Number(row.registrations || 0) / maxRegistrations * 100);
              const drillable = applied?.dimension !== "model";
              return (
                <div className={styles.rankRow} key={row.entity_key}>
                  <span className={styles.rankNumber}>{row.market_rank}</span>
                  <button type="button" className={styles.entityButton} disabled={!drillable || isLoading} onClick={() => drill(row)} title={drillable ? "คลิกเพื่อเจาะลงเป็นรายรุ่น" : undefined}>{row.entity_label}</button>
                  <div className={styles.rankBar}><i style={{ width: `${width}%` }} /></div>
                  <b className={styles.rankValue}>{rankingMetric === "share" ? pct(row.market_share_pct, 1) : n(row.registrations)}</b>
                  <span className={styles.rankUnits}>{n(row.registrations)} คัน</span>
                  <span className={Number(move?.share_change_pp || 0) >= 0 ? styles.positive : styles.negative}>{data?.comparison ? pp(move?.share_change_pp) : "—"}</span>
                  <span className={styles.rankDelta}>{data?.comparison ? rankDelta(move?.rank_change) : "—"}</span>
                </div>
              );
            })}
          </div>
        </article>

        <aside className={`${styles.panel} ${styles.snapshot}`}>
          <div className={styles.panelHead}><div><span>MARKET SNAPSHOT</span><h2>ภาพรวมตลาด</h2></div></div>
          <div className={styles.snapshotList}>
            <div><span>ยอดจดในตลาดที่จัดอันดับได้</span><strong>{n(marketTotal)}</strong><small>คัน</small>{trendChange != null ? <em className={trendChange >= 0 ? styles.positive : styles.negative}>{trendChange >= 0 ? "▲" : "▼"} {Math.abs(trendChange).toFixed(1)}% จากต้นช่วงกราฟ</em> : null}</div>
            <div><span>อันดับ 1 ของตลาด</span><strong>{leader?.entity_label || "—"}</strong><small>{leader ? `${pct(leader.market_share_pct, 1)} share` : "ไม่มีข้อมูล"}</small></div>
            <div><span>เพิ่มส่วนแบ่งมากที่สุด</span><strong>{gainers[0]?.entity_label || "—"}</strong><small>{gainers[0] ? pp(gainers[0].share_change_pp) : "ไม่ได้เปิด comparison"}</small></div>
            <div><span>Mapping coverage</span><strong>{pct(mappingCoverage, 1)}</strong><small>{n(selectedCoverage?.total_registrations)} raw registrations · {applied?.period ? monthLabel(applied.period) : ""}</small></div>
          </div>
        </aside>
      </section>

      <section className={`${styles.panel} ${styles.trendPanel}`}>
        <div className={styles.panelHead}>
          <div><span>MARKET SIZE TREND</span><h2>ขนาดตลาดใน scope เดียวกัน · ย้อนหลังสูงสุด 6 เดือน</h2></div>
          {trendChange != null ? <strong className={trendChange >= 0 ? styles.positive : styles.negative}>{trendChange >= 0 ? "▲" : "▼"} {Math.abs(trendChange).toFixed(1)}%</strong> : null}
        </div>
        {trendPoints.length ? <>
          <div className={styles.lineChart}>
            <svg viewBox="0 0 1000 210" preserveAspectRatio="none" aria-label="แนวโน้มยอดจดทะเบียน">
              <line x1="40" y1="45" x2="960" y2="45" />
              <line x1="40" y1="90" x2="960" y2="90" />
              <line x1="40" y1="135" x2="960" y2="135" />
              <line x1="40" y1="185" x2="960" y2="185" />
              {trendArea ? <path d={trendArea} className={styles.trendArea} /> : null}
              <polyline points={trendPolyline} className={styles.trendLine} />
              {trendPoints.map((point) => <g key={point.period}><circle cx={point.x} cy={point.y} r="5"><title>{monthLabel(point.period)} · {n(point.total)} คัน</title></circle><text x={point.x} y={Math.max(18, point.y - 12)} textAnchor="middle">{n(point.total)}</text></g>)}
            </svg>
          </div>
          <div className={styles.trendLabels}>{trendPoints.map((point) => <span key={point.period}>{monthLabel(point.period)}</span>)}</div>
        </> : <div className={styles.empty}>ยังไม่มีข้อมูล trend สำหรับ scope นี้</div>}
        {trendIncomplete ? <div className={styles.info}>Trend ย้อนหลังโหลดได้ไม่ครบทุกเดือน — กราฟแสดงเฉพาะเดือนที่ดึงข้อมูลสำเร็จ</div> : null}
        <p className={styles.note}>กราฟนี้เป็น registration activity ตาม DLT ไม่ใช่ retail-sales ledger; ใช้ share และ relative position เป็นแกนหลักสำหรับอ่าน movement. กราฟแสดงยอดรายเดือนดิบของแต่ละช่วงเสมอ ไม่เปลี่ยนตามโหมด “เปรียบเทียบ” ด้านบน — ตัวเลือกนั้นมีผลเฉพาะ Δ ส่วนแบ่ง/อันดับที่ตารางและ SHARE MOVEMENT เท่านั้น</p>
      </section>

      {data?.comparison ? <section className={`${styles.panel} ${styles.movementPanel}`}>
        <div className={styles.panelHead}><div><span>SHARE MOVEMENT</span><h2>การเปลี่ยนแปลงส่วนแบ่งตลาด</h2><small>percentage-point change เทียบกับช่วงที่เลือก</small></div></div>
        <div className={styles.divergingChart}>
          <div className={`${styles.movementSide} ${styles.gainSide}`}><h3>รุ่นที่ส่วนแบ่งเพิ่มขึ้น</h3>{gainers.map((row) => <div className={styles.movementRow} key={row.entity_key}><span>{row.entity_label}</span><div className={styles.movementTrack}><i style={{ width: `${Math.abs(Number(row.share_change_pp)) / maxMove * 100}%` }} /></div><b>{pp(row.share_change_pp)}</b></div>)}</div>
          <div className={`${styles.movementSide} ${styles.lossSide}`}><h3>รุ่นที่ส่วนแบ่งลดลง</h3>{losers.map((row) => <div className={styles.movementRow} key={row.entity_key}><b>{pp(row.share_change_pp)}</b><div className={styles.movementTrack}><i style={{ width: `${Math.abs(Number(row.share_change_pp)) / maxMove * 100}%` }} /></div><span>{row.entity_label}</span></div>)}</div>
        </div>
      </section> : null}

      <details className={styles.details} open>
        <summary><span>▤ รายละเอียดข้อมูล</span><b>แสดงทั้งหมด</b></summary>
        <div className={styles.tableWrap}><table><thead><tr><th>#</th><th>{dimensionLabel}</th><th>ยอดจดทะเบียน</th><th>ส่วนแบ่งตลาด</th>{data?.comparison ? <><th>Δ ส่วนแบ่ง</th><th>Δ อันดับ</th></> : null}</tr></thead><tbody>{(data?.rows || []).map((row) => { const move = movementByKey.get(row.entity_key); return <tr key={row.entity_key}><td>{row.market_rank}</td><td><b>{row.entity_label}</b></td><td>{n(row.registrations)}</td><td>{pct(row.market_share_pct)}</td>{data?.comparison ? <><td className={Number(move?.share_change_pp || 0) >= 0 ? styles.positive : styles.negative}>{pp(move?.share_change_pp)}</td><td>{rankDelta(move?.rank_change)}</td></> : null}</tr>; })}</tbody></table></div>
      </details>
      </div>

      {showFilters ? <div className={styles.drawerBackdrop} onMouseDown={() => setShowFilters(false)}>
        <aside className={styles.filterDrawer} onMouseDown={(event) => event.stopPropagation()}>
          <div className={styles.drawerHead}><div><span>DEFINE MARKET</span><h2>ตัวกรองตลาด</h2></div><button type="button" onClick={() => setShowFilters(false)}>×</button></div>
          <form onSubmit={submitFilters}>
            <label><span>ประเภทรถ DLT</span><select value={filters.registrationType} onChange={(event) => setFilters((current) => ({ ...current, registrationType: event.target.value }))}><option value="">ทั้งหมด</option><option value="RY1">RY1</option><option value="RY2">RY2</option><option value="RY3">RY3</option></select></label>
            <label><span>แบรนด์</span><select value={filters.brand} onChange={(event) => changeBrand(event.target.value)}><option value="">ทุกแบรนด์</option>{brands.map((brand) => <option key={brand.id} value={brand.id}>{brand.name}</option>)}</select></label>
            <label><span>รุ่น</span><select value={filters.model} onChange={(event) => setFilters((current) => ({ ...current, model: event.target.value }))}><option value="">ทุกรุ่น</option>{modelOptions.map((model) => <option key={model.id} value={model.id}>{model.brandName} · {model.name}</option>)}</select></label>
            <label><span>Segment</span><select value={filters.segment} onChange={(event) => setFilters((current) => ({ ...current, segment: event.target.value }))}><option value="">ทุก Segment</option>{segments.map((segment) => <option key={segment}>{segment}</option>)}</select></label>
            <label><span>ตัวถัง</span><select value={filters.bodyType} onChange={(event) => setFilters((current) => ({ ...current, bodyType: event.target.value }))}><option value="">ทุกตัวถัง</option>{bodyTypes.map((body) => <option key={body} value={body}>{bodyLabel(body)}</option>)}</select></label>
            <label><span>Powertrain</span><select value={filters.powertrain} onChange={(event) => setFilters((current) => ({ ...current, powertrain: event.target.value }))}><option value="">ทุก Powertrain</option>{powertrains.map((powertrain) => <option key={powertrain}>{powertrain}</option>)}</select></label>
            <label className={styles.disabledField}><span>Price range</span><select disabled><option>รอ canonical LIST_PRICE coverage</option></select></label>
            <label className={styles.checkbox}><input type="checkbox" checked={filters.allScopes} onChange={(event) => setFilters((current) => ({ ...current, allScopes: event.target.checked }))} /><span>รวม NICHE / GREY / COMMERCIAL</span></label>
            <div className={styles.drawerActions}><button type="button" onClick={() => setFilters((current) => ({ ...current, registrationType: "", brand: "", model: "", segment: "", bodyType: "", powertrain: "", allScopes: false }))}>ล้างตัวกรอง</button><button type="submit" disabled={status === "loading"}>ดูตลาดนี้</button></div>
          </form>
        </aside>
      </div> : null}
    </main>
  );
}
