/** Thai display labels for the stored body_type values. Presentation only —
 *  the values written to and read from the database are unchanged. */
export const BODY_LABEL: Record<string, string> = {
  "Sedan": "ซีดาน",
  "Hatchback": "แฮทช์แบ็ก",
  "Coupe": "คูเป้",
  "Crossover": "ครอสโอเวอร์",
  "SUV (Monocoque)": "SUV โมโนค็อก",
  "SUV (Ladder frame)": "SUV โครงกระบะ (PPV)",
  "MPV": "MPV",
  "Pickup truck": "กระบะ",
  "Van": "รถตู้",
};

/** Falls back to the stored value, so a body type that is not in the map
 *  (an older row, a value added in admin) still shows what the record says. */
export function bodyLabel(value: any) {
  return value ? BODY_LABEL[value] || value : null;
}
