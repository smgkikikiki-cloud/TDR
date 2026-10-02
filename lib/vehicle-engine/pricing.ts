/**
 * Price ledger and campaigns, ported from
 * automotive/vehicle_master/vehreg/pricing.py, vehreg/product.py (correct_price,
 * close_price) and vehreg/canonical_write.py (APPEND_PRICE's same-day rule).
 * ENGINE_INVENTORY §4.6, §5.4.
 *
 * Placement (supabase/migration_v59_vehicle_engine_rules.sql):
 * - PriceRecord.validate and Campaign.validate are CHECK constraints, the
 *   same-start conflict rule is a deferred trigger, and the ledger is
 *   append-only in the database. They are not repeated here.
 * - Here: turning raw input into the stored row (parse), the resolution rules
 *   every computed price value comes from, and the write planners that decide
 *   append / no-op / retract-and-replace / supersede / close.
 *
 * Dates are ISO `YYYY-MM-DD` strings; comparing them as strings is what the
 * Python code does too.
 */

type Row = Record<string, any>;

export class PricingError extends Error {}

export const PRICE_TYPES = [
  "LIST_PRICE", "INTRODUCTORY_PRICE", "CAMPAIGN_PRICE", "FINANCE_PRICE",
  "ESTIMATED_PRICE", "DEALER_PRICE", "ECO_STICKER_PRICE", "UNKNOWN",
] as const;
const CAMPAIGN_TYPES = new Set(["CAMPAIGN_PRICE", "FINANCE_PRICE"]);
const OFFER_STATUSES = ["ACTIVE", "SOLD_OUT", "WITHDRAWN", "SUPERSEDED"];

/** PriceRecord fields in dataclass order (to_jsonable key order). */
export const PRICE_FIELDS = [
  "trim_id", "amount_thb", "price_type", "effective_from", "effective_to", "observed_at",
  "source", "source_ref", "source_document_id", "notes", "campaign_id", "option_id",
  "reference_price_thb", "retracted_at", "retraction_reason", "reviewed_by",
] as const;

function repr(value: unknown): string {
  if (typeof value === "string") return `'${value}'`;
  if (value === null || value === undefined) return "None";
  if (value === true) return "True";
  if (value === false) return "False";
  return String(value);
}

const str = (value: unknown) => (value === null || value === undefined ? "" : String(value));
/** Python `str(raw or "")` */
const orEmpty = (value: unknown) => (value === null || value === undefined || value === false || value === 0 || value === "" ? "" : String(value));

/** `YYYY-MM-DD` that datetime.date.fromisoformat accepts (year 1..9999, real day). */
export function isValidIsoDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const [y, m, d] = value.split("-").map(Number);
  if (y < 1 || m < 1 || m > 12 || d < 1) return false;
  const leap = (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0;
  return d <= [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1];
}

/** pricing._iso_date */
export function isoDate(raw: unknown, field: string): string | null {
  if (raw === null || raw === undefined || raw === "") return null;
  const value = String(raw);
  if (!isValidIsoDate(value)) throw new PricingError(`${field} must be YYYY-MM-DD, got ${repr(value)}`);
  return value;
}

export function dayBefore(day: string): string {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d - 1)).toISOString().slice(0, 10);
}

/** PriceType.parse */
export function parsePriceType(raw: unknown): string {
  const value = (orEmpty(raw) || "UNKNOWN").trim().toUpperCase();
  if (!(PRICE_TYPES as readonly string[]).includes(value)) throw new PricingError(`unknown price_type ${repr(raw)}`);
  return value;
}

function digits(raw: unknown): boolean {
  return typeof raw !== "boolean" && raw !== null && raw !== undefined && /^[0-9]+$/.test(String(raw));
}

/**
 * PriceLedger.add_payload, for one raw row: the stored row
 * (to_jsonable(PriceRecord)), or the parse error Python raises before
 * PriceRecord.validate runs. Validation of the parsed row is the
 * vm_rule_price_validate CHECK.
 */
