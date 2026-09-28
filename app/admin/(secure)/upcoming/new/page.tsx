import Link from "next/link";
import { UpcomingCarForm } from "@/components/admin/UpcomingCarForm";

export default function NewUpcomingCar() {
  return <div className="adminEditor">
    <div className="adminHeader"><div><small>UPCOMING CARS / CREATE</small><h1>เพิ่มรถที่กำลังจะเปิดตัว</h1></div>
      <Link href="/admin/upcoming">กลับรายการ</Link></div>
    <UpcomingCarForm />
  </div>;
}
