"use client";

import { useState } from "react";
import { createUpcomingCar, updateUpcomingCar } from "@/app/admin/upcoming-actions";
import { Field, Select, TextArea } from "@/components/admin/Fields";
import type { UpcomingCarForAdmin } from "@/lib/upcoming-cars";

export function UpcomingCarForm({ car }: { car?: UpcomingCarForAdmin }) {
  const [status, setStatus] = useState(car?.status ?? "RUMORED");
  const [month, setMonth] = useState(car?.confirmedMonth?.toString() ?? "");
  return <form action={car ? updateUpcomingCar : createUpcomingCar} className="adminForm">
    {car ? <input type="hidden" name="vehicle_id" value={car.vehicleId} /> : null}
    <label className="adminField"><span>Upcoming Cars ID</span>
      <input value={car?.vehicleId ?? "สร้างอัตโนมัติเมื่อบันทึก"} readOnly aria-label="Upcoming Cars ID" />
    </label>
    <Field label="ชื่อรถ" name="vehicle_name" defaultValue={car?.vehicleName} required />
    <label className="adminField"><span>สถานะ</span>
      <select name="status" value={status} onChange={(event) => setStatus(event.target.value as "RUMORED" | "CONFIRMED")}>
        <option value="RUMORED">Rumored</option><option value="CONFIRMED">Confirmed launch</option>
      </select>
    </label>
    <Select label="ความมั่นใจ" name="confidence" defaultValue={car?.confidence ?? "MEDIUM"} required>
      <option value="HIGH">มาก</option><option value="MEDIUM">กลาง</option><option value="LOW">ต่ำ</option>
    </Select>
    <Field label="ปีที่คาดว่าจะเปิดตัว" name="launch_year" type="number" defaultValue={car?.launchYear} required />
    {status === "RUMORED" ? <Select label="ช่วงปี" name="rumor_half" defaultValue={car?.rumorHalf ?? "H1"} required>
      <option value="H1">H1 — ครึ่งปีแรก</option><option value="H2">H2 — ครึ่งปีหลัง</option>
    </Select> : <>
      {month ? <div className="adminField"><span>ไตรมาส</span><small>คำนวณจากเดือนที่ระบุ</small></div>
        : <Select label="ไตรมาส (ถ้าทราบ)" name="confirmed_quarter" defaultValue={car?.confirmedQuarter}>
        <option value="">ไม่ระบุ</option>
        <option value="Q1">Q1</option><option value="Q2">Q2</option>
        <option value="Q3">Q3</option><option value="Q4">Q4</option>
      </Select>}
      <label className="adminField"><span>เดือน (ถ้าทราบ; 1–12)</span>
        <input name="confirmed_month" type="number" min="1" max="12" value={month}
          onChange={(event) => setMonth(event.target.value)} />
      </label>
      <Field label="วัน (ถ้าทราบ; ต้องมีเดือน)" name="confirmed_day" type="number" defaultValue={car?.confirmedDay} />
    </>}
    <TextArea label="รายละเอียด" name="description" defaultValue={car?.description} rows={12} />
    <TextArea label="บันทึกภายใน (เฉพาะ Admin)" name="internal_notes" defaultValue={car?.internalNotes} rows={6} />
    <div className="adminFormActions"><button className="adminPrimary">{car ? "บันทึกการแก้ไข" : "สร้าง Upcoming Car"}</button></div>
  </form>;
}
