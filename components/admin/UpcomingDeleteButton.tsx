"use client";

import { deleteUpcomingCar } from "@/app/admin/upcoming-actions";

export function UpcomingDeleteButton({ vehicleId }: { vehicleId: string }) {
  return <form action={deleteUpcomingCar} onSubmit={(event) => {
    if (!window.confirm(`ลบ ${vehicleId} พร้อมบันทึกอัปเดตทั้งหมดอย่างถาวร?`)) event.preventDefault();
  }}>
    <input type="hidden" name="vehicle_id" value={vehicleId} />
    <button className="adminDangerButton">ลบ Upcoming Car</button>
  </form>;
}