export function parsePriceRow(raw: unknown, knownTrimIds?: ReadonlySet<string>): Row {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new PricingError("price row must be an object");
  const row = raw as Row;
  const unknown = Object.keys(row).filter((k) => !(PRICE_FIELDS as readonly string[]).includes(k)).sort();
  if (unknown.length) throw new PricingError(`unknown price fields: [${unknown.map((k) => `'${k}'`).join(", ")}]`);
  const trimId = orEmpty(row.trim_id).trim();
  if (knownTrimIds && !knownTrimIds.has(trimId)) throw new PricingError(`unknown trim_id ${repr(trimId)}`);
  if (!("amount_thb" in row) || !digits(row.amount_thb)) throw new PricingError(`invalid amount_thb for ${repr(trimId)}`);
  let reference: number | null = null;
  if (row.reference_price_thb !== null && row.reference_price_thb !== undefined) {
    if (!digits(row.reference_price_thb)) throw new PricingError(`invalid reference_price_thb for ${repr(trimId)}`);
    reference = Number(row.reference_price_thb);
  }
  return {
    trim_id: trimId,
    amount_thb: Number(row.amount_thb),
    price_type: parsePriceType(row.price_type),
    effective_from: isoDate(row.effective_from, "effective_from"),
    effective_to: isoDate(row.effective_to, "effective_to"),
    observed_at: isoDate(row.observed_at, "observed_at"),
    source: orEmpty(row.source).trim(),
    source_ref: orEmpty(row.source_ref).trim(),
    source_document_id: orEmpty(row.source_document_id).trim(),
    notes: orEmpty(row.notes),
    campaign_id: orEmpty(row.campaign_id).trim() || null,
    option_id: orEmpty(row.option_id).trim() || null,
    reference_price_thb: reference,
    retracted_at: isoDate(row.retracted_at, "retracted_at"),
    retraction_reason: orEmpty(row.retraction_reason).trim(),
    reviewed_by: orEmpty(row.reviewed_by).trim(),
  };
}

const CAMPAIGN_FIELDS = ["id", "brand_id", "name", "starts", "ends", "source", "source_ref", "options", "quota_units", "gifts", "notes"];
const OPTION_FIELDS = ["id", "label", "conditions", "starts", "ends", "status", "closed_at", "notes"];
const CONDITION_FIELDS = ["booking_from", "booking_to", "delivery_by", "quota_units", "finance_required", "text"];

function quota(raw: unknown): number | null {
  if (raw === null || raw === undefined) return null;
  if (!digits(raw)) throw new PricingError("quota_units must be a positive integer");
  return Number(raw);
}

function parseConditions(raw: unknown): Row {
  const empty = { booking_from: null, booking_to: null, delivery_by: null, quota_units: null, finance_required: false, text: "" };
  if (raw === null || raw === undefined || (typeof raw === "object" && !Array.isArray(raw) && !Object.keys(raw as object).length)) return empty;
  if (typeof raw !== "object" || Array.isArray(raw)) throw new PricingError("conditions must be an object");
  const row = raw as Row;
  const unknown = Object.keys(row).filter((k) => !CONDITION_FIELDS.includes(k)).sort();
  if (unknown.length) throw new PricingError(`unknown condition fields: [${unknown.map((k) => `'${k}'`).join(", ")}]`);
  const financeRequired = "finance_required" in row ? row.finance_required : false;
  if (typeof financeRequired !== "boolean") throw new PricingError("finance_required must be boolean");
  return {
    booking_from: isoDate(row.booking_from, "booking_from"),
    booking_to: isoDate(row.booking_to, "booking_to"),
    delivery_by: isoDate(row.delivery_by, "delivery_by"),
    quota_units: quota(row.quota_units),
    finance_required: financeRequired,
    text: orEmpty(row.text).trim(),
  };
}

function parseOfferStatus(raw: unknown): string {
  const value = (orEmpty(raw) || "ACTIVE").trim().toUpperCase();
  if (!OFFER_STATUSES.includes(value)) throw new PricingError(`unknown offer status ${repr(raw)}`);
  return value;
}

