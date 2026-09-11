import { compareValue, type CompareRowKey, type FreeCompareTrim } from "@/lib/free-compare";

export type CompareSpecFact = {
  fact_id?: string;
  trim_id: string;
  field_key: string;
  value_state?: "KNOWN" | "UNKNOWN" | "NOT_AVAILABLE" | "NOT_APPLICABLE" | string;
  value?: unknown;
  unit?: string | null;
  qualifiers?: Record<string, unknown> | null;
  effective_from?: string | null;
  observed_at?: string | null;
  verification_status?: string | null;
};

type CoreRow = { id: string; label: string; source: "core"; key: CompareRowKey };
type SpecRow = { id: string; label: string; source: "spec"; key: string };
export type WorkspaceCompareRow = CoreRow | SpecRow;
export type WorkspaceCompareSection = { id: string; title: string; rows: WorkspaceCompareRow[] };

const core = (key: CompareRowKey, label: string): CoreRow => ({ id: `core:${key}`, label, source: "core", key });
const spec = (key: string, label: string): SpecRow => ({ id: `spec:${key}`, label, source: "spec", key });

export const QUICK_COMPARE_ROWS: WorkspaceCompareRow[] = [
  core("price", "ราคา"),
  core("powertrain", "Powertrain"),
  core("power", "กำลังสูงสุด"),
  core("torque_nm", "แรงบิดสูงสุด"),
  core("wheelbase_mm", "ฐานล้อ"),
  core("seats", "จำนวนที่นั่ง"),
  core("range", "ระยะทาง EV"),
  spec("technology.infotainment_screen_in", "หน้าจอกลาง"),
  spec("safety.airbag_count", "ถุงลมนิรภัย"),
  spec("safety.adaptive_cruise", "Adaptive Cruise"),
  spec("safety.aeb", "AEB"),
  spec("safety.blind_spot", "Blind Spot"),
];

export const WORKSPACE_COMPARE_SECTIONS: WorkspaceCompareSection[] = [
  {
    id: "identity",
    title: "รุ่นและราคา",
    rows: [
      core("price", "ราคาปัจจุบัน"), core("campaign", "แคมเปญปัจจุบัน"),
      core("segment", "Segment"), core("body_type", "ตัวถัง"),
    ],
  },
  {
    id: "powertrain",
    title: "เครื่องยนต์และระบบขับเคลื่อน",
    rows: [
      core("powertrain", "Powertrain"), core("engine_cc", "ความจุเครื่องยนต์"),
      core("battery_kwh", "ความจุแบตเตอรี่"), core("power", "กำลังสูงสุด"),
      core("torque_nm", "แรงบิดสูงสุด"), core("drivetrain", "ระบบขับเคลื่อน"),
      core("transmission", "ระบบส่งกำลัง"), core("range", "ระยะทางที่ผู้ผลิตประกาศ"),
    ],
  },
  {
    id: "dimensions",
    title: "ขนาดและการใช้งาน",
    rows: [
      core("length_mm", "ความยาว"), core("width_mm", "ความกว้าง"),
      core("height_mm", "ความสูง"), core("wheelbase_mm", "ฐานล้อ"),
      core("ground_clearance_mm", "ระยะใต้ท้อง"), core("seats", "จำนวนที่นั่ง"),
    ],
  },
  {
    id: "technology",
    title: "ห้องโดยสารและเทคโนโลยี",
    rows: [
      spec("technology.infotainment_screen_in", "ขนาดหน้าจอกลาง"),
      spec("technology.driver_display_in", "ขนาดหน้าจอผู้ขับขี่"),
      spec("technology.head_up_display", "Head-up display"),
      spec("technology.apple_carplay", "Apple CarPlay"),
      spec("technology.apple_carplay_wireless", "Apple CarPlay แบบไร้สาย"),
      spec("technology.android_auto", "Android Auto"),
      spec("technology.android_auto_wireless", "Android Auto แบบไร้สาย"),
      spec("technology.wireless_charger", "แท่นชาร์จโทรศัพท์ไร้สาย"),
      spec("technology.speaker_count", "จำนวนลำโพง"),
      spec("technology.branded_audio", "เครื่องเสียงแบรนด์"),
      spec("technology.usb_front_count", "พอร์ต USB ด้านหน้า"),
      spec("technology.usb_rear_count", "พอร์ต USB ด้านหลัง"),
    ],
  },
  {
    id: "safety",
    title: "ความปลอดภัยและ ADAS",
    rows: [
      spec("safety.airbag_count", "จำนวนถุงลมนิรภัย"),
      spec("safety.abs", "ABS"), spec("safety.ebd", "EBD"),
      spec("safety.brake_assist", "Brake Assist"),
      spec("safety.stability_control", "ระบบควบคุมการทรงตัว"),
      spec("safety.traction_control", "Traction Control"),
      spec("safety.hill_start_assist", "Hill Start Assist"),
      spec("safety.hill_descent_control", "Hill Descent Control"),
      spec("safety.tpms", "TPMS"), spec("safety.isofix", "ISOFIX"),
      spec("safety.aeb", "AEB"),
      spec("safety.forward_collision_warning", "Forward Collision Warning"),
      spec("safety.adaptive_cruise", "Adaptive Cruise Control"),
      spec("safety.adaptive_cruise_stop_go", "Adaptive Cruise · Stop & Go"),
      spec("safety.lane_keep_assist", "Lane Keep Assist"),
      spec("safety.lane_departure_warning", "Lane Departure Warning"),
      spec("safety.lane_departure_prevention", "Lane Departure Prevention"),
      spec("safety.blind_spot", "Blind-spot monitoring"),
      spec("safety.rear_cross_traffic", "Rear Cross Traffic Alert"),
      spec("safety.door_opening_warning", "Door Opening Warning"),
      spec("safety.auto_high_beam", "Auto High Beam"),
      spec("safety.traffic_sign_recognition", "Traffic Sign Recognition"),
      spec("safety.driver_monitoring", "Driver Monitoring"),
      spec("safety.camera_360", "กล้อง 360°"),
      spec("safety.parking_sensors_front", "เซ็นเซอร์กะระยะด้านหน้า"),
      spec("safety.parking_sensors_rear", "เซ็นเซอร์กะระยะด้านหลัง"),
      spec("safety.auto_park", "Auto Park"),
      spec("safety.ncap_stars", "คะแนน NCAP"),
    ],
  },
  {
    id: "production",
    title: "แหล่งผลิตและการรับประกัน",
    rows: [
      core("production_type", "นำเข้า / ประกอบ (ระดับรุ่น)"),
      core("production_country", "ประเทศที่ผลิต (ระดับรุ่น)"),
      core("warranty", "การรับประกันรถ"),
    ],
  },
];

