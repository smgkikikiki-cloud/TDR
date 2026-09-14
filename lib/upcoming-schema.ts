export const UPCOMING_STATUSES = [
  "RUMORED", "EXPECTED", "CONFIRMED", "SCHEDULED", "DELAYED", "CANCELLED", "LAUNCHED",
] as const;
export type UpcomingStatus = (typeof UPCOMING_STATUSES)[number];

export const UPCOMING_VISIBILITIES = ["PUBLIC", "PRO", "INTERNAL"] as const;
export type UpcomingVisibility = (typeof UPCOMING_VISIBILITIES)[number];

export const LAUNCH_PRECISIONS = ["UNKNOWN", "YEAR", "HALF", "QUARTER", "MONTH", "EXACT_DATE"] as const;
export type LaunchPrecision = (typeof LAUNCH_PRECISIONS)[number];

export const FACT_SCOPES = ["THAI_MARKET", "GLOBAL_SPEC", "EXPECTED"] as const;
export type UpcomingFactScope = (typeof FACT_SCOPES)[number];

export const FACT_CERTAINTIES = ["CONFIRMED", "REPORTED", "EXPECTED"] as const;
export type UpcomingFactCertainty = (typeof FACT_CERTAINTIES)[number];

export const EVIDENCE_KINDS = ["OFFICIAL_THAI", "OEM_GLOBAL", "GOVERNMENT", "MEDIA", "DEALER", "OTHER"] as const;
export type UpcomingEvidenceKind = (typeof EVIDENCE_KINDS)[number];

/**
 * start/end deliberately preserve the source precision instead of inventing a
 * hidden exact date. Examples: 2027, 2027-H1, 2027-Q3, 2027-09, 2027-09-24.
 */
export type LaunchWindow = {
  start: string | null;
  end: string | null;
  precision: LaunchPrecision;
};

export type UpcomingFact = {
  field_key: string;
  label: string;
  value: string;
  scope: UpcomingFactScope;
  certainty: UpcomingFactCertainty;
  source_ref?: string | null;
};

export type UpcomingTimelineEntry = {
  date: string;
  title: string;
  note?: string | null;
  kind: UpcomingEvidenceKind;
  source_label?: string | null;
  source_url?: string | null;
};

export type UpcomingVehicle = {
  id: string;
  slug: string;
  market: "TH";
  brand: string;
  working_name: string;
  status: UpcomingStatus;
  visibility: UpcomingVisibility;
  launch_window: LaunchWindow;
  body_type?: string | null;
  segment?: string | null;
  powertrains?: string[];
  image_url?: string | null;
  summary?: string | null;
  linked_model_id?: string | null;
  facts?: UpcomingFact[];
  timeline: UpcomingTimelineEntry[];
  first_seen: string;
  updated_at: string;
};

export type UpcomingDataset = {
  schema_version: 1;
  vehicles: UpcomingVehicle[];
};

const STATUS_LABEL: Record<UpcomingStatus, string> = {
  RUMORED: "มีข่าวลือ",
  EXPECTED: "คาดว่าจะมา",
  CONFIRMED: "ยืนยันเข้าไทย",
  SCHEDULED: "มีกำหนดเปิดตัว",
  DELAYED: "เลื่อนกำหนด",
  CANCELLED: "ยกเลิก",
  LAUNCHED: "เปิดตัวแล้ว",
};

const FACT_SCOPE_LABEL: Record<UpcomingFactScope, string> = {
  THAI_MARKET: "ข้อมูลตลาดไทย",
  GLOBAL_SPEC: "สเปกต่างประเทศ",
  EXPECTED: "ข้อมูลที่คาดการณ์",
};

export function upcomingStatusLabel(status: UpcomingStatus) {
  return STATUS_LABEL[status];
}

export function upcomingFactScopeLabel(scope: UpcomingFactScope) {
  return FACT_SCOPE_LABEL[scope];
}

function isoDate(value: unknown) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const [year, month, day] = value.split("-").map(Number);
  const parsed = new Date(Date.UTC(year, month - 1, day));
  return parsed.getUTCFullYear() === year && parsed.getUTCMonth() === month - 1 && parsed.getUTCDate() === day;
}

