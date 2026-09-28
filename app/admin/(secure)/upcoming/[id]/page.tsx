import Link from "next/link";
import { notFound } from "next/navigation";
import { addUpcomingCarUpdate } from "@/app/admin/upcoming-actions";
import { UpcomingCarForm } from "@/components/admin/UpcomingCarForm";
import { UpcomingDeleteButton } from "@/components/admin/UpcomingDeleteButton";
import { Field, TextArea } from "@/components/admin/Fields";
import { getUpcomingCarForAdmin } from "@/lib/upcoming-cars";

export const dynamic = "force-dynamic";

function todayInBangkok() {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Bangkok", year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(new Date());
  const field = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
  return `${field("year")}-${field("month")}-${field("day")}`;
}

export default async function EditUpcomingCar({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^UP-\d{4,}$/.test(id)) notFound();
  const record = await getUpcomingCarForAdmin(id);
  if (!record) notFound();
  const { car, updates } = record;
  return <div className="adminEditor">
    <div className="adminHeader adminHeaderActions">
      <div><small>UPCOMING CARS / {car.vehicleId}</small><h1>{car.vehicleName}</h1>
        <Link href="/admin/upcoming">← รายการทั้งหมด</Link></div>
      <UpcomingDeleteButton vehicleId={car.vehicleId} />
    </div>
    <UpcomingCarForm car={car} />
    <section className="adminSubSection">
      <h3>บันทึกอัปเดต</h3>
      <form action={addUpcomingCarUpdate} className="adminForm">
        <input type="hidden" name="vehicle_id" value={car.vehicleId} />
        <Field label="วันที่อัปเดต" name="update_date" type="date" defaultValue={todayInBangkok()} required />
        <TextArea label="ข้อความอัปเดต" name="message" rows={4} />
        <div className="adminFormActions"><button className="adminPrimary">เพิ่มอัปเดต</button></div>
      </form>
      {updates.length ? <div className="adminTableWrap"><table className="adminTable">
        <thead><tr><th>วันที่</th><th>ข้อความ</th></tr></thead>
        <tbody>{updates.map((update) => <tr key={update.id}>
          <td>{update.updateDate}</td><td style={{ whiteSpace: "pre-wrap" }}>{update.message}</td>
        </tr>)}</tbody>
      </table></div> : <p>ยังไม่มีบันทึกอัปเดต</p>}
    </section>
  </div>;
}
