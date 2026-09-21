import Link from "next/link";
import { logoutAction } from "@/app/admin/actions";
import { currentEditor } from "@/lib/admin-auth";

/**
 * The admin sidebar: six doors, one per thing somebody actually does.
 *
 * Every entry that used to live here and does not now -- ECO review, price
 * coverage, retail lifecycle, data quality, raw canonical input, the batch
 * queue, releases, crosswalk teaching -- was a view onto machinery, not a
 * job. The machinery still runs; it just runs behind a save instead of
 * asking an operator to drive it. What is left is a car (Vehicles), a pile
 * of cars arriving at once (Import), the few the machinery could not place
 * (Exceptions), and the things read rather than edited.
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
      <Link href="/admin/research/new">บทวิเคราะห์</Link>

      <details className="adminNavGroup">
        <summary>Industry &amp; editorial</summary>
        <Link href="/admin/plants/new">+ เพิ่มโรงงาน</Link>
        <Link href="/admin/companies/new">+ เพิ่มบริษัท</Link>
        <Link href="/admin/events/new">+ เพิ่มข่าว / Event</Link>
      </details>

      <Link href="/" target="_blank">เปิดเว็บ Public ↗</Link>
    </nav>

    <form action={logoutAction} className="adminNavFoot">
      {editor ? <div className="adminWho"><small>กำลังแก้ไขในชื่อ</small><b>{editor.name}</b></div> : null}
      <button className="textButton">ออกจากระบบ</button>
    </form>
  </aside>;
}