/**
 * pricing._parse_campaign: the stored campaign payload (to_jsonable(Campaign)),
 * or Python's parse error. Campaign.validate is the vm_rule_campaign_validate
 * CHECK.
 */
export function parseCampaign(raw: unknown): Row {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new PricingError("campaign must be an object");
  const row = raw as Row;
  const unknown = Object.keys(row).filter((k) => !CAMPAIGN_FIELDS.includes(k)).sort();
  if (unknown.length) throw new PricingError(`unknown campaign fields: [${unknown.map((k) => `'${k}'`).join(", ")}]`);
  const options = row.options || [];
  if (!Array.isArray(options)) throw new PricingError("campaign options must be an array");
  const parsed = options.map((option: unknown) => {
    if (!option || typeof option !== "object" || Array.isArray(option)) throw new PricingError("campaign option must be an object");
    const o = option as Row;
    const extra = Object.keys(o).filter((k) => !OPTION_FIELDS.includes(k)).sort();
    if (extra.length) throw new PricingError(`unknown option fields: [${extra.map((k) => `'${k}'`).join(", ")}]`);
    return {
      id: orEmpty(o.id).trim(),
      label: orEmpty(o.label).trim(),
      conditions: parseConditions(o.conditions),
      starts: isoDate(o.starts, "starts"),
      ends: isoDate(o.ends, "ends"),
      status: parseOfferStatus(o.status),
      closed_at: isoDate(o.closed_at, "closed_at"),
      notes: orEmpty(o.notes),
    };
  });
  return {
    id: orEmpty(row.id).trim(),
    brand_id: orEmpty(row.brand_id).trim(),
    name: orEmpty(row.name).trim(),
    starts: isoDate(row.starts, "starts"),
    ends: isoDate(row.ends, "ends"),
    source: orEmpty(row.source).trim(),
    source_ref: orEmpty(row.source_ref).trim(),
    options: parsed,
    quota_units: quota(row.quota_units),
    gifts: orEmpty(row.gifts),
    notes: orEmpty(row.notes),
  };
}

// ---------------------------------------------------------------------------
// Resolution (§5.4)
// ---------------------------------------------------------------------------

const start = (r: Row): string | null => r.effective_from || r.observed_at || null;
const retracted = (r: Row) => Boolean(r.retracted_at);

/** PriceRecord.active_on */
export function activeOn(r: Row, day: string): boolean {
  const s = start(r);
  if (s && s > day) return false;
  if (r.effective_to && r.effective_to < day) return false;
  return true;
}

function sortKey(r: Row): [string, string, number] {
  return [start(r) || "0001-01-01", r.observed_at || "0001-01-01", Number(r.amount_thb)];
}

function compareKeys(a: Row, b: Row): number {
  const ka = sortKey(a);
  const kb = sortKey(b);
  for (let i = 0; i < 3; i++) {
    if (ka[i] < kb[i]) return -1;
    if (ka[i] > kb[i]) return 1;
  }
  return 0;
}

/** PriceLedger.records_for (stable sort, like Python's sorted). */
export function recordsFor(rows: Row[], trimId: string, opts: { priceType?: string; includeRetracted?: boolean } = {}): Row[] {
  return rows
    .filter((r) => r.trim_id === trimId && (opts.includeRetracted || !retracted(r)))
    .filter((r) => !opts.priceType || r.price_type === opts.priceType)
    .map((r, i) => ({ r, i }))
    .sort((a, b) => compareKeys(a.r, b.r) || a.i - b.i)
    .map(({ r }) => r);
}

