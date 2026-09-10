import Link from "next/link";
import { ingestRegistrationSnapshot, teachRegistrationAlias } from "@/app/admin/registration-actions";
import { adminDb } from "@/lib/supabase";
import { getAdminRegistrationCoverage, getAdminUnmappedRegistrationSummary } from "@/lib/admin-registration-market";
import { periodKey } from "@/lib/member-market";

type SearchParams = Record<string, string | string[] | undefined>;
type PreviewRow = { period: string; registrationType: string; brand: string; model: string; units: number; mapped: boolean };
function first(value: string | string[] | undefined) { return Array.isArray(value) ? value[0] : value; }
function one(value: string | string[] | undefined) { return String(first(value) || "").trim(); }
function n(value: unknown) { return Number(value || 0).toLocaleString("th-TH"); }
function normalize(value: unknown) { return String(value || "").toLocaleLowerCase().replace(/[^a-z0-9]+/g, ""); }
function snapshotUrl(period: string, kind: string) {
  const base = "https://raw.githubusercontent.com/smgkikikiki-cloud/TDR/main/automotive/vehicle_master/data";
  if (kind === "api") return `${base}/raw/dlt_${period}.csv`;
  if (kind === "long") return `${base}/raw_pivot/long_${period}.csv`;
  return `${base}/raw_pivot/pivot_${period}.csv`;
}

async function previewSnapshot(period: string, kind: string) {
  if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(period) || !["api","long","pivot"].includes(kind)) return null;
  const db = adminDb();
  if (!db) return { error: "admin database is not configured" } as any;
  const url = snapshotUrl(period, kind);
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) return { error: `snapshot not found (${response.status})`, url } as any;
  const text = await response.text();
  const lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
    .filter((line) => !line.startsWith("period,registration_type,brand,model,units") && !line.startsWith("เดือน,ประเภท,ยี่ห้อ,แบบรถ,จำนวน"));
  const parsed: Array<Omit<PreviewRow,"mapped">> = [];
  for (const line of lines) {
    const parts = line.split(",");
    if (parts.length < 5 || parts[0] !== period || !/^\d+$/.test(parts[4])) return { error: `malformed/mismatched row: ${line.slice(0,120)}`, url } as any;
    parsed.push({ period: parts[0], registrationType: parts[1], brand: parts[2], model: parts[3], units: Number(parts[4]) });
  }
  const [{ data: brandAliases, error: baError }, { data: modelAliases, error: maError }] = await Promise.all([
    db.from("registration_brand_aliases").select("raw_brand_norm,brand_id").limit(5000),
    db.from("registration_model_aliases").select("brand_id,registration_type,alias_norm,model_id,match_mode").limit(10000),
  ]);
  if (baError || maError) return { error: baError?.message || maError?.message || "crosswalk query failed", url } as any;
  const brandMap = new Map((brandAliases || []).map((row: any) => [String(row.raw_brand_norm), String(row.brand_id)]));
  const aliases = modelAliases || [];
  function mapped(row: Omit<PreviewRow,"mapped">) {
    const brandNorm = normalize(row.brand); const modelNorm = normalize(row.model);
    const brandId = brandMap.get(brandNorm); if (!brandId) return false;
    const withoutBrand = brandNorm && modelNorm.startsWith(brandNorm) ? modelNorm.slice(brandNorm.length) : modelNorm;
    const candidates = aliases.filter((alias: any) => String(alias.brand_id) === brandId && ["*",row.registrationType].includes(String(alias.registration_type)))
      .filter((alias: any) => {
        const token = String(alias.alias_norm); const mode = String(alias.match_mode);
        return mode === "exact" ? (modelNorm === token || withoutBrand === token) : (modelNorm.startsWith(token) || withoutBrand.startsWith(token));
      })
      .map((alias: any) => ({ modelId: String(alias.model_id), classSpecific: String(alias.registration_type) === row.registrationType ? 1 : 0, length: String(alias.alias_norm).length }));
    if (!candidates.length) return false;
    candidates.sort((a:any,b:any) => b.classSpecific-a.classSpecific || b.length-a.length);
    const best = candidates.filter((c:any) => c.classSpecific === candidates[0].classSpecific && c.length === candidates[0].length);
    return new Set(best.map((c:any) => c.modelId)).size === 1;
  }
  const rows: PreviewRow[] = parsed.map((row) => ({ ...row, mapped: mapped(row) }));
  const units = rows.reduce((sum,row) => sum + row.units,0);
  const mappedUnits = rows.filter((row) => row.mapped).reduce((sum,row) => sum + row.units,0);
  return { url, rows, units, mappedUnits, mappedPct: units ? 100*mappedUnits/units : 0, unmapped: rows.filter((row) => !row.mapped) };
}