function stamp(fact: CompareSpecFact) {
  return fact.effective_from || fact.observed_at || "";
}

export function factsByTrim(facts: CompareSpecFact[]) {
  const map = new Map<string, Map<string, CompareSpecFact>>();
  for (const fact of facts) {
    if (fact.verification_status && fact.verification_status !== "VERIFIED") continue;
    if (!map.has(fact.trim_id)) map.set(fact.trim_id, new Map());
    const bucket = map.get(fact.trim_id)!;
    const existing = bucket.get(fact.field_key);
    // Active releases should already contain resolved facts. If history is
    // present, use the newest verified assertion rather than merging values.
    if (!existing || stamp(fact) > stamp(existing)) bucket.set(fact.field_key, fact);
  }
  return map;
}

function numberDisplay(value: unknown, unit?: string | null) {
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  const digits = Math.abs(n % 1) > 0 ? 1 : 0;
  const text = n.toLocaleString("th-TH", { maximumFractionDigits: digits });
  if (!unit) return text;
  if (unit === "in") return `${text} นิ้ว`;
  if (unit === "airbag") return `${text} ใบ`;
  if (unit === "speaker") return `${text} ลำโพง`;
  if (unit === "port") return `${text} พอร์ต`;
  if (unit === "star") return `${text} ดาว`;
  return `${text} ${unit}`;
}

export type CompareCell = { display: string | null; token: string; known: boolean };

export function specCell(fact: CompareSpecFact | undefined): CompareCell {
  if (!fact) return { display: null, token: "UNKNOWN", known: false };
  const state = fact.value_state || "UNKNOWN";
  if (state === "NOT_APPLICABLE") return { display: "ไม่เกี่ยวข้อง", token: "NOT_APPLICABLE", known: true };
  if (state !== "KNOWN") return { display: null, token: state, known: false };
  if (typeof fact.value === "boolean") {
    return { display: fact.value ? "มี" : "ไม่มี", token: `BOOLEAN:${fact.value}`, known: true };
  }
  if (typeof fact.value === "number") {
    const display = numberDisplay(fact.value, fact.unit);
    return { display, token: `NUMBER:${fact.value}:${fact.unit || ""}`, known: true };
  }
  if (Array.isArray(fact.value)) {
    const display = fact.value.map(String).join(", ");
    return { display, token: `SET:${JSON.stringify(fact.value)}`, known: true };
  }
  const display = fact.value === null || fact.value === undefined || fact.value === "" ? null : String(fact.value);
  return { display, token: display === null ? "UNKNOWN" : `TEXT:${display}`, known: display !== null };
}

export function rowCell(
  trim: FreeCompareTrim,
  row: WorkspaceCompareRow,
  factMap: Map<string, Map<string, CompareSpecFact>>,
): CompareCell {
  if (row.source === "core") {
    const display = compareValue(trim, row.key);
    return { display, token: display === null ? "UNKNOWN" : `CORE:${display}`, known: display !== null };
  }
  return specCell(factMap.get(trim.id)?.get(row.key));
}

export function rowHasAnyKnown(
  trims: FreeCompareTrim[], row: WorkspaceCompareRow,
  factMap: Map<string, Map<string, CompareSpecFact>>,
) {
  return trims.some((trim) => rowCell(trim, row, factMap).known);
}

export function workspaceRowIsDifferent(
  trims: FreeCompareTrim[], row: WorkspaceCompareRow,
  factMap: Map<string, Map<string, CompareSpecFact>>,
) {
  if (trims.length < 2) return false;
  return new Set(trims.map((trim) => rowCell(trim, row, factMap).token)).size > 1;
}
