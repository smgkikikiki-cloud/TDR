/** Thai display labels for canonical taxonomy values shared with Vehicle Master
 *  (`automotive/vehicle_master/vehreg/taxonomy.py`'s `THAI_LABELS`) -- one map
 *  per facet, so a value's label lives in exactly one place. */
export const BODY_LABEL: Record<string, string> = {
  "SEDAN": "ซีดาน",
  "HATCHBACK": "แฮทช์แบ็ก",
  "COUPE": "คูเป้",
  "CROSSOVER": "ครอสโอเวอร์ / SUV โมโนค็อก",
  "PPV": "PPV พื้นฐานกระบะ",
  "OFFROAD": "SUV ออฟโรดโครงแชสซีส์",
  "MPV": "MPV",
  "PICKUP": "กระบะ",
  "WAGON": "แวกอน",
  "VAN": "รถตู้",
  "TRUCK": "รถบรรทุก",
};

/** Falls back to the stored value, so a body type that is not in the map
 *  (an older row, a value added in admin) still shows what the record says. */
export function bodyLabel(value: any) {
  return value ? BODY_LABEL[value] || value : null;
}

/** The exact canonical string this codebase uses for a pickup body type --
 *  see `automotive/vehicle_master/vehreg/taxonomy.py`'s `BodyType.PICKUP`. */
export const PICKUP_BODY_TYPE = "PICKUP";

/** Mirrors `THAI_LABELS["CabType"]` in taxonomy.py exactly, so this codebase
 *  never invents a second translation for the same enum. Cab type is only
 *  ever meaningful on a pickup -- see PICKUP_BODY_TYPE. */
export const CAB_LABEL: Record<string, string> = {
  "DOUBLE_CAB": "แค็บ 4 ประตู (รย.1)",
  "SINGLE_SMART": "ตอนเดียว/แค็บ (รย.3)",
  "SMART_CAB": "แค็บ/สเปซแค็บ",
  "SINGLE_CAB": "ตอนเดียว",
};

export function cabLabel(value: any) {
  return value ? CAB_LABEL[value] || value : null;
}

/** Retail lifecycle status (`automotive/vehicle_master/vehreg/entities.py`'s
 *  `RetailStatus`: CURRENT | HISTORICAL | UNVERIFIED). No canonical Thai
 *  copy exists for these yet -- only English/technical admin-facing usage --
 *  so this is the one public-facing translation, kept here rather than
 *  invented again at the call site. */
export const RETAIL_STATUS_LABEL: Record<string, string> = {
  "CURRENT": "ปัจจุบัน",
  "HISTORICAL": "เลิกขายแล้ว",
  "UNVERIFIED": "รอยืนยันข้อมูล",
};

export function retailStatusLabel(value: any) {
  return value ? RETAIL_STATUS_LABEL[value] || value : null;
}
