"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { browserDb } from "@/lib/supabase-browser";
import { bodyLabel } from "@/lib/body-labels";
import {
  comparisonMarketWindow,
  missingReportPeriods,
  normalizeReportPeriod,
  resolveMarketWindow,
  type MarketComparison,
  type MarketWindow,
} from "@/lib/registration-market";
import { coverageForPeriod, defaultMarketPeriod, periodKey, provisionalMarketPeriods, type CoverageRowLike } from "@/lib/member-market";
import styles from "./market.module.css";

type BrandOption = { id: string; name: string; oemGroup: string | null; brandOrigin: string | null };
type ModelOption = {
  id: string; name: string; brandId: string; brandName: string; segment: string | null; bodyType: string | null;
  powertrains: string[]; importType: string | null; originCountry: string | null; marketScope: string | null;
};
type MarketRow = Record<string, any>;
type MarketResponse = {
  dimension: string;
  period: string;
  window: string;
  period_from: string;
  period_to: string;
  rows: MarketRow[];
  comparison: null | { mode: MarketComparison; window: { from: string; to: string }; movement: MarketRow[] };
  trend: TrendPoint[];
  quota: { used: number; limit: number | null; remaining: number | null; resets_at: string };
};
type MarketDimensionValue =
  "model" | "brand" | "segment" | "body_type" | "powertrain"
  | "oem_group" | "import_type" | "origin_country" | "brand_origin" | "registration_type" | "market_scope";
type FilterState = {
  period: string;
  window: MarketWindow;
  compare: "none" | MarketComparison;
  dimension: MarketDimensionValue;
  registrationType: string;
  brand: string;
  model: string;
  segment: string;
  bodyType: string;
  powertrain: string;
  oemGroup: string;
  importType: string;
  originCountry: string;
  brandOrigin: string;
  allScopes: boolean;
};
type TrendPoint = { period: string; total: number };

// B2B buyers of this data care about MiT/CBU-CKD, Chinese OEM penetration and
// market positioning as much as -- often more than -- body type, so these
// carry the same weight in the ranking picker as the original five. The
// engine (app/api/report/market/route.ts, lib/registration-market.ts) has
// always accepted all of these; only the picker was five wide. Market
// position is deliberately left out for now -- the admin surface marks it
// "current snapshot, diagnosis only" (not period-aware like the others).
const DIMENSIONS: Array<{ value: FilterState["dimension"]; label: string }> = [
  { value: "model", label: "รุ่น" },
  { value: "brand", label: "แบรนด์" },
  { value: "segment", label: "Segment" },
  { value: "body_type", label: "ตัวถัง" },
  { value: "powertrain", label: "Powertrain" },
  { value: "oem_group", label: "OEM Group" },
  { value: "import_type", label: "CBU / CKD" },
  { value: "origin_country", label: "ประเทศผลิต" },
  { value: "brand_origin", label: "ต้นกำเนิดแบรนด์" },
  { value: "registration_type", label: "ประเภทรถ DLT" },
  { value: "market_scope", label: "Market Scope" },
];
const WINDOWS: Array<{ value: MarketWindow; label: string }> = [
  { value: "month", label: "เดือน" },
  { value: "rolling3", label: "3 เดือน" },
  { value: "rolling6", label: "6 เดือน" },
  { value: "rolling12", label: "12 เดือน" },
  { value: "ytd", label: "YTD" },
];
/** What this account may ask for, as the last response reported it. Until the
 *  first response arrives nothing is marked paid: guessing would either
 *  disable a control a paid reader owns or dangle one a free reader does not. */
type PlanCaps = {
  tier: string;
  model_grain: boolean;
  windows: string[] | null;
  comparisons: string[] | null;
  filters: boolean;
  history_from: string | null;
};
const PAID = " · แพ็กเกจเสียค่าบริการ";