function tokenMatchesPrecision(value: string | null, precision: LaunchPrecision) {
  if (value === null) return false;
  if (precision === "YEAR") return /^\d{4}$/.test(value);
  if (precision === "HALF") return /^\d{4}-H[12]$/.test(value);
  if (precision === "QUARTER") return /^\d{4}-Q[1-4]$/.test(value);
  if (precision === "MONTH") return /^\d{4}-(?:0[1-9]|1[0-2])$/.test(value);
  if (precision === "EXACT_DATE") return isoDate(value);
  return false;
}

function tokenYear(value: string) {
  return Number(value.slice(0, 4));
}

const MONTHS = ["", "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."];

function tokenLabel(value: string, precision: LaunchPrecision) {
  if (precision === "YEAR") return value;
  if (precision === "HALF") {
    const [year, half] = value.split("-");
    return `${half} ${year}`;
  }
  if (precision === "QUARTER") {
    const [year, quarter] = value.split("-");
    return `${quarter} ${year}`;
  }
  if (precision === "MONTH") {
    const [year, month] = value.split("-");
    return `${MONTHS[Number(month)]} ${year}`;
  }
  const [year, month, day] = value.split("-").map(Number);
  return `${day} ${MONTHS[month]} ${year}`;
}

export function launchWindowLabel(window: LaunchWindow) {
  if (window.precision === "UNKNOWN" || !window.start) return "ยังไม่ทราบกำหนด";
  const a = tokenLabel(window.start, window.precision);
  const b = window.end ? tokenLabel(window.end, window.precision) : a;
  return a === b ? a : `${a} – ${b}`;
}

/** Approximation is used only for ordering cards; the stored source value keeps
 * its original precision and is never rewritten as an exact date. */
export function launchWindowSortKey(window: LaunchWindow) {
  if (!window.start || window.precision === "UNKNOWN") return "9999-12-31";
  if (window.precision === "YEAR") return `${window.start}-01-01`;
  if (window.precision === "HALF") {
    const [year, half] = window.start.split("-");
    return `${year}-${half === "H1" ? "01" : "07"}-01`;
  }
  if (window.precision === "QUARTER") {
    const [year, quarter] = window.start.split("-");
    const month = { Q1: "01", Q2: "04", Q3: "07", Q4: "10" }[quarter] || "01";
    return `${year}-${month}-01`;
  }
  if (window.precision === "MONTH") return `${window.start}-01`;
  return window.start;
}

export function launchYear(vehicle: UpcomingVehicle) {
  return vehicle.launch_window.start ? tokenYear(vehicle.launch_window.start) : null;
}

