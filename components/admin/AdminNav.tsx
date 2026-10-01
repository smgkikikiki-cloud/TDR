import Link from "next/link";
import { logoutAction } from "@/app/admin/actions";
import { currentEditor } from "@/lib/admin-auth";

/**
 * The admin sidebar: routine work stays compact; the Retail Lineup Bootstrap
 * sits in its own explicit Level-0 section because it is an owner-authoritative
 * identity reset, not another daily import/review queue.
 */
export async function AdminNav() {
  const editor = await currentEditor();
  return <aside className="adminNav">
    <div>
      <div className="adminBrand">TDR <b>AUTO</b></div>
      <small>EDITOR / DATA LIBRARY</small>
    </div>

    <nav>
      <Link className="adminNavPrimary" href="/admin/vehicles">
        <b>แก้ข้อมูลรถ</b>
        <em>Canonical Vehicle Editor · รุ่น เจเนอเรชัน รุ่นย่อย สเปก</em>
      </Link>

      <span className="adminNavHeading">งานประจำ</span>
      <Link href="/admin">ภาพรวม</Link>
      <Link href="/admin/import">นำเข้าข้อมูล</Link>
      <Link href="/admin/exceptions">รายการที่ต้องตัดสิน</Link>
      <Link href="/admin/market">ข้อมูลตลาด</Link>
      <Link href="/admin/research">ไฟล์งานวิจัย</Link>

      <span className="adminNavHeading">LEVEL 0 · ใช้เมื่อ reset lineup</span>
      <Link href="/admin/retail-lineup-bootstrap">Retail Lineup Bootstrap</Link>

      <Link href="/" target="_blank">เปิดเว็บ Public ↗</Link>
    </nav>

    <form action={logoutAction} className="adminNavFoot">
      {editor ? <div className="adminWho"><small>กำลังแก้ไขในชื่อ</small><b>{editor.name}</b></div> : null}
      <button className="textButton">ออกจากระบบ</button>
    </form>
  </aside>;
}
