import Link from "next/link";
import { adminDb } from "@/lib/supabase";

const allowed = ["canonical_vehicle_releases", "models", "production_programs", "brands", "plants", "companies", "events", "sources", "registrations"] as const;
type TableName = typeof allowed[number];
const config: Record<TableName, { label: string; columns: string[]; add?: string; editBase?: string }> = {
  canonical_vehicle_releases: { label: "Vehicle releases", columns: ["release_id", "canonical_revision", "as_of", "status", "counts", "activated_at", "created_at"] },
  models: { label: "Editorial model links", columns: ["name_th", "market_position", "image_url", "consumer_description", "featured", "updated_at"], editBase: "/admin/models" },
  production_programs: { label: "Production Programs", columns: ["model_id", "plant_id", "production_type", "status", "platform", "annual_production_estimate", "production_volume_year", "updated_at"] },
  brands: { label: "Editorial brands", columns: ["name_th", "name_en", "country_origin", "status", "updated_at"], editBase: "/admin/brands" },
  plants: { label: "โรงงาน", columns: ["name_th", "maker_group", "province", "capacity_annual", "estimated_production_annual", "status", "updated_at"], add: "/admin/plants/new", editBase: "/admin/plants" },
  companies: { label: "บริษัท", columns: ["name_th", "company_type", "parent_company", "province", "updated_at"], add: "/admin/companies/new", editBase: "/admin/companies" },
  events: { label: "ข่าว / Events", columns: ["event_date", "title_th", "event_type", "source_name", "published", "updated_at"], add: "/admin/events/new", editBase: "/admin/events" },
  sources: { label: "Sources", columns: ["published_date", "publisher", "title", "url", "retrieved_at"] },
  registrations: { label: "Registration data · paid", columns: ["period", "brand_name_raw", "model_name_raw", "registrations", "created_at"] },
};

function pretty(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.length ? value.join(" / ") : "—";
  const text = typeof value === "object" ? JSON.stringify(value) : String(value);
  return text.length > 68 ? `${text.slice(0, 68)}…` : text;
}

export default async function Library({ searchParams }: { searchParams: Promise<{ table?: string; saved?: string; deleted?: string; q?: string }> }) {
  const p = await searchParams;
  const table = (allowed.includes(p.table as TableName) ? p.table : "canonical_vehicle_releases") as TableName;
  const db = adminDb();
  let rows: any[] = [];
  if (db) {
    let query = db.from(table).select("*").limit(300);
    const order = table === "events" ? "event_date" : table === "registrations" ? "period" : table === "canonical_vehicle_releases" ? "created_at" : "updated_at";
    query = query.order(order, { ascending: false });
    const { data } = await query;
    rows = data || [];
  }
  const term = (p.q || "").trim().toLowerCase();
  if (term) rows = rows.filter((row) => JSON.stringify(row).toLowerCase().includes(term));
  const current = config[table];
  return <>
    <div className="adminHeader">
      <div><small>BACK DOOR DATA LIBRARY</small><h1>{current.label}</h1><p>Vehicle facts มาจาก canonical release เท่านั้น ตาราง models เก็บเฉพาะ editorial link และ industry context</p></div>
      {current.add ? <Link className="adminPrimaryLink" href={current.add}>+ เพิ่มข้อมูล</Link> : null}
    </div>
    <div className="libraryTabs">{allowed.map((name) => <Link key={name} className={name === table ? "active" : ""} href={`/admin/library?table=${name}`}>{config[name].label}</Link>)}</div>
    {p.saved ? <div className="adminSaved">บันทึกข้อมูลแล้ว</div> : null}
    {p.deleted ? <div className="adminSaved">ลบข้อมูลแล้ว</div> : null}
    <form className="librarySearch"><input name="q" defaultValue={p.q || ""} placeholder="ค้นหาในตารางนี้…" /><input type="hidden" name="table" value={table} /><button>ค้นหา</button></form>
    <div className="libraryMeta"><span>{rows.length} records</span><span>สูงสุด 300 records ต่อครั้ง</span></div>
    <div className="adminTableWrap"><table className="adminTable"><thead><tr>{current.columns.map((column) => <th key={column}>{column}</th>)}{(current.editBase || table === "production_programs") ? <th /> : null}</tr></thead><tbody>
      {rows.length ? rows.map((row) => {
        const editHref = current.editBase ? `${current.editBase}/${row.id}/edit` : table === "production_programs" && row.model_id ? `/admin/models/${row.model_id}/edit` : null;
        return <tr key={row.id || row.release_id}>{current.columns.map((column) => <td key={column}>{pretty(row[column])}</td>)}{editHref ? <td><Link className="editLink" href={editHref}>{current.editBase ? "แก้ editorial" : "แก้ Industry"}</Link></td> : null}</tr>;
      }) : <tr><td colSpan={current.columns.length + 1} className="adminEmpty">ยังไม่มีข้อมูลในตารางนี้</td></tr>}
    </tbody></table></div>
  </>;
}
