import Link from "next/link";
import { logoutAction } from "@/app/admin/actions";
import { currentEditor } from "@/lib/admin-auth";

/**
 * The admin sidebar, ordered by how often a thing is actually done rather
 * than by which subsystem owns it.
 *
 * Editing a car is one job with one home -- the Canonical Vehicle Editor --
 * so it sits alone at the top. Everything below it is either a recurring
 * queue somebody works through, or a tool that exists for the case the normal
 * path cannot express. The second kind used to sit in the same flat list as
 * the first, which made the list read as sixteen equally plausible starting
 * points; folding it away is not hiding it, it is saying which door to use.
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
      <Link href="/admin/prices">ราคา</Link>
      <Link href="/admin/prices/coverage">Price coverage</Link>
      <Link href="/admin/retail-lifecycle">Retail lifecycle</Link>
      <Link href="/admin/eco-trims">ECO → MarketTrim review</Link>
      <Link href="/admin/registrations">Registration ops</Link>
      <Link href="/admin/data-quality">Data quality</Link>
      <Link href="/admin/market">Market intelligence</Link>

      <details className="adminNavGroup">
        <summary>Advanced</summary>
        {/* The raw queue. It can express things the editor deliberately
            cannot, which is exactly why it is not the front door. */}
        <Link href="/admin/vehicle-input">Raw canonical input</Link>
        <Link href="/admin/library?table=models">Data Library</Link>
        <Link href="/admin/library?table=canonical_vehicle_releases">Vehicle releases</Link>
      </details>

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
