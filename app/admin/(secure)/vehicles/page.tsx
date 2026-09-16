import Link from "next/link";
import { listVehicleModelsForPicker } from "@/lib/canonical-editor";

export default async function VehiclesIndexPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string }>;
}) {
  const { q } = await searchParams;
  const term = (q || "").trim();
  const models = await listVehicleModelsForPicker(term);

  return <div className="adminEditor">
    <div className="adminHeader">
      <div>
        <small>VEHICLE MASTER · CANONICAL VEHICLE EDITOR</small>
        <h1>เปิดรถทีละคันเพื่อแก้ canonical data</h1>
        <p>
          เลือกรุ่นเพื่อดูและแก้ Brand → Model → Generation → MarketTrims แบบมีฟอร์ม
          แทนการเขียน JSON เอง — ทุกการแก้ยังผ่านคิว canonical เดียวกับ{" "}
          <Link href="/admin/vehicle-input">Vehicle input</Link>
        </p>
      </div>
    </div>

    <form className="adminForm" action="/admin/vehicles">
      <label className="adminField adminFieldWide">
        <span>ค้นหาแบรนด์ / ชื่อรุ่น / canonical id</span>
        <input name="q" type="text" defaultValue={term} placeholder="toyota, yaris, jaecoo.jaecoo_5_ev…" />
      </label>
      <div className="adminFormActions"><button className="adminPrimary">ค้นหา</button></div>
    </form>

    <div className="libraryTable"><table><thead><tr>
      <th>Canonical model</th><th>Brand</th><th>Name</th><th>Status</th><th></th>
    </tr></thead><tbody>
      {models.length ? models.map((model) => <tr key={model.canonicalId}>
        <td><code>{model.canonicalId}</code></td>
        <td>{model.brandId}</td>
        <td>{model.nameEn}{model.nameTh ? ` · ${model.nameTh}` : ""}</td>
        <td>{model.status || "—"}</td>
        <td><Link className="adminPrimaryLink" href={`/admin/vehicles/${encodeURIComponent(model.canonicalId)}`}>เปิด editor →</Link></td>
      </tr>) : <tr><td colSpan={5}>ไม่พบรุ่นที่ตรงกับคำค้นหานี้</td></tr>}
    </tbody></table></div>
  </div>;
}
