/** Display-only presentation of spec text for the Vehicle Database pages (P03 summaries, P04 spec table).
 *
 *  The comparison formatter (lib/free-compare.ts) joins a number, the registry's canonical unit and the fact's
 *  qualifiers into one string, so internal tokens leak through: "5 seat", "8 year", "7.9 s (DECLARED)",
 *  "130 kW (FRONT_MOTOR, DECLARED)". This file turns such strings into reader-facing text WITHOUT touching a value or a
 *  qualifier: the number is unchanged, every qualifier is still there (just in words), and nothing is dropped.
 *  Standard measurement names that are not internal tokens (NEDC, WLTP, CLTC, VDA, ...) and SI symbols (mm, kg, kW,
 *  kWh, Nm, cc, V, %, g/km, Wh/km) are already what a reader expects and are left alone.
 *
 *  Plain TypeScript, no imports (scripts/check-models.ts runs it under Node's type stripping). */

/** Count and non-SI units that follow a number. Longest first so "L/100km" wins over "L". */
const UNIT_WORDS: [string, string][] = [
  ["L/100km", "ลิตร/100 กม."], ["km/h", "กม./ชม."], ["airbag", "ใบ"], ["seat", "ที่นั่ง"], ["year", "ปี"],
  ["gear", "เกียร์"], ["motor", "มอเตอร์"], ["star", "ดาว"], ["min", "นาที"], ["km", "กม."], ["L", "ลิตร"], ["m", "ม."], ["s", "วินาที"],
];

/** Qualifier and enum tokens in words. Distinct tokens keep distinct wording. */
const TOKEN_WORDS: Record<string, string> = {
  DECLARED: "ตามที่ผู้ผลิตประกาศ", AS_DECLARED: "ตามที่ประกาศ", PEAK: "ค่าสูงสุด",
  ECO_STICKER_TH: "ECO Sticker (ไทย)", CURB_TO_CURB: "วัดแบบ curb-to-curb",
  FULL: "ระยะรวม", ELECTRIC_ONLY: "เฉพาะไฟฟ้า",
  SYSTEM: "ทั้งระบบ", FRONT_MOTOR: "มอเตอร์หน้า", REAR_MOTOR: "มอเตอร์หลัง", MOTOR: "มอเตอร์", ENGINE: "เครื่องยนต์",
  SEATS_UP: "เบาะตั้ง", REAR_FOLDED: "พับเบาะหลัง", ALL_SEATS_UP: "เบาะตั้งทุกที่นั่ง",
  UNLADEN: "ไม่บรรทุก", LADEN: "บรรทุก",
  LI_ION_UNSPECIFIED: "ลิเธียมไอออน (ไม่ระบุชนิด)", ONBOARD_AC: "AC บนรถ", EXTERNAL_DC: "DC ภายนอก", AC_INDUCTION: "AC induction",
  // single-word enum VALUES (a whole value, never a word inside free text such as a supplier or plant name)
  AUTOMATIC: "อัตโนมัติ", MANUAL: "เกียร์ธรรมดา", GASOLINE: "เบนซิน", DIESEL: "ดีเซล", OTHER: "อื่นๆ", BOTH: "ทั้งสองแบบ",
};

const UNIT_RE = new RegExp(`(\\d)\\s(${UNIT_WORDS.map(([u]) => u.replace(/[/]/g, "\\/")).join("|")})(?=$|[\\s(,;·)])`, "g");
const UNIT_BY = new Map(UNIT_WORDS);
const SNAKE_RE = /\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b/g;

/** Any remaining SCREAMING_SNAKE token ("SOME_NEW_VALUE" -> "some new value") so an internal enum never reaches the page. */
function humanize(token: string): string {
  return token.toLowerCase().replace(/_/g, " ");
}

/** One enum / qualifier token in words. Known tokens use the table; other underscore tokens are humanized;
 *  single-word names (NEDC, BEV, LFP, FWD, CCS2) are standard terms and stay as they are. */
export function tokenLabel(token: string): string {
  if (TOKEN_WORDS[token]) return TOKEN_WORDS[token];
  return token.includes("_") ? humanize(token) : token;
}

/** Words of a comma list (a qualifier group), each mapped only when it is exactly a known token. */
function mapList(list: string): string {
  return list.split(", ").map((part) => (TOKEN_WORDS[part] ? TOKEN_WORDS[part] : part)).join(", ");
}

/** Reader-facing text for a formatted spec string or label. Numbers and meaning are unchanged.
 *  Known qualifier / enum words are translated only where they are tokens: a whole value, inside a "( … )" qualifier
 *  group, or after the " — " of a row label. Elsewhere only underscore tokens are rewritten, so free text such as
 *  "TOYOTA MOTOR CORPORATION" is never touched. */
export function presentSpecText(text: string | null | undefined): string {
  if (text === null || text === undefined) return "";
  let out = String(text).replace(UNIT_RE, (_m, n: string, unit: string) => `${n} ${UNIT_BY.get(unit) ?? unit}`);
  out = out.replace(SNAKE_RE, (token) => tokenLabel(token));
  out = out.replace(/\(([^()]*)\)/g, (_m, inner: string) => `(${mapList(inner)})`);
  const dash = out.indexOf(" — ");
  if (dash >= 0) out = out.slice(0, dash + 3) + mapList(out.slice(dash + 3));
  else if (TOKEN_WORDS[out.trim()]) out = TOKEN_WORDS[out.trim()];
  return out;
}

/** A value the ledger holds as a placeholder (UNKNOWN / NOT_APPLICABLE) is not a value: the row is omitted. */
export function isNoValue(text: string): boolean {
  return /^(UNKNOWN|NOT_APPLICABLE)$/i.test(text.trim());
}

/** True when text still contains an internal SCREAMING_SNAKE token (used by the regression check). */
export function hasInternalToken(text: string): boolean {
  return /\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b/.test(text);
}
