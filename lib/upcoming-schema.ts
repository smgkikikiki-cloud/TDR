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

function dateParts(value: string) {
  const [year, month, day] = value.split("-").map(Number);
  return { year, month, day };
}

const MONTHS = ["", "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."];

function quarter(month: number) {
  return Math.ceil(month / 3);
}

function half(month: number) {
  return month <= 6 ? 1 : 2;
}

export function launchWindowLabel(window: LaunchWindow) {
  if (window.precision === "UNKNOWN" || !window.start) return "ยังไม่ทราบกำหนด";
  const start = dateParts(window.start);
  const end = dateParts(window.end || window.start);
  if (window.precision === "YEAR") return start.year === end.year ? `${start.year}` : `${start.year}–${end.year}`;
  if (window.precision === "HALF") {
    const a = `H${half(start.month)} ${start.year}`;
    const b = `H${half(end.month)} ${end.year}`;
    return a === b ? a : `${a} – ${b}`;
  }
  if (window.precision === "QUARTER") {
    const a = `Q${quarter(start.month)} ${start.year}`;
    const b = `Q${quarter(end.month)} ${end.year}`;
    return a === b ? a : `${a} – ${b}`;
  }
  if (window.precision === "MONTH") {
    const a = `${MONTHS[start.month]} ${start.year}`;
    const b = `${MONTHS[end.month]} ${end.year}`;
    return a === b ? a : `${a} – ${b}`;
  }
  const a = `${start.day} ${MONTHS[start.month]} ${start.year}`;
  const b = `${end.day} ${MONTHS[end.month]} ${end.year}`;
  return a === b ? a : `${a} – ${b}`;
}

export function launchYear(vehicle: UpcomingVehicle) {
  return vehicle.launch_window.start ? dateParts(vehicle.launch_window.start).year : null;
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

    const window = vehicle.launch_window;
    if (!window || typeof window !== "object") problems.push(`${where}: launch_window is required`);
    else {
      if (!LAUNCH_PRECISIONS.includes(window.precision as LaunchPrecision)) problems.push(`${where}: invalid launch precision`);
      if (window.start !== null && !isoDate(window.start)) problems.push(`${where}: launch start must be null or YYYY-MM-DD`);
      if (window.end !== null && !isoDate(window.end)) problems.push(`${where}: launch end must be null or YYYY-MM-DD`);
      if (window.start && window.end && window.start > window.end) problems.push(`${where}: launch start cannot be after end`);
      if (window.precision === "UNKNOWN" && (window.start || window.end)) problems.push(`${where}: UNKNOWN launch window cannot carry dates`);
      if (window.precision !== "UNKNOWN" && !window.start) problems.push(`${where}: dated precision requires launch start`);
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