/** PriceLedger.current_price_for_scope */
export function currentPriceForScope(rows: Row[], trimId: string, priceType: string, asOf: string,
  campaignId: string | null = null, optionId: string | null = null): Row | null {
  let candidates = recordsFor(rows, trimId, { priceType });
  if (CAMPAIGN_TYPES.has(priceType)) {
    if (!campaignId || !optionId) return null;
    candidates = candidates.filter((r) => r.campaign_id === campaignId && r.option_id === optionId);
  }
  candidates = candidates.filter((r) => (start(r) || "9999-12-31") <= asOf);
  if (!candidates.length) return null;
  const latestStart = candidates.map((r) => start(r)!).reduce((a, b) => (b > a ? b : a));
  const latest = candidates.filter((r) => start(r) === latestStart && activeOn(r, asOf));
  if (new Set(latest.map((r) => Number(r.amount_thb))).size > 1) {
    if (priceType === "LIST_PRICE") throw new PricingError(`${trimId}: conflicting LIST_PRICE at ${latestStart}; review required`);
    let scope = `${trimId} ${priceType}`;
    if (campaignId || optionId) scope += ` ${campaignId || ""}/${optionId || ""}`;
    throw new PricingError(`${scope}: conflicting canonical prices at ${latestStart}; review required`);
  }
  return latest.length ? latest[latest.length - 1] : null;
}

export const currentListPrice = (rows: Row[], trimId: string, asOf: string) =>
  currentPriceForScope(rows, trimId, "LIST_PRICE", asOf);

export function currentListAmount(rows: Row[], trimId: string, asOf: string): number | null {
  const row = currentListPrice(rows, trimId, asOf);
  return row ? Number(row.amount_thb) : null;
}

function campaignLiveOn(campaign: Row, day: string): boolean {
  if (campaign.starts && day < campaign.starts) return false;
  if (campaign.ends && day > campaign.ends) return false;
  return true;
}

function optionOpenOn(option: Row, day: string): boolean {
  if (option.closed_at && day >= option.closed_at) return false;
  if (option.status !== "ACTIVE" && !option.closed_at) return false;
  if (option.starts && day < option.starts) return false;
  if (option.ends && day > option.ends) return false;
  const c = option.conditions || {};
  if (c.booking_from && day < c.booking_from) return false;
  if (c.booking_to && day > c.booking_to) return false;
  return true;
}

/** CampaignOption.status_on: what the option was on `day`, never what it is now. */
export function optionStatusOn(option: Row, day: string): string {
  if (option.closed_at) return day >= option.closed_at ? option.status : "ACTIVE";
  return option.status;
}

