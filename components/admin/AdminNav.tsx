import Link from "next/link";
import { logoutAction } from "@/app/admin/actions";

export function AdminNav() {
  return <aside className="adminNav">
    <div>
      <div className="adminBrand">TDR <b>AUTO</b></div>
      <small>EDITOR / DATA LIBRARY</small>
    </div>
    <nav>
      <Link href="/admin">ภาพรวม</Link>
      <Link href="/admin/library?table=models">Data Library</Link>
      <Link href="/admin/models/new">+ เพิ่มรุ่นรถ</Link>
      <Link href="/admin/brands/new">+ เพิ่มแบรนด์</Link>
      <Link href="/admin/plants/new">+ เพิ่มโรงงาน</Link>
      <Link href="/admin/companies/new">+ เพิ่มบริษัท</Link>
      <Link href="/admin/events/new">+ เพิ่มข่าว / Event</Link>
      <Link href="/" target="_blank">เปิดเว็บ Public ↗</Link>
    </nav>
    <form action={logoutAction}><button className="textButton">ออกจากระบบ</button></form>
  </aside>;
}