export function validateUpcomingDataset(raw: unknown): string[] {
  const problems: string[] = [];
  if (!raw || typeof raw !== "object") return ["dataset must be an object"];
  const dataset = raw as Partial<UpcomingDataset> & { schema_version?: unknown; vehicles?: unknown };
  if (dataset.schema_version !== 1) problems.push("schema_version must be 1");
  if (!Array.isArray(dataset.vehicles)) return [...problems, "vehicles must be an array"];

  const ids = new Set<string>();
  const slugs = new Set<string>();
  for (const [index, vehicleRaw] of dataset.vehicles.entries()) {
    const where = `vehicles[${index}]`;
    if (!vehicleRaw || typeof vehicleRaw !== "object") {
      problems.push(`${where}: must be an object`);
      continue;
    }
    const vehicle = vehicleRaw as Partial<UpcomingVehicle>;
    if (!vehicle.id || typeof vehicle.id !== "string") problems.push(`${where}: id is required`);
    else if (ids.has(vehicle.id)) problems.push(`${where}: duplicate id ${vehicle.id}`);
    else ids.add(vehicle.id);
    if (!vehicle.slug || typeof vehicle.slug !== "string" || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(vehicle.slug)) problems.push(`${where}: slug must be lowercase kebab-case`);
    else if (slugs.has(vehicle.slug)) problems.push(`${where}: duplicate slug ${vehicle.slug}`);
    else slugs.add(vehicle.slug);
    if (vehicle.market !== "TH") problems.push(`${where}: market must be TH`);
    if (!vehicle.brand || !vehicle.working_name) problems.push(`${where}: brand and working_name are required`);
    if (!UPCOMING_STATUSES.includes(vehicle.status as UpcomingStatus)) problems.push(`${where}: invalid status`);
    if (!UPCOMING_VISIBILITIES.includes(vehicle.visibility as UpcomingVisibility)) problems.push(`${where}: invalid visibility`);
    if (!isoDate(vehicle.first_seen)) problems.push(`${where}: first_seen must be YYYY-MM-DD`);
    if (!isoDate(vehicle.updated_at)) problems.push(`${where}: updated_at must be YYYY-MM-DD`);
    if (vehicle.first_seen && vehicle.updated_at && vehicle.first_seen > vehicle.updated_at) problems.push(`${where}: first_seen cannot be after updated_at`);

    const window = vehicle.launch_window;
    if (!window || typeof window !== "object") problems.push(`${where}: launch_window is required`);
    else {
      if (!LAUNCH_PRECISIONS.includes(window.precision as LaunchPrecision)) problems.push(`${where}: invalid launch precision`);
      if (window.precision === "UNKNOWN") {
        if (window.start || window.end) problems.push(`${where}: UNKNOWN launch window cannot carry dates`);
      } else {
        if (!window.start) problems.push(`${where}: dated precision requires launch start`);
        else if (!tokenMatchesPrecision(window.start, window.precision)) problems.push(`${where}: launch start does not match ${window.precision} precision`);
        if (window.end && !tokenMatchesPrecision(window.end, window.precision)) problems.push(`${where}: launch end does not match ${window.precision} precision`);
        if (window.start && window.end && launchWindowSortKey({ ...window, end: null }) > launchWindowSortKey({ ...window, start: window.end, end: null })) problems.push(`${where}: launch start cannot be after end`);
      }
      if (vehicle.status === "SCHEDULED" && window.precision === "UNKNOWN") problems.push(`${where}: SCHEDULED requires a dated launch window`);
    }

    if (vehicle.status === "LAUNCHED" && !vehicle.linked_model_id) problems.push(`${where}: LAUNCHED requires linked_model_id`);
    if (vehicle.powertrains && (!Array.isArray(vehicle.powertrains) || vehicle.powertrains.some((value) => typeof value !== "string" || !value))) problems.push(`${where}: powertrains must be non-empty strings`);
    if (vehicle.facts && !Array.isArray(vehicle.facts)) problems.push(`${where}: facts must be an array`);
    for (const [factIndex, fact] of (vehicle.facts || []).entries()) {
      const factWhere = `${where}.facts[${factIndex}]`;
      if (!fact.field_key || !/^[a-z][a-z0-9_.]*$/.test(fact.field_key)) problems.push(`${factWhere}: invalid field_key`);
      if (!fact.label || !fact.value) problems.push(`${factWhere}: label and value are required`);
      if (!FACT_SCOPES.includes(fact.scope as UpcomingFactScope)) problems.push(`${factWhere}: invalid scope`);
      if (!FACT_CERTAINTIES.includes(fact.certainty as UpcomingFactCertainty)) problems.push(`${factWhere}: invalid certainty`);
    }

    if (!Array.isArray(vehicle.timeline)) problems.push(`${where}: timeline must be an array`);
    for (const [eventIndex, event] of (vehicle.timeline || []).entries()) {
      const eventWhere = `${where}.timeline[${eventIndex}]`;
      if (!isoDate(event.date)) problems.push(`${eventWhere}: date must be YYYY-MM-DD`);
      if (!event.title) problems.push(`${eventWhere}: title is required`);
      if (!EVIDENCE_KINDS.includes(event.kind as UpcomingEvidenceKind)) problems.push(`${eventWhere}: invalid evidence kind`);
      if (event.source_url && !/^https?:\/\//.test(event.source_url)) problems.push(`${eventWhere}: source_url must be http(s)`);
    }
  }
  return problems;
}