/** PriceLedger.current_campaign_offers */
export function currentCampaignOffers(rows: Row[], campaigns: Map<string, Row>, trimId: string, asOf: string): Row[] {
  const scopes = new Map<string, [string, string, string]>();
  for (const r of recordsFor(rows, trimId)) {
    if (!CAMPAIGN_TYPES.has(r.price_type)) continue;
    if (r.campaign_id && r.option_id) scopes.set(`${r.price_type}\u0000${r.campaign_id}\u0000${r.option_id}`, [r.price_type, r.campaign_id, r.option_id]);
  }
  const ordered = [...scopes.values()].sort((a, b) =>
    (a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : 0) || (a[2] < b[2] ? -1 : a[2] > b[2] ? 1 : 0) || (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
  const live: Row[] = [];
  for (const [priceType, campaignId, optionId] of ordered) {
    const record = currentPriceForScope(rows, trimId, priceType, asOf, campaignId, optionId);
    if (!record) continue;
    const campaign = campaigns.get(campaignId);
    if (campaign) {
      if (!campaignLiveOn(campaign, asOf)) continue;
      const option = (campaign.options || []).find((o: Row) => o.id === optionId);
      if (option && !optionOpenOn(option, asOf)) continue;
    }
    live.push(record);
  }
  return live;
}

/** pricing.to_conditions_dict: only the non-empty parts. */
export function conditionsDict(c: Row): Row {
  const payload: Row = {
    booking_from: c.booking_from ?? null, booking_to: c.booking_to ?? null, delivery_by: c.delivery_by ?? null,
    quota_units: c.quota_units ?? null, finance_required: c.finance_required ?? false, text: c.text ?? "",
  };
  return Object.fromEntries(Object.entries(payload).filter(([, v]) => v !== null && v !== "" && v !== false));
}

/** PriceLedger.campaign_quote (served shape unchanged, v3 §7). */
export function campaignQuote(rows: Row[], campaigns: Map<string, Row>, trimId: string, asOf: string): Row {
  const listed = currentListPrice(rows, trimId, asOf);
  const offers = currentCampaignOffers(rows, campaigns, trimId, asOf).map((record) => {
    const campaign = campaigns.get(record.campaign_id || "");
    const option = campaign ? (campaign.options || []).find((o: Row) => o.id === (record.option_id || "")) : undefined;
    const optionQuota = option ? option.conditions?.quota_units ?? null : null;
    return {
      amount_thb: record.amount_thb,
      price_type: record.price_type,
      reference_price_thb: record.reference_price_thb ?? null,
      discount_thb: record.reference_price_thb == null ? null : record.reference_price_thb - record.amount_thb,
      campaign_id: record.campaign_id,
      campaign_name: campaign ? campaign.name : "",
      gifts: campaign ? campaign.gifts : "",
      campaign_starts: campaign ? campaign.starts : null,
      campaign_ends: campaign ? campaign.ends : null,
      option_id: record.option_id,
      option_label: option ? option.label : "",
      status_as_of: option ? optionStatusOn(option, asOf) : null,
      current_status: option ? option.status : null,
      closed_at: option ? option.closed_at : null,
      conditions: option ? conditionsDict(option.conditions || {}) : {},
      quota_units: (option ? optionQuota : null) || (campaign ? campaign.quota_units : null),
      quota_scope: option && optionQuota ? "OPTION" : campaign && campaign.quota_units ? "CAMPAIGN" : null,
      valid_to: record.effective_to,
      source: record.source,
      source_ref: record.source_ref,
      source_document_id: record.source_document_id || null,
    };
  });
  return { trim_id: trimId, as_of: asOf, list_price_thb: listed ? listed.amount_thb : null, campaign_options: offers };
}

// ---------------------------------------------------------------------------
// Write planners. Each returns the edits Python would make; it never writes.
// ---------------------------------------------------------------------------

export type PriceEdit =
  | { kind: "update"; recordIndex: number; changes: Row }
  | { kind: "append"; row: Row };

export type PricePlan =
  | { changed: false; note?: string }
  | { changed: true; edits: PriceEdit[] };

/** product._matches + _live_on + _one_live_row */
function oneLiveRow(rows: Row[], trimId: string, priceType: string, campaignId: string | null,
  optionId: string | null, asOf: string): number {
  const matches = rows
    .map((row, index) => ({ row, index }))
    .filter(({ row }) => row.trim_id === trimId && row.price_type === priceType
      && (campaignId === null || (row.campaign_id || null) === campaignId)
      && (optionId === null || (row.option_id || null) === optionId)
      && !row.retracted_at)
    .filter(({ row }) => activeOn(row, asOf));
  if (!matches.length) throw new PricingError(`${trimId}: no live ${priceType} to change on ${asOf}`);
  if (matches.length > 1) {
    const amounts = matches.map(({ row }) => Number(row.amount_thb).toLocaleString("en-US")).join(", ");
    throw new PricingError(`${trimId}: ${matches.length} live ${priceType} rows (${amounts}); name the campaign/option, or fix the overlap first`);
  }
  return matches[0].index;
}

export type CorrectPriceArgs = {
  trimId: string; priceType: string; amountThb: number; reason: string; reviewer: string;
  mode?: "supersede" | "retract"; effectiveFrom?: string | null; campaignId?: string | null; optionId?: string | null;
  source?: string; sourceRef?: string; sourceDocumentId?: string; referencePriceThb?: number | null; asOf: string;
};

/** product.correct_price */
export function planCorrectPrice(rows: Row[], args: CorrectPriceArgs): PricePlan {
  const mode = args.mode ?? "supersede";
  if (mode !== "supersede" && mode !== "retract") throw new PricingError(`unknown mode '${mode}'`);
  if (!args.reason || !args.reviewer) throw new PricingError("a correction requires both a reason and a reviewer");
  const today = args.asOf;
  const starts = args.effectiveFrom || today;
  const index = oneLiveRow(rows, args.trimId, args.priceType, args.campaignId ?? null, args.optionId ?? null, args.asOf);
  const old = rows[index];
  if (Number(old.amount_thb) === args.amountThb && mode === "supersede") {
    return { changed: false, note: "the live price already says that" };
  }
  const oldStart = start(old);
  if (mode === "supersede" && oldStart && oldStart >= starts) {
    throw new PricingError(`${args.trimId}: the live price starts ${oldStart}, so it cannot end before ${starts}; use --mode retract if it was simply wrong`);
  }
  const closing: Row = mode === "supersede"
    ? { effective_to: dayBefore(starts) }
    : { retracted_at: today, retraction_reason: args.reason };
  closing.reviewed_by = args.reviewer;
  const replacement: Row = {
    trim_id: args.trimId, amount_thb: args.amountThb, price_type: args.priceType,
    effective_from: starts, observed_at: today,
    source: args.source || old.source || "", source_ref: args.sourceRef || old.source_ref || "",
    notes: args.reason, reviewed_by: args.reviewer,
  };
  for (const [name, value] of [["campaign_id", args.campaignId ?? null], ["option_id", args.optionId ?? null],
    ["reference_price_thb", args.referencePriceThb ?? null], ["source_document_id", args.sourceDocumentId || null]] as const) {
    if (value !== null && value !== undefined) replacement[name] = value;
  }
  return { changed: true, edits: [{ kind: "update", recordIndex: index, changes: closing }, { kind: "append", row: replacement }] };
}

/** product.close_price */
export function planClosePrice(rows: Row[], args: {
  trimId: string; priceType: string; ends: string; reason: string; reviewer: string;
  campaignId?: string | null; optionId?: string | null; asOf: string;
}): PricePlan {
  if (!args.reason || !args.reviewer) throw new PricingError("closing a price requires both a reason and a reviewer");
  isoDate(args.ends, "ends");
  const index = oneLiveRow(rows, args.trimId, args.priceType, args.campaignId ?? null, args.optionId ?? null, args.asOf);
  const s = start(rows[index]);
  if (s && s > args.ends) throw new PricingError(`${args.trimId}: cannot end on ${args.ends}, the price starts ${s}`);
  return { changed: true, edits: [{ kind: "update", recordIndex: index, changes: { effective_to: args.ends, reviewed_by: args.reviewer, notes: args.reason } }] };
}

/**
 * canonical_write._append_price's decision: the same number again on the same
 * start is a no-op; a different number on the same start retracts the live row
 * and replaces it (correct_price mode=retract); anything else appends.
 */
export function planAppendPrice(rows: Row[], record: Row, actor: { reason: string; reviewer: string }): PricePlan | { changed: true; edits: PriceEdit[]; append: true } {
  const s = record.effective_from || record.observed_at;
  let sameDay: Row | null = null;
  if (s) {
    try {
      const priceType = parsePriceType(record.price_type || "LIST_PRICE");
      const current = currentPriceForScope(rows, record.trim_id, priceType, String(s),
        record.campaign_id ? String(record.campaign_id) : null, record.option_id ? String(record.option_id) : null);
      sameDay = current && start(current) === String(s) ? current : null;
    } catch {
      sameDay = null;
    }
  }
  if (sameDay) {
    if (Number(sameDay.amount_thb) === Number(record.amount_thb)) return { changed: false };
    return planCorrectPrice(rows, {
      trimId: record.trim_id, priceType: parsePriceType(record.price_type || "LIST_PRICE"),
      amountThb: Number(record.amount_thb), reason: actor.reason || `replaces the price saved earlier on ${s}`,
      reviewer: actor.reviewer || "owner", mode: "retract", effectiveFrom: String(s),
      campaignId: record.campaign_id ? String(record.campaign_id) : null,
      optionId: record.option_id ? String(record.option_id) : null,
      source: str(record.source), sourceRef: str(record.source_ref), sourceDocumentId: str(record.source_document_id),
      referencePriceThb: record.reference_price_thb === null || record.reference_price_thb === undefined || record.reference_price_thb === ""
        ? null : Number(record.reference_price_thb),
      asOf: String(s),
    });
  }
  return { changed: true, edits: [{ kind: "append", row: record }], append: true };
}
