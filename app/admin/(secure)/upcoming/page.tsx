import Link from "next/link";
import { listUpcomingCars } from "@/lib/upcoming-cars";
import { displayUpcomingTiming } from "@/lib/upcoming-cars-domain";

export const dynamic = "force-dynamic";

export default async function UpcomingAdminList() {
  const cars = await listUpcomingCars();
  return <div className="adminEditor">
    <div className="adminHeader">
      <div><small>EDITORIAL INTELLIGENCE</small><h1>Upcoming Cars</h1>
        <p>ข้อมูลรถที่ยังไม่เปิดตัว แยกจาก Vehicle Master</p></div>
      <Link href="/admin/upcoming/new" className="adminPrimaryLink">เพิ่มรถ</Link>
    </div>
    <div className="adminTableWrap"><table className="adminTable">
      <thead><tr><th>ID</th><th>รถ</th><th>สถานะ</th><th>ความมั่นใจ</th><th>ช่วงเปิดตัว</th><th>แก้ไขล่าสุด</th></tr></thead>
      <tbody>{cars.length ? cars.map((car) => <tr key={car.id}>
        <td><Link className="editLink" href={`/admin/upcoming/${car.vehicleId}`}>{car.vehicleId}</Link></td>
        <td>{car.vehicleName}</td><td>{car.status}</td><td>{car.confidence}</td>
        <td>{displayUpcomingTiming(car)}</td>
        <td>{new Date(car.updatedAt).toLocaleDateString("th-TH")}</td>
      </tr>) : <tr><td className="adminEmpty" colSpan={6}>ยังไม่มี Upcoming Cars</td></tr>}</tbody>
    </table></div>
  </div>;
}
