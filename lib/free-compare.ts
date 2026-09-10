export type FreeCompareTrim = {
  id: string;
  brand_name?: string | null;
  model_name?: string | null;
  name?: string | null;
  model_slug?: string | null;
  segment?: string | null;
  body_type?: string | null;
  powertrain?: string | null;
  drivetrain?: string | null;
  transmission?: string | null;
  engine_cc?: number | string | null;
  battery_kwh?: number | string | null;
  horsepower_ps?: number | string | null;
  motor_kw?: number | string | null;
  power_kw?: number | string | null;
  torque_nm?: number | string | null;
  length_mm?: number | string | null;
  width_mm?: number | string | null;
  height_mm?: number | string | null;
  wheelbase_mm?: number | string | null;
  ground_clearance_mm?: number | string | null;
  seats?: number | string | null;
  model_seats?: number | string | null;
  published_range_km?: number | string | null;
  published_range_cycle?: string | null;
  production_type?: string | null;
  production_country?: string | null;
  warranty?: string | null;
  vehicle_warranty?: string | null;
  price_baht?: number | string | null;
  campaign_quote?: any;
};

export type CompareRowKey =
  | "price"
  | "campaign"
  | "segment"
  | "body_type"
  | "powertrain"
  | "engine_cc"
  | "battery_kwh"
  | "power"
  | "torque_nm"
  | "drivetrain"
  | "transmission"
  | "range"
  | "length_mm"
  | "width_mm"
  | "height_mm"
  | "wheelbase_mm"
  | "ground_clearance_mm"
  | "seats"
  | "production_type"
  | "production_country"
  | "warranty";

export type CompareRowDefinition = {
  key: CompareRowKey;
  label: string;
};

export type CompareGroupDefinition = {
  title: string;
  rows: CompareRowDefinition[];
};

export const FREE_COMPARE_GROUPS: CompareGroupDefinition[] = [
  {
    title: "รุ่นและราคา",
    rows: [
      { key: "price", label: "ราคาปัจจุบัน" },
      { key: "campaign", label: "แคมเปญปัจจุบัน" },
      { key: "segment", label: "Segment" },
      { key: "body_type", label: "ตัวถัง" },
    ],
  },
  {
    title: "เครื่องยนต์และระบบขับเคลื่อน",
    rows: [
      { key: "powertrain", label: "Powertrain" },
      { key: "engine_cc", label: "ความจุเครื่องยนต์" },
      { key: "battery_kwh", label: "ความจุแบตเตอรี่" },
      { key: "power", label: "กำลังสูงสุด" },
      { key: "torque_nm", label: "แรงบิดสูงสุด" },
      { key: "drivetrain", label: "ระบบขับเคลื่อน" },
      { key: "transmission", label: "ระบบส่งกำลัง" },
      { key: "range", label: "ระยะทางที่ผู้ผลิตประกาศ" },
    ],
  },
  {
    title: "ขนาดและการใช้งาน",
    rows: [
      { key: "length_mm", label: "ความยาว" },
      { key: "width_mm", label: "ความกว้าง" },
      { key: "height_mm", label: "ความสูง" },
      { key: "wheelbase_mm", label: "ฐานล้อ" },
      { key: "ground_clearance_mm", label: "ระยะใต้ท้อง" },
      { key: "seats", label: "จำนวนที่นั่ง" },
    ],
  },
  {
    title: "แหล่งผลิตและการรับประกัน",
    rows: [
      { key: "production_type", label: "นำเข้า / ประกอบ (ระดับรุ่น)" },
      { key: "production_country", label: "ประเทศที่ผลิต (ระดับรุ่น)" },
      { key: "warranty", label: "การรับประกันรถ" },
    ],
  },
];

function number(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function baht(value: unknown): string | null {
  const n = number(value);
  return n && n > 0 ? `฿${Math.round(n).toLocaleString("th-TH")}` : null;
}

function numericUnit(value: unknown, unit: string, digits = 0): string | null {
  const n = number(value);
  if (n === null || n <= 0) return null;
  return `${n.toLocaleString("th-TH", { maximumFractionDigits: digits })} ${unit}`;
}

function activeCampaign(trim: FreeCompareTrim): string | null {
  const options = Array.isArray(trim.campaign_quote?.campaign_options)
    ? trim.campaign_quote.campaign_options.filter((option: any) => option?.status_as_of === "ACTIVE")
    : [];
  if (!options.length) return null;
  const offer = options[0];
  const money = baht(offer.amount_thb) || (baht(offer.discount_thb) ? `ลด ${baht(offer.discount_thb)}` : null);
  return [offer.option_label || offer.campaign_name, money].filter(Boolean).join(" · ") || "มีแคมเปญ";
}

function power(trim: FreeCompareTrim): string | null {
  const ps = numericUnit(trim.horsepower_ps, "PS");
  if (ps) return ps;
  const kw = numericUnit(trim.motor_kw ?? trim.power_kw, "kW", 1);
  return kw;
}

export function compareValue(trim: FreeCompareTrim, key: CompareRowKey): string | null {
  switch (key) {
    case "price": return baht(trim.price_baht);
    case "campaign": return activeCampaign(trim);
    case "segment": return trim.segment || null;
    case "body_type": return trim.body_type || null;
    case "powertrain": return trim.powertrain || null;
    case "engine_cc": return numericUnit(trim.engine_cc, "cc");
    case "battery_kwh": return numericUnit(trim.battery_kwh, "kWh", 1);
    case "power": return power(trim);
    case "torque_nm": return numericUnit(trim.torque_nm, "Nm");
    case "drivetrain": return trim.drivetrain || null;
    case "transmission": return trim.transmission || null;
    case "range": {
      const value = numericUnit(trim.published_range_km, "km");
      return value ? `${value}${trim.published_range_cycle ? ` ${trim.published_range_cycle}` : ""}` : null;
    }
    case "length_mm": return numericUnit(trim.length_mm, "mm");
    case "width_mm": return numericUnit(trim.width_mm, "mm");
    case "height_mm": return numericUnit(trim.height_mm, "mm");
    case "wheelbase_mm": return numericUnit(trim.wheelbase_mm, "mm");
    case "ground_clearance_mm": return numericUnit(trim.ground_clearance_mm, "mm");
    case "seats": return numericUnit(trim.seats ?? trim.model_seats, "ที่นั่ง");
    case "production_type": return trim.production_type === "MIXED" ? "MIXED · ต่างกันตามรุ่นย่อย/ช่วงเวลา" : trim.production_type || null;
    case "production_country": return trim.production_country === "MIXED" ? "MIXED · ต่างกันตามรุ่นย่อย/ช่วงเวลา" : trim.production_country || null;
    case "warranty": return trim.vehicle_warranty || trim.warranty || null;
  }
}

export function rowHasAnyValue(trims: FreeCompareTrim[], key: CompareRowKey): boolean {
  return trims.some((trim) => compareValue(trim, key) !== null);
}

export function rowIsDifferent(trims: FreeCompareTrim[], key: CompareRowKey): boolean {
  if (trims.length < 2) return false;
  const values = trims.map((trim) => compareValue(trim, key) ?? "__MISSING__");
  return new Set(values).size > 1;
}

export function visibleCompareGroups(trims: FreeCompareTrim[], differencesOnly = false) {
  return FREE_COMPARE_GROUPS
    .map((group) => ({
      ...group,
      rows: group.rows.filter((row) => rowHasAnyValue(trims, row.key)
        && (!differencesOnly || rowIsDifferent(trims, row.key))),
    }))
    .filter((group) => group.rows.length > 0);
}