const FILTER_BY_DIMENSION: Record<string, keyof FilterState | undefined> = {
  brand: "brand", model: "model", segment: "segment", body_type: "bodyType", powertrain: "powertrain",
  oem_group: "oemGroup", import_type: "importType", origin_country: "originCountry", brand_origin: "brandOrigin",
  registration_type: "registrationType",
  // market_scope has no single-value filter counterpart -- the "allScopes"
  // checkbox is a coarse CORE/ALL toggle, not a select the same-dimension
  // auto-hide logic (ignoredFilter/ignoredValue below) applies to.
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
function monthLabel(period: string) {
  const normalized = normalizeReportPeriod(period);
  if (!normalized) return period;
  return new Intl.DateTimeFormat("th-TH", { month: "short", year: "2-digit" }).format(new Date(`${normalized}T00:00:00Z`));
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
  const params = new URLSearchParams({
    dimension,
    period,
    window: filters.window,
    limit: String(limit),
  });
  if (includeComparison && filters.compare !== "none") params.set("compare", filters.compare);
  if (filters.registrationType) params.set("registration_type", filters.registrationType);
  if (filters.brand) params.set("brand", filters.brand);
  if (filters.model) params.set("model", filters.model);
  if (filters.segment) params.set("segment", filters.segment);
  if (filters.bodyType) params.set("body_type", filters.bodyType);
  if (filters.powertrain) params.set("powertrain", filters.powertrain);
  if (filters.oemGroup) params.set("oem_group", filters.oemGroup);
  if (filters.importType) params.set("import_type", filters.importType);
  if (filters.originCountry) params.set("origin_country", filters.originCountry);
  if (filters.brandOrigin) params.set("brand_origin", filters.brandOrigin);
  if (filters.allScopes) params.set("market_scope", "ALL");
  return `/api/report/market?${params.toString()}`;
}

/** The scope-filter half of FilterState, reset to nothing selected -- shared
 *  by the initial state, boot()'s first load and the "ล้าง scope" button so
 *  the three can't drift apart on which fields count as "scope". */
const EMPTY_SCOPE_FILTERS = {
  registrationType: "", brand: "", model: "", segment: "", bodyType: "", powertrain: "",
  oemGroup: "", importType: "", originCountry: "", brandOrigin: "", allScopes: false,
} as const;

export function MarketWorkspace({ brands, models }: { brands: BrandOption[]; models: ModelOption[] }) {
  const router = useRouter();
  const [token, setToken] = useState("");
  const [coverage, setCoverage] = useState<CoverageRowLike[]>([]);
  const [filters, setFilters] = useState<FilterState>({
    period: "", window: "month", compare: "previous", dimension: "model", ...EMPTY_SCOPE_FILTERS,
  });
  const [applied, setApplied] = useState<FilterState | null>(null);
  const [data, setData] = useState<MarketResponse | null>(null);
  const [trend, setTrend] = useState<TrendPoint[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "forbidden" | "activation" | "quota" | "upgrade" | "error">("loading");
  const [plan, setPlan] = useState<PlanCaps | null>(null);
  const [message, setMessage] = useState("");

  const periods = useMemo(() => coverage.map((row) => periodKey(row.period)).filter(Boolean).sort(), [coverage]);
  const available = useMemo(() => new Set(periods.map((period) => normalizeReportPeriod(period)).filter(Boolean) as string[]), [periods]);
  const provisional = useMemo(() => provisionalMarketPeriods(coverage), [coverage]);
  const bodyTypes = useMemo(() => [...new Set(models.map((row) => row.bodyType).filter(Boolean) as string[])].sort(), [models]);
  const segments = useMemo(() => [...new Set(models.map((row) => row.segment).filter(Boolean) as string[])].sort(), [models]);
  const powertrains = useMemo(() => [...new Set(models.flatMap((row) => row.powertrains).filter(Boolean))].sort(), [models]);
  const importTypes = useMemo(() => [...new Set(models.map((row) => row.importType).filter(Boolean) as string[])].sort(), [models]);
  const originCountries = useMemo(() => [...new Set(models.map((row) => row.originCountry).filter(Boolean) as string[])].sort(), [models]);
  const oemGroups = useMemo(() => [...new Set(brands.map((row) => row.oemGroup).filter(Boolean) as string[])].sort(), [brands]);
  const brandOrigins = useMemo(() => [...new Set(brands.map((row) => row.brandOrigin).filter(Boolean) as string[])].sort(), [brands]);
  const modelOptions = useMemo(() => filters.brand ? models.filter((row) => row.brandId === filters.brand) : models, [filters.brand, models]);

  function windowAvailable(period: string, window: MarketWindow) {
    if (!period) return false;
    return missingReportPeriods(resolveMarketWindow(period, window), available).length === 0;
  }
  function comparisonAvailable(period: string, window: MarketWindow, comparison: MarketComparison) {
    if (!windowAvailable(period, window)) return false;
    return missingReportPeriods(comparisonMarketWindow(resolveMarketWindow(period, window), comparison), available).length === 0;
  }

  async function loadMarket(next: FilterState, accessToken: string) {
    setStatus("loading");
    setMessage("");
    // One "Update market" click = one HTTP request = one sales_query
    // quota unit, consumed exactly once server-side. The trend sparkline
    // (previously up to 6 separate client-side fetches trying to share one
    // quota unit via a client-supplied action id) is now computed
    // server-side in this same request and returned as `trend`.
    try {
      const body = await jsonFetch(marketPath(next), accessToken) as MarketResponse;
      setData(body);
      if ((body as any).plan) setPlan((body as any).plan as PlanCaps);
      setApplied(next);
      setTrend(body.trend || []);
      setStatus("ready");
    } catch (error: any) {
      if (error?.status === 401) {
        await browserDb()?.auth.signOut();
        router.replace("/member/login");
        return;
      }
      if (error?.status === 429) {
        setStatus("quota");
        setMessage(error?.message || "ใช้โควตา Sales Tools ของวันนี้ครบแล้ว");
        return;
      }
      if (error?.status === 403 && error?.body?.upgrade_required) {
        setStatus("upgrade");
        setMessage(error?.message || "");
        return;
      }
      if (error?.status === 403) {
        setStatus(String(error?.message || "").includes("activation") ? "activation" : "forbidden");
        setMessage(error?.message || "");
        return;
      }
      setStatus("error");
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
          period, window: "month", compare: "previous", dimension: "model", ...EMPTY_SCOPE_FILTERS,
        };
        setToken(accessToken); setCoverage(rows); setFilters(initial);
        await loadMarket(initial, accessToken);
      } catch (error: any) {
        if (cancelled) return;
        if (error?.status === 403) {
          setStatus(String(error?.message || "").includes("activation") ? "activation" : "forbidden");
        } else {
          setStatus("error");
        }
        setMessage(error?.message || "โหลดข้อมูลไม่สำเร็จ");
      }
    }
    boot();
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router]);

  const movementByKey = useMemo(() => new Map((data?.comparison?.movement || []).map((row) => [row.entity_key, row])), [data]);
  const gainers = useMemo(() => (data?.comparison?.movement || []).filter((row) => Number(row.share_change_pp) > 0).slice(0, 6), [data]);
  const losers = useMemo(() => [...(data?.comparison?.movement || [])].filter((row) => Number(row.share_change_pp) < 0).sort((a, b) => Number(a.share_change_pp) - Number(b.share_change_pp)).slice(0, 6), [data]);
  const maxMove = Math.max(0.01, ...gainers.map((row) => Math.abs(Number(row.share_change_pp))), ...losers.map((row) => Math.abs(Number(row.share_change_pp))));
  const maxTrend = Math.max(1, ...trend.map((point) => point.total));
  const leader = data?.rows?.[0];
  const marketTotal = Number(leader?.market_total || 0);
  const mappingCoverage = Number(leader?.window_mapping_coverage_pct ?? coverageForPeriod(coverage, applied?.period || "")?.mapped_unit_pct ?? 0);
  const ignoredFilter = applied ? FILTER_BY_DIMENSION[applied.dimension] : undefined;
  const ignoredValue = ignoredFilter && applied ? applied[ignoredFilter] : null;
  const selectedCoverage = coverageForPeriod(coverage, applied?.period || filters.period);

  function changePeriod(period: string) {
    const nextWindow: MarketWindow = "month";
    setFilters((current) => ({
      ...current, period, window: nextWindow,
      compare: comparisonAvailable(period, nextWindow, "previous") ? "previous" : "none",
    }));
  }
  function changeWindow(window: MarketWindow) {
    setFilters((current) => ({
      ...current, window,
      compare: current.compare !== "none" && comparisonAvailable(current.period, window, current.compare) ? current.compare : "none",
    }));
  }
  function changeBrand(brand: string) {
    setFilters((current) => {
      const selectedModel = models.find((row) => row.id === current.model);
      return { ...current, brand, model: selectedModel && brand && selectedModel.brandId !== brand ? "" : current.model };
    });
  }
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!token || !filters.period) return;
    await loadMarket(filters, token);
  }
  async function signOut() { await browserDb()?.auth.signOut(); router.replace("/member/login"); }
  // Raw CSV export used to live here (client-only Blob download of
  // `data.rows`, no server visibility, no quota). Removed: no self-service
  // tier may expose a raw structured-data download under the product's
  // raw-data-safety policy -- this was the one member-facing raw-export
  // path found in the codebase (see the delivery report).

  if (status === "loading" && !data) return <main className={styles.shell}><div className={styles.stateCard}>กำลังเปิด Market Comparison…</div></main>;
  if (status === "activation") return <main className={styles.shell}><section className={styles.stateCard}><h1>ยืนยันตัวตนก่อนใช้ Sales Tools</h1><p>ต้องยืนยันอีเมล ยืนยันเบอร์มือถือ และกรอกโปรไฟล์ให้ครบก่อน</p><Link href="/member/profile">ไปที่หน้าโปรไฟล์ →</Link></section></main>;
  if (status === "forbidden") return <main className={styles.shell}><section className={styles.stateCard}><h1>บัญชีนี้ยังไม่มีสิทธิ์ Registration Intelligence</h1><p>{message}</p><Link href="/reports">ดูแพ็กเกจ TDR Report</Link></section></main>;
  if (status === "upgrade") return <main className={styles.shell}><section className={styles.stateCard}><h1>อยู่ในแพ็กเกจแบบเสียค่าบริการ</h1><p>{message}</p><Link href="/pricing">ดูแพ็กเกจ</Link></section></main>;
  if (status === "quota") return <main className={styles.shell}><section className={styles.stateCard}><h1>ใช้โควตา Sales Tools ของวันนี้ครบแล้ว</h1><p>{message}</p><Link href="/pricing">ดูแพ็กเกจ</Link></section></main>;
  if (status === "error" && !data) return <main className={styles.shell}><section className={styles.stateCard}><h1>เปิด Market Comparison ไม่สำเร็จ</h1><p>{message}</p><button onClick={() => location.reload()}>ลองใหม่</button></section></main>;

  return <main className={styles.shell}>
    <header className={styles.header}>
      <div><div className={styles.eyebrow}>TDR REPORT · SALES INTELLIGENCE</div><h1>คนขายเทียบตลาด</h1><p>กำหนดตลาดที่ต้องการ แล้วดูว่าใครนำ ใครกินส่วนแบ่งเพิ่ม และอันดับขยับอย่างไรจากยอดจดทะเบียน DLT ที่ map เข้ากับ Vehicle Master ชุดเดียวกับ Catalog</p></div>
      <div className={styles.headerActions}><Link href="/member">ภาพรวม</Link><button onClick={signOut}>ออกจากระบบ</button></div>
    </header>

    <form className={styles.workspace} onSubmit={submit}>
      <aside className={styles.filters}>
        <div className={styles.filterHead}><div><span>DEFINE MARKET</span><b>กำหนดตลาด</b></div><button type="button" onClick={() => setFilters((current) => ({ ...current, ...EMPTY_SCOPE_FILTERS }))}>ล้าง scope</button></div>
        <label><span>เดือนข้อมูล</span><select value={filters.period} onChange={(event) => changePeriod(event.target.value)}>{periods.map((period) => <option key={period} value={period}>{monthLabel(period)}{provisional.has(period) ? " · provisional" : ""}</option>)}</select></label>
        <label><span>ช่วงเวลา</span><select value={filters.window} onChange={(event) => changeWindow(event.target.value as MarketWindow)}>{WINDOWS.map((item) => {
            const locked = plan?.windows ? !plan.windows.includes(item.value) : false;
            const short = !windowAvailable(filters.period, item.value);
            return <option key={item.value} value={item.value} disabled={locked || short}>
              {item.label}{locked ? PAID : short ? " · ข้อมูลยังไม่ครบ" : ""}
            </option>;
          })}</select></label>
        <label><span>เทียบกับ</span><select value={filters.compare} onChange={(event) => setFilters((current) => ({ ...current, compare: event.target.value as FilterState["compare"] }))}><option value="none">ไม่เทียบ</option><option value="previous" disabled={!comparisonAvailable(filters.period, filters.window, "previous")}>ช่วงก่อนหน้า</option><option value="yoy" disabled={(plan?.comparisons ? !plan.comparisons.includes("yoy") : false) || !comparisonAvailable(filters.period, filters.window, "yoy")}>ช่วงเดียวกันปีก่อน{plan?.comparisons && !plan.comparisons.includes("yoy") ? PAID : ""}</option></select></label>
        <label><span>จัดอันดับตาม</span><select value={filters.dimension} onChange={(event) => setFilters((current) => ({ ...current, dimension: event.target.value as FilterState["dimension"] }))}>{DIMENSIONS.map((item) => {
            const locked = item.value === "model" && plan ? !plan.model_grain : false;
            return <option key={item.value} value={item.value} disabled={locked}>{item.label}{locked ? PAID : ""}</option>;
          })}</select></label>
        <div className={styles.rule} />
        <label><span>ประเภทรถ DLT</span><select value={filters.registrationType} onChange={(event) => setFilters((current) => ({ ...current, registrationType: event.target.value }))}><option value="">ทั้งหมด</option><option value="RY1">RY1</option><option value="RY2">RY2</option><option value="RY3">RY3</option></select></label>
        <label><span>แบรนด์</span><select disabled={plan ? !plan.filters : false} value={filters.brand} onChange={(event) => changeBrand(event.target.value)}><option value="">ทุกแบรนด์</option>{brands.map((brand) => <option key={brand.id} value={brand.id}>{brand.name}</option>)}</select></label>
        <label><span>รุ่น</span><select disabled={plan ? !plan.filters : false} value={filters.model} onChange={(event) => setFilters((current) => ({ ...current, model: event.target.value }))}><option value="">ทุกรุ่น</option>{modelOptions.map((model) => <option key={model.id} value={model.id}>{model.brandName} · {model.name}</option>)}</select></label>
        <label><span>Segment</span><select disabled={plan ? !plan.filters : false} value={filters.segment} onChange={(event) => setFilters((current) => ({ ...current, segment: event.target.value }))}><option value="">ทุก Segment</option>{segments.map((segment) => <option key={segment}>{segment}</option>)}</select></label>
        <label><span>ตัวถัง</span><select disabled={plan ? !plan.filters : false} value={filters.bodyType} onChange={(event) => setFilters((current) => ({ ...current, bodyType: event.target.value }))}><option value="">ทุกตัวถัง</option>{bodyTypes.map((body) => <option key={body} value={body}>{bodyLabel(body)}</option>)}</select></label>
        <label><span>Powertrain</span><select disabled={plan ? !plan.filters : false} value={filters.powertrain} onChange={(event) => setFilters((current) => ({ ...current, powertrain: event.target.value }))}><option value="">ทุก Powertrain</option>{powertrains.map((powertrain) => <option key={powertrain}>{powertrain}</option>)}</select></label>
        <label><span>OEM Group</span><select disabled={plan ? !plan.filters : false} value={filters.oemGroup} onChange={(event) => setFilters((current) => ({ ...current, oemGroup: event.target.value }))}><option value="">ทุก OEM Group</option>{oemGroups.map((group) => <option key={group}>{group}</option>)}</select></label>
        <label><span>CBU / CKD</span><select disabled={plan ? !plan.filters : false} value={filters.importType} onChange={(event) => setFilters((current) => ({ ...current, importType: event.target.value }))}><option value="">ทุกรูปแบบ</option>{importTypes.map((type) => <option key={type}>{type}</option>)}</select></label>
        <label><span>ประเทศผลิต</span><select disabled={plan ? !plan.filters : false} value={filters.originCountry} onChange={(event) => setFilters((current) => ({ ...current, originCountry: event.target.value }))}><option value="">ทุกประเทศ</option>{originCountries.map((country) => <option key={country}>{country}</option>)}</select></label>
        <label><span>ต้นกำเนิดแบรนด์</span><select disabled={plan ? !plan.filters : false} value={filters.brandOrigin} onChange={(event) => setFilters((current) => ({ ...current, brandOrigin: event.target.value }))}><option value="">ทุกต้นกำเนิด</option>{brandOrigins.map((origin) => <option key={origin}>{origin}</option>)}</select></label>
        <label className={styles.disabled}><span>Price range</span><select disabled><option>รอ canonical Price Ledger coverage</option></select></label>
        {plan && !plan.filters ? (
          <p className={styles.planNote}>
            การกรองตามแบรนด์ รุ่น Segment ตัวถัง Powertrain OEM Group CBU/CKD ประเทศผลิต และต้นกำเนิดแบรนด์ อยู่ในแพ็กเกจแบบเสียค่าบริการ ·{" "}
            <Link href="/pricing">ดูแพ็กเกจ</Link>
          </p>
        ) : null}
        <label className={styles.check}><input type="checkbox" checked={filters.allScopes} onChange={(event) => setFilters((current) => ({ ...current, allScopes: event.target.checked }))} /><span>รวม NICHE / GREY / COMMERCIAL</span></label>
        <button className={styles.apply} type="submit" disabled={status === "loading"}>{status === "loading" ? "กำลังคำนวณ…" : "อัปเดตตลาด"}</button>
      </aside>

      <section className={styles.results}>
        {provisional.has(applied?.period || "") ? <div className={styles.danger}>เดือนนี้มีปริมาณต่ำกว่า 40% ของ baseline 6 เดือน จึงถือว่า provisional — อย่าใช้อันดับ/ส่วนแบ่งเป็นข้อสรุปตลาด</div> : null}
        {mappingCoverage < 90 ? <div className={styles.warning}>Canonical model mapping coverage {pct(mappingCoverage, 1)} — ranking ระดับ Model/Segment/Body/Powertrain จะไม่รวมหน่วยที่ map รุ่นไม่ได้; Brand ranking ยังเก็บ brand-grain residual ที่ระบุแบรนด์ได้</div> : null}
        {ignoredValue ? <div className={styles.info}>ตอนจัดอันดับตาม {DIMENSIONS.find((item) => item.value === applied?.dimension)?.label} ระบบเปิด filter ของ dimension เดียวกันออกอัตโนมัติ เพื่อให้เห็นคู่แข่งและ denominator ที่ถูกต้อง</div> : null}
        {message && status === "error" ? <div className={styles.danger}>{message}</div> : null}

        <div className={styles.contextRow}><div><span>MARKET SCOPE</span><b>{applied ? `${monthLabel(applied.period)} · ${WINDOWS.find((item) => item.value === applied.window)?.label}` : "—"}</b></div><div><span>ฐานตลาด</span><b>{applied?.allScopes ? "ALL SCOPES" : "CORE"}</b></div></div>

        <section className={styles.kpis}>
          <article><span>ยอดจดในตลาดที่จัดอันดับได้</span><strong>{n(marketTotal)}</strong><small>คัน</small></article>
          <article><span>อันดับ 1</span><strong>{leader?.entity_label || "—"}</strong><small>{leader ? `${pct(leader.market_share_pct)} share` : "ไม่มีข้อมูล"}</small></article>
          <article><span>Mapping coverage</span><strong>{pct(mappingCoverage, 1)}</strong><small>{n(selectedCoverage?.total_registrations)} raw registrations ในเดือนปลายทาง</small></article>
          <article><span>Share mover</span><strong>{gainers[0]?.entity_label || "—"}</strong><small>{gainers[0] ? pp(gainers[0].share_change_pp) : "ไม่ได้เปิด comparison"}</small></article>
        </section>

        <section className={styles.panel}>
          <div className={styles.panelHead}><div><span>RANKING</span><h2>{DIMENSIONS.find((item) => item.value === applied?.dimension)?.label || "ตลาด"}</h2></div><small>{data?.period_from ? `${periodKey(data.period_from)} → ${periodKey(data.period_to)}` : ""}</small></div>
          <div className={styles.tableWrap}><table><thead><tr><th>#</th><th>ผู้เล่น</th><th>ยอดจด</th><th>Share</th>{data?.comparison ? <><th>Δ Share</th><th>อันดับ</th></> : null}</tr></thead><tbody>{(data?.rows || []).map((row) => { const move = movementByKey.get(row.entity_key); return <tr key={row.entity_key}><td>{row.market_rank}</td><td><b>{row.entity_label}</b></td><td>{n(row.registrations)}</td><td>{pct(row.market_share_pct)}</td>{data?.comparison ? <><td className={Number(move?.share_change_pp || 0) >= 0 ? styles.positive : styles.negative}>{pp(move?.share_change_pp)}</td><td>{move?.rank_change == null ? "ใหม่/หลุด" : move.rank_change === 0 ? "—" : `${move.rank_change > 0 ? "↑" : "↓"}${Math.abs(move.rank_change)}`}</td></> : null}</tr>; })}</tbody></table></div>
        </section>

        {data?.comparison ? <section className={styles.panel}>
          <div className={styles.panelHead}><div><span>SHARE MOVEMENT</span><h2>การเปลี่ยนแปลงส่วนแบ่งตลาด</h2></div><small>จัดตาม percentage-point change ไม่ใช่ unit growth</small></div>
          <div className={styles.movementGrid}><div><h3>Gainers</h3>{gainers.map((row) => <div className={styles.moveRow} key={row.entity_key}><span>{row.entity_label}</span><div className={styles.moveTrack}><i className={styles.gain} style={{ width: `${Math.abs(Number(row.share_change_pp)) / maxMove * 100}%` }} /></div><b>{pp(row.share_change_pp)}</b></div>)}</div><div><h3>Losers</h3>{losers.map((row) => <div className={styles.moveRow} key={row.entity_key}><span>{row.entity_label}</span><div className={styles.moveTrack}><i className={styles.loss} style={{ width: `${Math.abs(Number(row.share_change_pp)) / maxMove * 100}%` }} /></div><b>{pp(row.share_change_pp)}</b></div>)}</div></div>
        </section> : null}

        <section className={styles.panel}>
          <div className={styles.panelHead}><div><span>MARKET SIZE TREND</span><h2>ยอดจดใน scope เดียวกัน</h2></div><small>ย้อนหลังสูงสุด 6 เดือนที่มีใน serving DB</small></div>
          <div className={styles.trend}>{trend.map((point) => <div key={point.period}><div className={styles.trendBar}><i style={{ height: `${Math.max(4, point.total / maxTrend * 100)}%` }} /></div><b>{n(point.total)}</b><span>{monthLabel(point.period)}</span></div>)}</div>
          <p className={styles.note}>กราฟนี้เป็น registration activity ตาม DLT ไม่ใช่ retail-sales ledger; ใช้ share และ relative position เป็นแกนหลักสำหรับอ่าน movement.</p>
        </section>
      </section>
    </form>
  </main>;
}
