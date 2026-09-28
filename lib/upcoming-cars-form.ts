import {
  isUpcomingTiming, type UpcomingTiming,
} from "./upcoming-cars-domain.ts";

function value(form: FormData, key: string): string {
  const entry = form.get(key);
  return typeof entry === "string" ? entry.trim() : "";
}

function number(value: string): number | null {
  if (!value) return null;
  if (!/^\d+$/.test(value)) throw new Error("ช่วงเปิดตัวต้องเป็นจำนวนเต็ม");
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed)) throw new Error("ช่วงเปิดตัวไม่ถูกต้อง");
  return parsed;
}

/** Server-side validation; fields from the inactive status are discarded. */
export function parseUpcomingCarForm(form: FormData) {
  const vehicleName = value(form, "vehicle_name");
  if (!vehicleName) throw new Error("กรุณาใส่ชื่อรถ");
  const status = value(form, "status");
  const timing: UpcomingTiming = {
    status: status as UpcomingTiming["status"],
    confidence: value(form, "confidence") as UpcomingTiming["confidence"],
    launchYear: number(value(form, "launch_year")) ?? 0,
    rumorHalf: status === "RUMORED"
      ? (value(form, "rumor_half") || null) as UpcomingTiming["rumorHalf"] : null,
    confirmedQuarter: status === "CONFIRMED"
      ? (value(form, "confirmed_quarter") || null) as UpcomingTiming["confirmedQuarter"] : null,
    confirmedMonth: status === "CONFIRMED" ? number(value(form, "confirmed_month")) : null,
    confirmedDay: status === "CONFIRMED" ? number(value(form, "confirmed_day")) : null,
  };
  if (!isUpcomingTiming(timing)) throw new Error("สถานะ ความมั่นใจ หรือช่วงเปิดตัวไม่ถูกต้อง");
  return {
    vehicle_name: vehicleName,
    status: timing.status,
    confidence: timing.confidence,
    launch_year: timing.launchYear,
    rumor_half: timing.rumorHalf,
    confirmed_quarter: timing.confirmedQuarter,
    confirmed_month: timing.confirmedMonth,
    confirmed_day: timing.confirmedDay,
    description: value(form, "description"),
    internal_notes: value(form, "internal_notes"),
  };
}

export function parseUpcomingUpdate(form: FormData) {
  const updateDate = value(form, "update_date");
  const message = value(form, "message");
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(updateDate);
  if (!match) throw new Error("วันที่อัปเดตไม่ถูกต้อง");
  const year = Number(match[1]), month = Number(match[2]), day = Number(match[3]);
  const date = new Date(Date.UTC(year, month - 1, day));
  if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) {
    throw new Error("วันที่อัปเดตไม่ถูกต้อง");
  }
  if (!message) throw new Error("กรุณาใส่ข้อความอัปเดต");
  return { update_date: updateDate, message };
}
