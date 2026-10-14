import { adminDb } from "@/lib/supabase";
import { iceQueueCreate, iceQueueExclude, iceQueueLink } from "@/app/admin/ice-queue-actions";

export const dynamic = "force-dynamic";

type Search = Record<string, string | string[] | undefined>;
const n = (v: unknown) => Number(v || 0).toLocaleString("th-TH");
const slug = (v: string) => v.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
const title = (v: string) => (v === v.toUpperCase() ? v.toLowerCase().replace(/\b[a-z]/g, (c) => c.toUpperCase()) : v);

export default async function IceQueuePage({ searchParams }: { searchParams: Promise<Search> }) {
  const sp = await searchParams;
  const done = typeof sp.done === "string" ? sp.done : "";
  const failed = typeof sp.error === "string" ? sp.error : "";
  const db = adminDb();
  if (!db) return <div className="adminEditor"><div className="adminNotice">ฐานข้อมูลแอดมินยังไม่ได้ตั้งค่า</div></div>;

  const [queue, coverage] = await Promise.all([
    db.from("ice_review_queue").select("*").eq("status", "OPEN").order("total_units", { ascending: false }).limit(200),
    db.rpc("ice_coverage_by_period"),
  ]);
  const missing = Boolean(queue.error);
  const rows = (queue.data || []) as any[];
  const months = ((coverage.data || []) as any[]).slice(0, 3);
  const openUnits = rows.reduce((s, r) => s + Number(r.total_units || 0), 0);

  return <div className="adminEditor">
    <div className="adminHeader"><div>
      <small>ICE · MONTHLY</small>
      <h1>คิวรถ Ice ที่รอคุณตัดสิน</h1>
      <p>
        รถที่เคยตัดสินแล้วนับเข้าตลาดเองทุกเดือน หน้านี้มีเฉพาะกลุ่มรถที่ Ice ส่งมาใหม่และมีตั้งแต่ 40 คัน
        ตัดสินครั้งเดียว ระบบจำไว้ เดือนถัดไปไม่ถามซ้ำ ปุ่มทุกปุ่มใช้กับ "ทุกประเภททะเบียน" ของกลุ่มนั้น
        กลุ่มกระบะที่ต้องแยก รย.1/รย.2 ให้ทำผ่าน SQL
      </p>
    </div></div>

    {failed ? <div className="adminNotice"><b>ทำรายการไม่สำเร็จ:</b> {failed}</div> : null}
    {done ? <div className="adminSaved">บันทึกคำตัดสินของ {done} แล้ว</div> : null}
    {missing ? <div className="adminNotice">
      ยังอ่านคิวไม่ได้ ({queue.error?.message}) — ต้องรัน migration v69 ใน Supabase ก่อน แล้วรัน <code>select ice_monthly_refresh_queue();</code>
    </div> : null}

    {months.length ? <div className="libraryTable"><table>
      <thead><tr><th>งวด</th><th>ยอดทั้งหมด</th><th>นับเข้าตลาดแล้ว</th><th>%</th><th>ไม่นับ (ตามกฎ)</th><th>ยังไม่มีคำตัดสิน</th></tr></thead>
      <tbody>{months.map((m) => <tr key={m.period}>
        <td><b>{m.period}</b></td><td>{n(m.total_units)}</td><td>{n(m.approved_units)}</td><td>{m.approved_pct}%</td><td>{n(m.excluded_units)}</td><td>{n(m.uncovered_units)}</td>
      </tr>)}</tbody>
    </table></div> : null}

    {!missing ? <>
      <div className="adminHeader"><div>
        <h2>รอตัดสิน {n(rows.length)} กลุ่ม · {n(openUnits)} คัน</h2>
      </div></div>
      {rows.length ? rows.map((r) => {
        const brand = title(String(r.brand || ""));
        const guess = r.suggestion || `${slug(String(r.brand || ""))}.${slug(String(r.model_name || ""))}`;
        return <section key={r.model_group_id} className="adminForm" style={{ marginBottom: 16 }}>
          <b>{r.brand} · {r.model_name}</b>
          <small> {n(r.total_units)} คัน · ทะเบียน {r.reg_types || "-"} · รหัส {r.model_group_id}{r.suggestion ? ` · ระบบเดิมเดาว่า ${r.suggestion}` : ""}</small>

          <form action={iceQueueLink} className="adminInlineForm">
            <input type="hidden" name="model_group_id" value={r.model_group_id} />
            <label className="adminField"><span>ผูกกับรถที่มีอยู่ (รหัสรถ)</span>
              <input name="canonical_model_id" type="text" defaultValue={r.suggestion || ""} placeholder="toyota.camry" /></label>
            <button className="adminPrimary">ผูก</button>
          </form>

          <form action={iceQueueCreate} className="adminInlineForm">
            <input type="hidden" name="model_group_id" value={r.model_group_id} />
            <label className="adminField"><span>รหัสรถใหม่</span><input name="canonical_id" type="text" defaultValue={guess} /></label>
            <label className="adminField"><span>ชื่อรุ่น</span><input name="name_en" type="text" defaultValue={String(r.model_name || "")} /></label>
            <label className="adminField"><span>ชื่อแบรนด์ (ถ้าเป็นแบรนด์ใหม่)</span><input name="brand_name_en" type="text" defaultValue={brand} /></label>
            <label className="adminField"><span>สถานะ</span>
              <select name="status" defaultValue="UNVERIFIED"><option value="UNVERIFIED">รอยืนยันข้อมูล</option><option value="HISTORICAL">เลิกขายแล้ว</option></select></label>
            <button className="adminPrimary">สร้างรถใหม่แล้วผูก</button>
          </form>

          <form action={iceQueueExclude} className="adminInlineForm">
            <input type="hidden" name="model_group_id" value={r.model_group_id} />
            <label className="adminField"><span>ไม่นับกลุ่มนี้ (เหตุผล)</span><input name="reason" type="text" placeholder="เช่น รถพ่วง / ระบุรุ่นไม่ได้" /></label>
            <button className="textButton">ไม่นับ</button>
          </form>
        </section>;
      }) : <div className="adminSaved">ไม่มีอะไรค้างในคิว</div>}
    </> : null}
  </div>;
}
