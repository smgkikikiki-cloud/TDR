import Link from "next/link";
import { logoutAction } from "@/app/admin/actions";
import { currentEditor } from "@/lib/admin-auth";

export async function AdminNav() {
  const editor = await currentEditor();
  return <aside className="adminNav">
    <div>
      <div className="adminBrand">TDR <b>AUTO</b></div>
      <small>EDITOR / DATA LIBRARY</small>
    </div>
    <nav>
      <Link href="/admin">ภาพรวม</Link>
      <Link href="/admin/vehicle-input">Admin Bench · Vehicle input</Link>
      <Link href="/admin/library?table=models">Data Library</Link>
      <Link href="/admin/library?table=canonical_vehicle_releases">Vehicle releases</Link>
      <Link href="/admin/plants/new">+ เพิ่มโรงงาน</Link>
      <Link href="/admin/companies/new">+ เพิ่มบริษัท</Link>
      <Link href="/admin/events/new">+ เพิ่มข่าว / Event</Link>
      <Link href="/" target="_blank">เปิดเว็บ Public ↗</Link>
    </nav>
    <form action={logoutAction} className="adminNavFoot">
      {editor ? <div className="adminWho"><small>กำลังแก้ไขในชื่อ</small><b>{editor.name}</b></div> : null}
      <button className="textButton">ออกจากระบบ</button>
    </form>
  </aside>;
}
