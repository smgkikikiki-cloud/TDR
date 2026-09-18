import Link from "next/link";
import {
  compareMarketSliceRows,
  comparisonMarketWindow,
  isMarketComparison,
  isMarketDimension,
  isMarketWindow,
  missingReportPeriods,
  normalizeReportPeriod,
  resolveMarketWindow,
  type MarketComparison,
  type MarketDimension,
  type MarketSliceFilters,
  type MarketWindow,
} from "@/lib/registration-market";
import {
  getAdminMarketOptions,
  getAdminRegistrationCoverage,
  getAdminRegistrationMarketSlice,
} from "@/lib/admin-registration-market";
import { defaultMarketPeriod, periodKey, provisionalMarketPeriods } from "@/lib/member-market";
import styles from "./market.module.css";

type SearchParams = Record<string, string | string[] | undefined>;
const DIMENSIONS: Array<[MarketDimension, string]> = [
  ["brand", "Brand"], ["oem_group", "OEM group"], ["model", "Model"],
  ["segment", "Segment"], ["body_type", "Body"], ["powertrain", "Powertrain"],
  ["market_position", "Market position*"], ["import_type", "CBU / CKD"],
  ["origin_country", "Production country"], ["brand_origin", "Brand origin"],
  ["registration_type", "DLT class"], ["market_scope", "Market scope"],
];
const WINDOWS: Array<[MarketWindow, string]> = [
  ["month", "Month"], ["rolling3", "Rolling 3M"], ["rolling6", "Rolling 6M"],
  ["rolling12", "Rolling 12M"], ["ytd", "YTD"],
];
const SEGMENTS = ["A", "B", "C", "D", "E", "F", "UNKNOWN"];
const BODY_TYPES = ["HATCHBACK", "SEDAN", "CROSSOVER", "PPV", "OFFROAD", "COUPE", "MPV", "PICKUP", "WAGON", "VAN", "TRUCK", "OTHER", "UNKNOWN"];
const POWERTRAINS = ["ICE", "HEV", "PHEV", "REEV", "BEV", "FCEV", "MIXED", "UNKNOWN"];

function first(value: string | string[] | undefined) { return Array.isArray(value) ? value[0] : value; }
function on(value: string | string[] | undefined) { return ["1", "true", "yes", "on"].includes(String(first(value) || "").toLowerCase()); }
function one(value: string | string[] | undefined) { const out = String(first(value) || "").trim(); return out || ""; }
function n(value: unknown) { return Number(value || 0).toLocaleString("th-TH"); }
function pct(value: unknown) { const number = Number(value); return Number.isFinite(number) ? `${number.toFixed(2)}%` : "—"; }
function pp(value: unknown) { const number = Number(value); return Number.isFinite(number) ? `${number > 0 ? "+" : ""}${number.toFixed(2)} pp` : "—"; }
function monthLabel(value: string) {
  const normalized = normalizeReportPeriod(value);
  if (!normalized) return value;
  return new Intl.DateTimeFormat("th-TH", { month: "short", year: "numeric" }).format(new Date(`${normalized}T00:00:00Z`));
}
function active(value: string) { return value && value !== "ALL" ? [value] : undefined; }
function hrefWith(params: URLSearchParams, changes: Record<string, string | null>) {
  const next = new URLSearchParams(params);
  for (const [key, value] of Object.entries(changes)) value == null ? next.delete(key) : next.set(key, value);
  return `/admin/market?${next.toString()}`;
}

