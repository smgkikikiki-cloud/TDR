import Link from "next/link";
import { adminDb } from "@/lib/supabase";

type SearchParams = Record<string, string | string[] | undefined>;
function first(value: string | string[] | undefined) { return Array.isArray(value) ? value[0] : value; }
function one(value: string | string[] | undefined) { return String(first(value) || "").trim(); }
function n(value: unknown) { const number = Number(value); return Number.isFinite(number) ? number.toLocaleString("th-TH") : "—"; }
function date(value: unknown) { return value ? String(value).slice(0,10) : "—"; }

export default async function AdminPricesPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const sp = await searchParams;
  const db = adminDb();
  const q = one(sp.q).toLocaleLowerCase();
  const selectedTrim = one(sp.trim);
  const [trimResult, priceResult, batchResult] = db ? await Promise.all([
    db.from("current_market_trims").select("canonical_id,model_id,name,powertrain,status,current_list_price,campaign_quote,price_history").order("model_id").order("name").limit(1000),
    db.from("canonical_price_projection").select("record_id,trim_id,amount_thb,price_type,effective_from,effective_to,observed_at,campaign_id,option_id,source,source_ref,payload").order("observed_at", { ascending: false }).limit(5000),
    db.from("canonical_input_batches").select("batch_key,source_kind,status,pull_request_url,error,created_at").in("source_kind", ["PRICE_HARVEST","OEM","MEDIA"]).order("created_at", { ascending: false }).limit(30),
  ]) : [{ data: [] }, { data: [] }, { data: [] }];
  const trims = trimResult.data || [];
  const prices = priceResult.data || [];
  const batches = batchResult.data || [];
  const modelIds = [...new Set(trims.map((row:any) => row.model_id).filter(Boolean))];
  const { data: modelRows } = db && modelIds.length ? await db.from("current_vehicle_models").select("canonical_id,brand_id,name_en,name_th").in("canonical_id", modelIds).limit(1000) : { data: [] as any[] };
  const brandIds = [...new Set((modelRows || []).map((row:any) => row.brand_id).filter(Boolean))];
  const { data: brandRows } = db && brandIds.length ? await db.from("current_vehicle_brands").select("canonical_id,name_en,name_th").in("canonical_id", brandIds).limit(500) : { data: [] as any[] };
  const brands = new Map((brandRows || []).map((row:any) => [String(row.canonical_id), String(row.name_en || row.name_th || row.canonical_id)]));
  const models = new Map((modelRows || []).map((row:any) => [String(row.canonical_id), { name: String(row.name_en || row.name_th || row.canonical_id), brand: brands.get(String(row.brand_id)) || "" }]));
  const label = (trim:any) => { const model:any = models.get(String(trim.model_id)); return `${model?.brand || ""} ${model?.name || trim.model_id} · ${trim.name} · ${trim.powertrain || "?"}`.trim(); };
  const visible = trims.filter((trim:any) => !q || `${label(trim)} ${trim.canonical_id}`.toLocaleLowerCase().includes(q));
  const target = trims.find((trim:any) => trim.canonical_id === selectedTrim) || visible[0] || null;
  const history = target ? prices.filter((row:any) => row.trim_id === target.canonical_id) : [];
  const currentCount = trims.filter((row:any) => row.current_list_price?.amount_thb).length;
  const campaignCount = trims.filter((row:any) => Array.isArray(row.campaign_quote?.campaign_options) && row.campaign_quote.campaign_options.length).length;

  return <div className="adminEditor">
    <div className="adminHeader"><div><small>ADMIN BENCH · CANONICAL PRICE LEDGER</small><h1>ราคา + Campaign + History</h1><p>อ่านจาก active Vehicle Master release โดยตรง. ราคาเป็น dated ledger แยกจาก MarketTrim identity; campaign ไม่ทับ MSRP.</p></div><Link className="adminPrimaryLink" href="/admin/vehicle-input">+ เพิ่ม Price observation</Link></div>
    <div className="adminQuickGrid"><Link href="/admin/market"><b>Market Intelligence</b><span>ยอดจด / share / movement</span></Link><Link href="/admin/registrations"><b>Registration Ops</b><span>preview / ingest / crosswalk</span></Link><Link href="/admin/vehicle-input"><b>Canonical Vehicle Editor</b><span>เพิ่มราคาใหม่ผ่าน validated queue</span></Link></div>

    <div className="adminStatGrid">
      <div className="adminStat"><span>MarketTrims</span><strong>{trims.length}</strong><small>active release</small></div>
      <div className="adminStat"><span>Current list price</span><strong>{currentCount}</strong><small>trims with current MSRP</small></div>
      <div className="adminStat"><span>Ledger records</span><strong>{prices.length}</strong><small>active release projection</small></div>
      <div className="adminStat"><span>Trims with campaign</span><strong>{campaignCount}</strong><small>campaign quote ณ release as-of</small></div>
    </div>

    <div className="adminNotice"><b>Write-path status</b><span>APPEND_PRICE ใช้ canonical queue ได้แล้ว. Supersede / retract / close / campaign edit ยังต้องเพิ่มเป็น canonical commands ก่อนเปิดปุ่มที่นี่ — ห้าม bypass ไปแก้ serving table หรือไฟล์ Git จากเว็บ.</span></div>

    <form className="adminForm" method="get"><label className="adminField adminFieldWide"><span>ค้นหา Brand / Model / Trim / Canonical ID</span><input name="q" defaultValue={one(sp.q)} placeholder="Jaecoo 5 / Camry / trim id…"/></label><label className="adminField adminFieldWide"><span>ดูรายละเอียด MarketTrim</span><select name="trim" defaultValue={target?.canonical_id || ""}>{visible.map((trim:any) => <option key={trim.canonical_id} value={trim.canonical_id}>{label(trim)}</option>)}</select></label><div className="adminFormActions"><button className="adminPrimary">Open ledger</button></div></form>

    {target ? <>
      <div className="adminHeader"><div><small>{target.canonical_id}</small><h2>{label(target)}</h2></div></div>
      <div className="adminStatGrid">
        <div className="adminStat"><span>Current list price</span><strong>{target.current_list_price?.amount_thb ? `${n(target.current_list_price.amount_thb)} ฿` : "—"}</strong><small>{target.current_list_price ? `${date(target.current_list_price.effective_from || target.current_list_price.observed_at)} · ${target.current_list_price.source || ""}` : "no current list price"}</small></div>
        <div className="adminStat"><span>History rows</span><strong>{history.length}</strong><small>including non-list price records</small></div>
        <div className="adminStat"><span>Campaign options</span><strong>{Array.isArray(target.campaign_quote?.campaign_options) ? target.campaign_quote.campaign_options.length : 0}</strong><small>not ranked against one another</small></div>
      </div>
      <div className="adminHeader"><div><small>PRICE LEDGER</small><h2>ประวัติราคา</h2></div></div>
      <div className="libraryTable"><table><thead><tr><th>Type</th><th>Amount</th><th>Effective</th><th>End</th><th>Observed</th><th>Campaign / option</th><th>Source</th></tr></thead><tbody>{history.map((row:any) => <tr key={row.record_id}><td><b>{row.price_type}</b></td><td>{n(row.amount_thb)} ฿</td><td>{date(row.effective_from)}</td><td>{date(row.effective_to)}</td><td>{date(row.observed_at)}</td><td>{[row.campaign_id,row.option_id].filter(Boolean).join(" / ") || "—"}</td><td>{row.source_ref ? <a href={row.source_ref} target="_blank" rel="noreferrer">{row.source || "source"} ↗</a> : row.source || "—"}</td></tr>)}</tbody></table></div>

      <div className="adminHeader"><div><small>CAMPAIGN QUOTE</small><h2>ทางเลือกแคมเปญ ณ active release</h2><p>แต่ละ option เป็นทางเลือกแยกกัน ไม่ประกาศว่าอันไหน “ดีที่สุด” เพราะ cash / finance / quota มีเงื่อนไขคนละแบบ.</p></div></div>
      {Array.isArray(target.campaign_quote?.campaign_options) && target.campaign_quote.campaign_options.length ? <div className="adminQuickGrid">{target.campaign_quote.campaign_options.map((option:any) => <div key={option.option_id || option.option_label}><b>{option.option_label || option.option_id}</b><span>{n(option.amount_thb)} ฿{option.discount_thb ? ` · ลด ${n(option.discount_thb)} ฿` : ""}</span><small>{option.conditions?.text || JSON.stringify(option.conditions || {})}</small></div>)}</div> : <div className="adminNotice"><span>ไม่มี campaign option ที่ active ณ release นี้</span></div>}
    </> : <div className="adminNotice">ยังไม่มี MarketTrim ใน active release</div>}

    <div className="adminHeader"><div><small>PRICE INPUT OPERATIONS</small><h2>30 batches ล่าสุดจาก Price/OEM/Media</h2></div></div>
    <div className="libraryTable"><table><thead><tr><th>Batch</th><th>Source</th><th>Status</th><th>Created</th><th>Result</th></tr></thead><tbody>{batches.map((row:any) => <tr key={row.batch_key}><td>{row.batch_key}</td><td>{row.source_kind}</td><td><b>{row.status}</b></td><td>{String(row.created_at || "").slice(0,19)}</td><td>{row.pull_request_url ? <a href={row.pull_request_url} target="_blank" rel="noreferrer">PR ↗</a> : row.error || "—"}</td></tr>)}</tbody></table></div>
  </div>;
}
