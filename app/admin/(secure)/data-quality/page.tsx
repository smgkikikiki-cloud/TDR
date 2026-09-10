import Link from "next/link";
import { adminDb } from "@/lib/supabase";
import { getAdminRegistrationCoverage, getAdminUnmappedRegistrationSummary } from "@/lib/admin-registration-market";
import { periodKey, provisionalMarketPeriods } from "@/lib/member-market";

function n(value: unknown) { return Number(value || 0).toLocaleString("th-TH"); }
function status(ok: boolean, partial = false) { return ok ? "✅" : partial ? "🟡" : "🔴"; }
async function count(table: string) {
  const db = adminDb(); if (!db) return null;
  const { count } = await db.from(table).select("*", { count: "exact", head: true });
  return count ?? 0;
}

export default async function DataQualityPage() {
  const db = adminDb();
  const [coverage, unresolved, models, trims, prices, specs, batches] = await Promise.all([
    getAdminRegistrationCoverage(), getAdminUnmappedRegistrationSummary(500),
    count("current_vehicle_models"), count("current_market_trims"), count("canonical_price_projection"),
    count("canonical_spec_projection"), count("canonical_input_batches"),
  ]);
  const latest = coverage.at(-1) as any;
  const provisional = provisionalMarketPeriods(coverage as any[]);
  const pricedModelResult = db ? await db.from("current_vehicle_models").select("canonical_id,retail_price_min,retail_price_max").not("retail_price_min", "is", null).limit(1000) : { data: [] };
  const pricedModels = pricedModelResult.data?.length || 0;
  const failedResult = db ? await db.from("canonical_input_batches").select("batch_key,error,created_at").eq("status","FAILED").order("created_at", { ascending:false }).limit(20) : { data: [] };
  const failed = failedResult.data || [];
  const firstPeriod = coverage[0] ? periodKey((coverage[0] as any).period) : "";
  const lastPeriod = latest ? periodKey(latest.period) : "";
  const hasLongHistory = Boolean(firstPeriod && firstPeriod <= "2021-01" && lastPeriod >= "2026-08");
  const priceCoverageGood = Boolean(models && pricedModels / models >= .8);
  const mappingHealthy = Number(latest?.mapped_unit_pct || 0) >= 90;

  const gates = [
    ["Canonical Catalog / Compare source", true, "Free Catalog + Compare read active canonical release"],
    ["Paid market canonical dimensions", true, "Paid market reads raw registration facts joined to active canonical release"],
    ["Admin Full Market Bench", true, "New /admin/market uses the same market aggregation contract"],
    ["Registration ingest + crosswalk review", true, "Preview / replace-month ingest / reviewed alias queue now live in TDR Admin"],
    ["Price ledger read/history", true, "Admin reads active canonical price projection and campaign quote"],
    ["Price correction write parity", true, "Append / supersede / retract / close / campaign upsert all enter the canonical input queue and Vehicle Master revision path"],
    ["Raw trend uses full filter semantics", true, "Paid market trend uses a neutral OEM-group aggregation so Brand / Model / Segment / Body / Powertrain / DLT scope remains fully applied"],
    ["Period-aware price/import/origin analytics", false, "Serving analytics still use current model snapshot for these historical facets"],
    ["Full registration history", hasLongHistory, `${firstPeriod || "—"} → ${lastPeriod || "—"}; old warehouse extends back to 2021`],
    ["Regional / province grain", false, "Current Supabase registration fact has no province field"],
    ["Price range usable in paid slicer", priceCoverageGood, `${pricedModels}/${models ?? 0} canonical models have current price range`],
  ] as const;
  const remainingBlockers = gates.filter(([, ok]) => !ok);

  return <div className="adminEditor">
    <div className="adminHeader"><div><small>ADMIN BENCH · DATA QUALITY / PARITY GATE</small><h1>ย้ายครบจริงหรือยัง?</h1><p>หน้านี้ตอบคำถามเดียว: capability จาก Vehicle Master เก่าเข้าถึงได้จาก TDR ใหม่ครบหรือยัง. แดงหนึ่งอัน = ยังห้าม retire Streamlit workbench.</p></div><Link className="adminPrimaryLink" href="/admin/market">เปิด Full Market Bench</Link></div>
    <div className="adminStatGrid">
      <div className="adminStat"><span>Canonical models</span><strong>{n(models)}</strong><small>active release</small></div>
      <div className="adminStat"><span>MarketTrims</span><strong>{n(trims)}</strong><small>active release</small></div>
      <div className="adminStat"><span>Price ledger</span><strong>{n(prices)}</strong><small>projection rows</small></div>
      <div className="adminStat"><span>Spec facts</span><strong>{n(specs)}</strong><small>projection rows</small></div>
      <div className="adminStat"><span>Registration months</span><strong>{coverage.length}</strong><small>{firstPeriod || "—"} → {lastPeriod || "—"}</small></div>
      <div className="adminStat"><span>Latest mapped</span><strong>{latest ? `${Number(latest.mapped_unit_pct || 0).toFixed(1)}%` : "—"}</strong><small>{mappingHealthy ? "healthy" : "needs review"}</small></div>
      <div className="adminStat"><span>Unmapped groups</span><strong>{unresolved.length}</strong><small>top groups loaded</small></div>
      <div className="adminStat"><span>Input batches</span><strong>{n(batches)}</strong><small>{failed.length} recent failed</small></div>
    </div>

    <div className="adminHeader"><div><small>LEGACY RETIREMENT GATE</small><h2>Feature parity matrix</h2></div></div>
    <div className="libraryTable"><table><thead><tr><th>Status</th><th>Capability</th><th>Evidence / blocker</th></tr></thead><tbody>{gates.map(([label, ok, note]) => <tr key={label}><td style={{fontSize:18}}>{status(Boolean(ok))}</td><td><b>{label}</b></td><td>{note}</td></tr>)}</tbody></table></div>
    {remainingBlockers.length ? <div className="adminNotice"><b>Retirement decision: KEEP LEGACY WORKBENCH</b><span>ยังเหลือ {remainingBlockers.length} red gate: {remainingBlockers.map(([label]) => label).join(" · ")}. จึงยังไม่ลบ/disable Streamlit จนกว่าจะย้าย data grain/history ที่จำเป็นและผ่าน parity tests.</span></div> : <div className="adminNotice"><b>Retirement decision: READY FOR FINAL MANUAL REVIEW</b><span>Automated parity gates ผ่านหมดแล้ว เหลือ product-level manual review ก่อน disable presentation layer เก่า.</span></div>}

    <div className="adminHeader"><div><small>REGISTRATION HEALTH</small><h2>Coverage by month</h2></div></div>
    <div className="libraryTable"><table><thead><tr><th>Period</th><th>Total</th><th>Mapped</th><th>Coverage</th><th>Quality flag</th></tr></thead><tbody>{[...coverage].reverse().map((row:any) => { const p=periodKey(row.period); return <tr key={p}><td>{p}</td><td>{n(row.total_registrations)}</td><td>{n(row.mapped_registrations)}</td><td>{Number(row.mapped_unit_pct || 0).toFixed(1)}%</td><td>{provisional.has(p) ? "PROVISIONAL" : Number(row.mapped_unit_pct || 0)<80 ? "LOW MAP" : "—"}</td></tr>; })}</tbody></table></div>

    {failed.length ? <><div className="adminHeader"><div><small>FAILED INPUT</small><h2>Canonical batches ที่ต้องแก้</h2></div></div><div className="libraryTable"><table><thead><tr><th>Batch</th><th>When</th><th>Error</th></tr></thead><tbody>{failed.map((row:any) => <tr key={row.batch_key}><td>{row.batch_key}</td><td>{String(row.created_at || "").slice(0,19)}</td><td>{row.error || "—"}</td></tr>)}</tbody></table></div></> : null}

    <div className="adminQuickGrid"><Link href="/admin/registrations"><b>แก้ Registration coverage</b><span>preview ingest / reviewed aliases</span></Link><Link href="/admin/prices"><b>ตรวจ Price Ledger</b><span>current / history / campaign / maintenance</span></Link><Link href="/admin/vehicle-input"><b>Canonical input queue</b><span>vehicle / price / spec input</span></Link></div>
  </div>;
}