export default async function AdminMarketPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const sp = await searchParams;
  const [coverage, options] = await Promise.all([getAdminRegistrationCoverage(), getAdminMarketOptions()]);
  const periods = coverage.map((row: any) => periodKey(row.period)).filter(Boolean).sort();
  const available = new Set(periods.map((p) => normalizeReportPeriod(p)).filter(Boolean) as string[]);
  const provisional = provisionalMarketPeriods(coverage as any[]);
  const defaultPeriod = defaultMarketPeriod(coverage as any[]) || periods.at(-1) || "";
  const requestedPeriod = one(sp.period);
  const period = periods.includes(requestedPeriod) ? requestedPeriod : defaultPeriod;
  const rawDimension = one(sp.dimension);
  const dimension: MarketDimension = isMarketDimension(rawDimension) ? rawDimension : "model";
  const rawWindow = one(sp.window);
  const window: MarketWindow = isMarketWindow(rawWindow) ? rawWindow : "month";
  const rawCompare = one(sp.compare);
  const comparison: MarketComparison | null = isMarketComparison(rawCompare) ? rawCompare : null;
  const allScopes = on(sp.all_scopes);
  const includeUnmapped = on(sp.include_unmapped);

  const brand = one(sp.brand); const model = one(sp.model); const segment = one(sp.segment);
  const bodyType = one(sp.body_type); const powertrain = one(sp.powertrain); const registrationType = one(sp.registration_type);
  const oemGroup = one(sp.oem_group); const marketPosition = one(sp.market_position); const importType = one(sp.import_type);
  const originCountry = one(sp.origin_country); const brandOrigin = one(sp.brand_origin);

  const filters: MarketSliceFilters = {
    brandIds: active(brand), modelIds: active(model), segments: active(segment), bodyTypes: active(bodyType),
    powertrains: active(powertrain), registrationTypes: active(registrationType), oemGroups: active(oemGroup),
    marketPositions: active(marketPosition), importTypes: active(importType), originCountries: active(originCountry),
    brandOrigins: active(brandOrigin), marketScopes: allScopes ? undefined : ["CORE", "MIXED"],
  };

  const currentWindow = period ? resolveMarketWindow(period, window) : null;
  const missingCurrent = currentWindow ? missingReportPeriods(currentWindow, available) : [];
  const rows = currentWindow && !missingCurrent.length
    ? await getAdminRegistrationMarketSlice({ dimension, window: currentWindow, filters, includeUnmapped, limit: 500 }) : [];

  let movement: ReturnType<typeof compareMarketSliceRows> = [];
  let comparisonMissing: string[] = [];
  let comparisonWindow = null as null | { from: string; to: string };
  if (comparison && currentWindow && !missingCurrent.length) {
    comparisonWindow = comparisonMarketWindow(currentWindow, comparison);
    comparisonMissing = missingReportPeriods(comparisonWindow, available);
    if (!comparisonMissing.length) {
      const previousRows = await getAdminRegistrationMarketSlice({ dimension, window: comparisonWindow, filters, includeUnmapped, limit: 500 });
      movement = compareMarketSliceRows(previousRows, rows);
    }
  }

  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(sp)) {
    const v = first(value); if (v) params.set(key, v);
  }
  if (!params.has("period") && period) params.set("period", period);
  if (!params.has("dimension")) params.set("dimension", dimension);
  if (!params.has("window")) params.set("window", window);

  const movementByKey = new Map(movement.map((row) => [row.entity_key, row]));
  const gainers = movement.filter((row) => row.share_change_pp > 0).slice(0, 10);
  const losers = [...movement].filter((row) => row.share_change_pp < 0).sort((a, b) => a.share_change_pp - b.share_change_pp).slice(0, 10);
  const maxMove = Math.max(.01, ...gainers.map((row) => Math.abs(row.share_change_pp)), ...losers.map((row) => Math.abs(row.share_change_pp)));
  const leader = rows[0];
  const currentCoverage = coverage.find((row: any) => periodKey(row.period) === period) as any;
  const modelOptions = brand ? options.models.filter((row: any) => row.brandId === brand) : options.models;

  const trendPeriods = periods.filter((p) => p <= period).slice(-12);
  const trend = currentWindow && !missingCurrent.length ? await Promise.all(trendPeriods.map(async (p) => {
    const trendRows = await getAdminRegistrationMarketSlice({
      dimension, window: resolveMarketWindow(p, "month"), filters, includeUnmapped, limit: 1,
    });
    return { period: p, total: Number(trendRows[0]?.market_total || 0) };
  })) : [];
  const maxTrend = Math.max(1, ...trend.map((point) => point.total));

  return <div className={styles.bench}>
    <div className="adminHeader"><div><small>ADMIN BENCH · FULL MARKET INTELLIGENCE</small><h1>ตลาด / Share / Movement</h1><p>พอร์ตจาก analyst deck เดิม แต่ใช้ registration facts + active canonical Vehicle Master ของ TDR โดยตรง. หน้านี้เป็นหลังบ้านเต็ม; `/member/market` คือเวอร์ชันที่ตัดให้เซลใช้.</p></div><Link className="adminPrimaryLink" href="/member/market">เปิด Paid workspace ↗</Link></div>

    <div className={styles.tabs}><Link href="/admin/market">Market bench</Link><Link href="/admin/regional-market">Regional market (coming soon)</Link><Link href="/admin/registrations">Registration ingest / review</Link><Link href="/admin/prices">Prices / review</Link><Link href="/admin/data-quality">Data quality</Link></div>

    <form className={styles.filters} method="get">
      <label><span>เดือนอ้างอิง</span><select name="period" defaultValue={period}>{periods.map((p) => <option key={p} value={p}>{monthLabel(p)}{provisional.has(p) ? " · PROVISIONAL" : ""}</option>)}</select></label>
      <label><span>Window</span><select name="window" defaultValue={window}>{WINDOWS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label><span>Compare / rank by</span><select name="dimension" defaultValue={dimension}>{DIMENSIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label><span>Comparison</span><select name="compare" defaultValue={comparison || ""}><option value="">None</option><option value="previous">Previous window</option><option value="yoy">Same window last year</option></select></label>

      <label><span>DLT class</span><select name="registration_type" defaultValue={registrationType}><option value="">ALL</option>{["RY1","RY2","RY3"].map((v) => <option key={v}>{v}</option>)}</select></label>
      <label><span>Brand</span><select name="brand" defaultValue={brand}><option value="">ALL</option>{options.brands.map((row: any) => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
      <label className={styles.wide}><span>Model</span><select name="model" defaultValue={model}><option value="">ALL</option>{modelOptions.map((row: any) => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
      <label><span>Segment</span><select name="segment" defaultValue={segment}><option value="">ALL</option>{SEGMENTS.map((v) => <option key={v}>{v}</option>)}</select></label>
      <label><span>Body</span><select name="body_type" defaultValue={bodyType}><option value="">ALL</option>{BODY_TYPES.map((v) => <option key={v}>{v}</option>)}</select></label>
      <label><span>Powertrain</span><select name="powertrain" defaultValue={powertrain}><option value="">ALL</option>{POWERTRAINS.map((v) => <option key={v}>{v}</option>)}</select></label>
      <label className={styles.blocked}><span>Price band · WAITING PERIOD PRICE</span><select disabled><option>ยังไม่เปิด — Price Ledger serving history ไม่ครบ</option></select></label>

      <label><span>OEM group</span><input name="oem_group" defaultValue={oemGroup} placeholder="เช่น Toyota Motor" /></label>
      <label className={styles.blocked}><span>Market position* · CURRENT SNAPSHOT</span><input name="market_position" defaultValue={marketPosition} placeholder="ใช้วินิจฉัยเท่านั้น" /></label>
      <label><span>CBU / CKD · PERIOD-AWARE</span><input name="import_type" defaultValue={importType} placeholder="CBU / CKD / SKD" /></label>
      <label><span>Production country · PERIOD-AWARE</span><input name="origin_country" defaultValue={originCountry} placeholder="TH / CN / ID…" /></label>
      <label><span>Brand origin</span><input name="brand_origin" defaultValue={brandOrigin} placeholder="TH / JP / CN…" /></label>

      <div className={styles.checks}><label><input type="checkbox" name="all_scopes" defaultChecked={allScopes}/> รวม NICHE / GREY / COMMERCIAL</label><label><input type="checkbox" name="include_unmapped" defaultChecked={includeUnmapped}/> รวม unmapped/raw buckets</label></div>
      <div className={styles.actions}><span>Dimension ที่กำลัง rank จะเปิด filter ของตัวเองอัตโนมัติ เพื่อให้ denominator มีคู่แข่งจริง.</span><div><Link className={styles.csv} href={`/api/admin/market/export?${params.toString()}`}>CSV</Link> <button>Apply</button></div></div>
    </form>

    {provisional.has(period) ? <div className={styles.warning}><b>PROVISIONAL MONTH:</b> เดือน {period} ต่ำกว่า 40% ของ trailing six-month median. ดู raw data ได้ แต่ share/rank ไม่ควรใช้อ้างอิงจน source settle.</div> : null}
    {missingCurrent.length ? <div className={styles.warning}>Window นี้ข้อมูลไม่ครบ: {missingCurrent.map(periodKey).join(", ")} — ไม่สร้าง ranking จากเดือนที่หาย.</div> : null}
    {comparisonMissing.length ? <div className={styles.warning}>Comparison ถูกปิดเพราะ window ฝั่งเทียบขาด: {comparisonMissing.map(periodKey).join(", ")}</div> : null}
    {marketPosition ? <div className={styles.warning}><b>* Current-snapshot diagnostic:</b> market position ยังไม่ได้เป็น period-aware state. Import route และ production country ใช้ historical year baseline + reviewed monthly change-points แล้ว.</div> : null}

    <div className={styles.kpis}>
      <article><span>Registrations in competitive scope</span><strong>{n(leader?.market_total)}</strong><small>{currentWindow ? `${periodKey(currentWindow.from)} → ${periodKey(currentWindow.to)}` : "—"}</small></article>
      <article><span>Entities ranked</span><strong>{rows.length}</strong><small>{DIMENSIONS.find(([v]) => v === dimension)?.[1]}</small></article>
      <article><span>Leader</span><strong>{leader?.entity_label || "—"}</strong><small>{pct(leader?.market_share_pct)} share</small></article>
      <article><span>Model mapping coverage</span><strong>{leader ? pct(leader.window_mapping_coverage_pct) : currentCoverage ? `${Number(currentCoverage.mapped_unit_pct || 0).toFixed(1)}%` : "—"}</strong><small>{currentCoverage ? `${n(currentCoverage.mapped_registrations)} / ${n(currentCoverage.total_registrations)} units` : "no coverage row"}</small></article>
    </div>

    <section className={styles.panel}><div className={styles.panelHead}><div><small>STRUCTURE</small><h2>Ranking / share</h2></div><span>{allScopes ? "ALL scopes" : "CORE + honest MIXED residual"}{includeUnmapped ? " · includes raw" : ""}</span></div><div className={styles.table}><table><thead><tr><th>#</th><th>Entity</th><th>Registrations</th><th>Share</th>{comparison ? <><th>Δ units</th><th>Δ share</th><th>Rank Δ</th></> : null}</tr></thead><tbody>{rows.map((row) => { const move = movementByKey.get(row.entity_key); return <tr key={row.entity_key}><td>{row.market_rank}</td><td><b>{row.entity_label}</b></td><td>{n(row.registrations)}</td><td>{pct(row.market_share_pct)}</td>{comparison ? <><td className={Number(move?.units_change || 0) >= 0 ? styles.positive : styles.negative}>{move ? `${move.units_change > 0 ? "+" : ""}${n(move.units_change)}` : "—"}</td><td className={Number(move?.share_change_pp || 0) >= 0 ? styles.positive : styles.negative}>{move ? pp(move.share_change_pp) : "—"}</td><td>{move?.rank_change == null ? "—" : `${move.rank_change > 0 ? "+" : ""}${move.rank_change}`}</td></> : null}</tr>; })}</tbody></table></div></section>

    {comparison && movement.length ? <section className={styles.panel}><div className={styles.panelHead}><div><small>MOVEMENT</small><h2>Share gainers / losers</h2></div><span>{comparisonWindow ? `${periodKey(comparisonWindow.from)}–${periodKey(comparisonWindow.to)} → ${periodKey(currentWindow!.from)}–${periodKey(currentWindow!.to)}` : ""}</span></div><div className={styles.movement}><div className={styles.moveCol}><h3>Gainers</h3>{gainers.map((row) => <div className={styles.moveRow} key={row.entity_key}><b>{row.entity_label}</b><div className={styles.bar}><i style={{width:`${100*Math.abs(row.share_change_pp)/maxMove}%`}}/></div><span className={styles.positive}>{pp(row.share_change_pp)}</span></div>)}</div><div className={styles.moveCol}><h3>Losers</h3>{losers.map((row) => <div className={styles.moveRow} key={row.entity_key}><b>{row.entity_label}</b><div className={`${styles.bar} ${styles.negativeBar}`}><i style={{width:`${100*Math.abs(row.share_change_pp)/maxMove}%`}}/></div><span className={styles.negative}>{pp(row.share_change_pp)}</span></div>)}</div></div></section> : null}

    <section className={styles.panel}><div className={styles.panelHead}><div><small>RAW TREND</small><h2>12 เดือนที่มีใน serving DB</h2></div><span>registration history 2021-01 → 2026-08 is backfilled</span></div><div className={styles.trend}>{trend.map((point) => <div className={styles.trendItem} key={point.period}><div className={styles.trendBar} style={{height:`${Math.max(2,100*point.total/maxTrend)}%`}}/><span>{periodKey(point.period)}</span></div>)}</div></section>

    <div className={styles.warning}><b>Legacy parity blockers ที่ยังห้าม retire Streamlit:</b> period-aware Price band และ Regional Market/province grain. Import/origin historical state กับ registration history ย้ายแล้ว; retirement gate จะเขียวเมื่อ active release publish historical state สำเร็จ.</div>
  </div>;
}