export default async function RegistrationsAdminPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const sp = await searchParams;
  const db = adminDb();
  const [coverage, unresolved, modelResult, brandResult] = await Promise.all([
    getAdminRegistrationCoverage(), getAdminUnmappedRegistrationSummary(120),
    db ? db.from("current_vehicle_models").select("canonical_id,tdr_model_id,brand_id,name_en,name_th").order("name_en").limit(1000) : Promise.resolve({ data: [] }),
    db ? db.from("current_vehicle_brands").select("canonical_id,name_en,name_th").order("name_en").limit(500) : Promise.resolve({ data: [] }),
  ]);
  const brands = new Map((brandResult.data || []).map((row:any) => [String(row.canonical_id), String(row.name_en || row.name_th || row.canonical_id)]));
  const targets = (modelResult.data || []).filter((row:any) => row.tdr_model_id).map((row:any) => ({
    id: String(row.tdr_model_id), label: `${brands.get(String(row.brand_id)) || ""} ${row.name_en || row.name_th || row.canonical_id}`.trim(),
  })).sort((a:any,b:any) => a.label.localeCompare(b.label));
  const previewPeriod = one(sp.preview_period); const previewKind = one(sp.preview_kind) || "api";
  const preview = previewPeriod ? await previewSnapshot(previewPeriod, previewKind) : null;
  const existing = previewPeriod ? coverage.find((row:any) => periodKey(row.period) === previewPeriod) as any : null;
  const latest = coverage.at(-1) as any;

  return <div className="adminEditor">
    <div className="adminHeader"><div><small>ADMIN BENCH · REGISTRATION OPERATIONS</small><h1>Upload + Review queue</h1><p>DLT facts แยกจาก Vehicle Master. ขั้นนี้ตรวจ snapshot ก่อน replace เดือนจริง แล้วสอน crosswalk เฉพาะ mapping ที่คนยืนยัน.</p></div><Link className="adminPrimaryLink" href="/admin/market">กลับ Full Market Bench</Link></div>
    <div className="adminQuickGrid"><Link href="/admin/market"><b>Market Intelligence</b><span>rank / share / movement / raw diagnostics</span></Link><Link href="/admin/vehicle-input"><b>Vehicle Editor</b><span>แก้ canonical vehicle facts</span></Link><Link href="/admin/library?table=registrations"><b>Raw registration library</b><span>ดู rows ใน Supabase</span></Link></div>
    {sp.ingested ? <div className="adminSaved">โหลด {one(sp.period)} แล้ว · {n(one(sp.units))} คัน · mapped {one(sp.coverage) || "—"}%</div> : null}
    {sp.mapped ? <div className="adminSaved">บันทึก reviewed alias และ remap rows เดิมแล้ว: {one(sp.raw)}</div> : null}

    <div className="adminStatGrid">
      <div className="adminStat"><span>Months in serving DB</span><strong>{coverage.length}</strong><small>{coverage.length ? `${periodKey((coverage[0] as any).period)} → ${periodKey(latest?.period)}` : "no data"}</small></div>
      <div className="adminStat"><span>Latest units</span><strong>{n(latest?.total_registrations)}</strong><small>{periodKey(latest?.period)}</small></div>
      <div className="adminStat"><span>Latest mapped</span><strong>{latest ? `${Number(latest.mapped_unit_pct || 0).toFixed(1)}%` : "—"}</strong><small>{n(latest?.mapped_registrations)} units</small></div>
      <div className="adminStat"><span>Unmapped labels</span><strong>{unresolved.length}</strong><small>top unresolved groups loaded</small></div>
    </div>

    <div className="adminHeader"><div><small>INGEST 01 · PREVIEW FIRST</small><h2>ตรวจ snapshot ก่อนแทนเดือนจริง</h2><p>Preview ไม่เขียนฐานข้อมูล. Commit ใช้ RPC เดิมซึ่ง validate period/row shape ก่อน delete + insert transaction.</p></div></div>
    <form className="adminForm" method="get">
      <input type="hidden" name="preview" value="1" />
      <label className="adminField"><span>เดือน</span><input type="month" name="preview_period" required defaultValue={previewPeriod || periodKey(latest?.period)} /></label>
      <label className="adminField"><span>Snapshot</span><select name="preview_kind" defaultValue={previewKind}><option value="api">DLT API export</option><option value="long">Pivot normalized long</option><option value="pivot">Pivot source</option></select></label>
      <div className="adminFormActions"><button className="adminPrimary">Preview snapshot</button></div>
    </form>

    {preview ? <div className="adminNotice">{"error" in preview ? <><b>Preview failed</b><span>{preview.error}</span><code>{preview.url || ""}</code></> : <><b>{previewPeriod} · {previewKind.toUpperCase()}</b><span>{preview.rows.length.toLocaleString()} rows · {n(preview.units)} units · dry-run mapped {preview.mappedPct.toFixed(1)}% ({n(preview.mappedUnits)} units)</span><code>{preview.url}</code>{existing ? <span><strong>คำเตือน:</strong> เดือนนี้มีอยู่แล้ว {n(existing.total_registrations)} คัน; Commit จะ replace เดือนนี้ทั้งก้อน.</span> : <span>เดือนนี้ยังไม่มีใน serving DB.</span>}</>}</div> : null}

    {preview && !("error" in preview) ? <>
      <div className="libraryTable"><table><thead><tr><th>Class</th><th>Brand</th><th>Model raw</th><th>Units</th><th>Dry-run</th></tr></thead><tbody>{preview.rows.slice(0,30).map((row: PreviewRow, index: number) => <tr key={`${row.brand}-${row.model}-${index}`}><td>{row.registrationType}</td><td>{row.brand}</td><td>{row.model}</td><td>{n(row.units)}</td><td>{row.mapped ? "mapped" : "REVIEW"}</td></tr>)}</tbody></table></div>
      <form action={ingestRegistrationSnapshot} className="adminForm"><input type="hidden" name="period" value={previewPeriod}/><input type="hidden" name="snapshot_kind" value={previewKind}/><div className="adminFormActions"><button className="adminPrimary">Commit + replace {previewPeriod}</button></div></form>
    </> : null}

    <div className="adminHeader"><div><small>REVIEW 02 · UNMAPPED</small><h2>คิวสอน crosswalk</h2><p>เรียงตามยอดสะสม เพื่อแก้ label ที่กระทบ coverage มากก่อน. ถ้ารถยังไม่มีใน catalog ให้ไป Vehicle Editor; อย่าฝืน map เข้ารุ่นใกล้เคียง.</p></div></div>
    <datalist id="registrationTargetModels">{targets.map((row:any) => <option key={row.id} value={row.id}>{row.label}</option>)}</datalist>
    <div className="libraryTable"><table><thead><tr><th>Class</th><th>Raw brand</th><th>Raw model</th><th>Units</th><th>Months</th><th>Latest</th><th>Reviewed target</th></tr></thead><tbody>{unresolved.map((row:any) => <tr key={`${row.registration_type}|${row.brand_name_raw}|${row.model_name_raw}`}><td>{row.registration_type}</td><td><b>{row.brand_name_raw}</b></td><td>{row.model_name_raw}</td><td>{n(row.registrations)}</td><td>{row.months}</td><td>{periodKey(row.latest_period)}</td><td><form action={teachRegistrationAlias} style={{display:"flex",gap:6,alignItems:"center",minWidth:420}}><input type="hidden" name="raw_brand" value={row.brand_name_raw}/><input type="hidden" name="raw_model" value={row.model_name_raw}/><input type="hidden" name="registration_type" value={row.registration_type}/><input name="target_model_id" list="registrationTargetModels" placeholder="public model UUID…" required style={{minWidth:230}}/><select name="match_mode" defaultValue="prefix"><option value="prefix">prefix</option><option value="exact">exact</option></select><button className="adminPrimary">Teach</button></form></td></tr>)}</tbody></table></div>
    <div className="adminNotice"><b>ยังต้องหา source ที่ดีกว่า?</b><span>อย่าสอน alias ถ้า DLT row ไม่ได้ละเอียดพอจะระบุรุ่น. ปล่อย NULL ไว้ได้; Brand-level residual จะยังนับใน Brand market โดยไม่ถูกเสกเป็น Model.</span><Link href="/admin/vehicle-input">ถ้า catalog ขาดรุ่น → เปิด Vehicle Editor</Link></div>

    <div className="adminHeader"><div><small>COVERAGE HISTORY</small><h2>ทุกเดือนใน serving DB</h2></div></div>
    <div className="libraryTable"><table><thead><tr><th>Period</th><th>Rows</th><th>Total units</th><th>Mapped rows</th><th>Mapped units</th><th>Coverage</th></tr></thead><tbody>{[...coverage].reverse().map((row:any) => <tr key={row.period}><td>{periodKey(row.period)}</td><td>{n(row.raw_rows)}</td><td>{n(row.total_registrations)}</td><td>{n(row.mapped_rows)}</td><td>{n(row.mapped_registrations)}</td><td>{Number(row.mapped_unit_pct || 0).toFixed(1)}%</td></tr>)}</tbody></table></div>
  </div>;
}
