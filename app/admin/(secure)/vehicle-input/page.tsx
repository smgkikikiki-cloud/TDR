import { enqueueVehicleInput } from "@/app/admin/input-actions";
import { adminDb } from "@/lib/supabase";

const example = JSON.stringify({
  schema_version: 1,
  batch_id: "admin-jaecoo5-price-20260909",
  year: 2026,
  source: { kind: "OEM", ref: "https://example.com/official-price" },
  reason: "official list price",
  commands: [{
    operation: "APPEND_PRICE",
    canonical_id: "jaecoo.jaecoo_5_ev.j5.trim.dynamic_bev",
    payload: {
      amount_thb: 899000,
      price_type: "LIST_PRICE",
      effective_from: "2026-09-09",
      observed_at: "2026-09-09",
      source: "OEM",
      source_ref: "https://example.com/official-price",
    },
  }],
}, null, 2);

export default async function VehicleInputPage({ searchParams }: { searchParams: Promise<{ queued?: string }> }) {
  const query = await searchParams;
  const db = adminDb();
  const { data } = db ? await db.from("canonical_input_batches")
    .select("batch_key,source_kind,item_count,status,pull_request_url,release_id,error,created_at")
    .order("created_at", { ascending: false }).limit(20) : { data: [] };
  return <div className="adminEditor">
    <div className="adminHeader"><div><small>VEHICLE MASTER · ONE INPUT</small><h1>Canonical input queue</h1><p>รับเฉพาะ market/catalog/trim/price/spec/fitment; ข้อมูลจดทะเบียนมี ingest แยกและจะไม่สร้าง MarketTrim</p></div></div>
    {query.queued ? <p className="adminSaved">{query.queued === "duplicate" ? "batch เดิมอยู่ในคิวแล้ว—ไม่สร้างซ้ำ" : "รับ batch เข้าคิวแล้ว"}</p> : null}
    <form action={enqueueVehicleInput} className="adminForm">
      <label className="adminField adminFieldWide"><span>Input batch JSON</span><textarea name="payload" rows={24} defaultValue={example} required /></label>
      <div className="adminFormActions"><button className="adminPrimary">Validate + enqueue</button></div>
    </form>
    <div className="adminHeader"><div><small>PIPELINE STATUS</small><h2>20 batches ล่าสุด</h2></div></div>
    <div className="libraryTable"><table><thead><tr><th>Batch</th><th>Source</th><th>Items</th><th>Status</th><th>Result</th></tr></thead><tbody>
      {(data || []).map((row: any) => <tr key={row.batch_key}><td><b>{row.batch_key}</b><small>{new Date(row.created_at).toLocaleString("th-TH")}</small></td><td>{row.source_kind}</td><td>{row.item_count}</td><td>{row.status}</td><td>{row.pull_request_url ? <a href={row.pull_request_url}>PR</a> : row.release_id || row.error || "—"}</td></tr>)}
    </tbody></table></div>
  </div>;
}
