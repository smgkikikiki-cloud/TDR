/** Thai display labels for the canonical body_type values shared with Vehicle Master. */
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
