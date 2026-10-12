/**
 * Turns a reconcile plan into `vm_apply_price_changes` items (supabase/migration_v66).
 *
 * Pure. The served values the database stores (current_list_price, price_history, campaign_quote, the model price
 * band) are computed here with the ported engine rules (./pricing.ts, ./served.ts, ./lifecycle.ts) and handed to the
 * RPC, which enforces authority, revisions and the jump guard but never derives them (ENGINE_RULES §4).
 */
import { currentListPrice, campaignQuote, planAppendPrice, recordsFor, dayBefore } from "./pricing.ts";
import { priceRecord } from "./served.ts";
import { priceEligibleTrims, retailPriceBand, type LifecycleInputs } from "./lifecycle.ts";

type Row = Record<string, any>;

export type ModelSnapshot = {
  model: Row;                       // vehicle_models row (canonical_id, revision, retail_price_min/max, payload)
  generations: Row[];               // payload shape: id, model_id, code, segment, seats, launched, ended
  trims: Row[];                     // vehicle_trims rows of this model (canonical_id, generation_id, revision, catalog_payload, ...)
  prices: Row[];                    // vehicle_price_ledger rows of this model's trims: payload + record_id, retracted included
  campaigns: Map<string, Row>;
  lifecycle: LifecycleInputs;
};

export type ActorKind = "ADMIN" | "OFFICIAL" | "AI" | "EXCEL";

export type WriteContext = {
  asOf: string;                     // YYYY-MM-DD, the observation day
  actor_kind: ActorKind;
  source: string;                   // e.g. "official_toyota_th"
  source_ref: string;               // the page the price was read from
  reviewer: string;                 // recorded as the reviewer of the replaced row, if any
  reason: string;
};

export type PriceApply = {
  trim_id: string;
  amount_thb: number;
  vat_included?: boolean | null;
  /** Set when an admin approved a PRICE_JUMP card for exactly this change. */
  approved_inbox_id?: string | null;
  observation_id?: string | null;
};

export type RpcItem = {
  trim_id: string;
  expected_trim_revision: number;
  actor_kind: ActorKind;
  new_row: Row | null;
  retract_record_ids?: string[];
  close_record_ids?: string[];
  close_effective_to?: string;
  reopen_record_ids?: string[];
  retraction_reason?: string;
  served: { current_list_price: Row | null; price_history: Row[]; campaign_quote: Row };
  model: { model_id: string; expected_model_revision: number; retail_price_min: number | null; retail_price_max: number | null } | null;
  approved_inbox_id?: string | null;
  observation_id?: string | null;
  reverts_id?: string | null;
  reason: string;
};

export type Skipped = { trim_id: string; why: "NO_CHANGE" | "UNKNOWN_TRIM" | "FUTURE_PRICE_EXISTS" | "PLAN_ERROR"; detail?: string };

const start = (r: Row) => r.effective_from || r.observed_at || "";

/**
 * One RpcItem per applied price, in order. The model band rides on the last item so the model row is written once.
 * Each trim must appear at most once per call.
 */
export function planPriceWrites(snapshot: ModelSnapshot, applies: PriceApply[], ctx: WriteContext):
  { items: RpcItem[]; skipped: Skipped[] } {
  const items: RpcItem[] = [];
  const skipped: Skipped[] = [];
  const trimById = new Map(snapshot.trims.map((t) => [t.canonical_id, t]));
  let rows: Row[] = snapshot.prices.map((r) => ({ ...r }));
  const seen = new Set<string>();

  for (const apply of applies) {
    const trim = trimById.get(apply.trim_id);
    if (!trim || seen.has(apply.trim_id)) {
      skipped.push({ trim_id: apply.trim_id, why: "UNKNOWN_TRIM", detail: trim ? "listed twice" : undefined });
      continue;
    }
    seen.add(apply.trim_id);

    const record: Row = {
      trim_id: apply.trim_id, amount_thb: apply.amount_thb, price_type: "LIST_PRICE",
      effective_from: ctx.asOf, observed_at: ctx.asOf, source: ctx.source, source_ref: ctx.source_ref,
    };
    // A price already scheduled to start later than today would never become current: leave it to a human.
    const later = recordsFor(rows, apply.trim_id, { priceType: "LIST_PRICE" }).find((r) => start(r) > ctx.asOf);
    if (later) { skipped.push({ trim_id: apply.trim_id, why: "FUTURE_PRICE_EXISTS", detail: start(later) }); continue; }

    let plan;
    try {
      plan = planAppendPrice(rows, record, { reason: ctx.reason, reviewer: ctx.reviewer });
    } catch (error) {
      skipped.push({ trim_id: apply.trim_id, why: "PLAN_ERROR", detail: String((error as Error).message) });
      continue;
    }
    if (!plan.changed) { skipped.push({ trim_id: apply.trim_id, why: "NO_CHANGE" }); continue; }

    const retract: string[] = [];
    const nextRows = rows.map((r) => ({ ...r }));
    let appended: Row | null = null;
    for (const edit of plan.edits) {
      if (edit.kind === "update") {
        const target = nextRows[edit.recordIndex];
        Object.assign(target, edit.changes);
        if (edit.changes.retracted_at) retract.push(String(target.record_id));
      } else {
        appended = { ...edit.row, record_id: `pending-${apply.trim_id}`, amount_thb: Number(edit.row.amount_thb) };
        nextRows.push(appended);
      }
    }
    if (!appended) { skipped.push({ trim_id: apply.trim_id, why: "NO_CHANGE" }); continue; }
    rows = nextRows;

    const current = currentListPrice(rows, apply.trim_id, ctx.asOf);
    items.push({
      trim_id: apply.trim_id,
      expected_trim_revision: Number(trim.revision),
      actor_kind: ctx.actor_kind,
      new_row: {
        amount_thb: apply.amount_thb, price_type: "LIST_PRICE", effective_from: ctx.asOf, observed_at: ctx.asOf,
        source: ctx.source, source_ref: ctx.source_ref, vat_included: apply.vat_included ?? null,
        notes: appended.notes ?? "",
      },
      retract_record_ids: retract.length ? retract : undefined,
      retraction_reason: retract.length ? (appended.notes || ctx.reason) : undefined,
      served: {
        current_list_price: current ? priceRecord(current) : null,
        price_history: recordsFor(rows, apply.trim_id).map(priceRecord),
        campaign_quote: campaignQuote(rows, snapshot.campaigns, apply.trim_id, ctx.asOf),
      },
      model: null,
      approved_inbox_id: apply.approved_inbox_id ?? null,
      observation_id: apply.observation_id ?? null,
      reason: ctx.reason,
    });
  }

  if (items.length) {
    const catalogTrims = snapshot.trims.filter((t) => t.catalog_payload);
    const eligible = priceEligibleTrims(snapshot.model, snapshot.generations, catalogTrims, snapshot.lifecycle, ctx.asOf);
    const band = retailPriceBand(eligible, rows, ctx.asOf);
    const stored = (v: unknown) => (v === null || v === undefined ? null : Number(v));
    if (band.min !== stored(snapshot.model.retail_price_min) || band.max !== stored(snapshot.model.retail_price_max)) {
      items[items.length - 1].model = {
        model_id: snapshot.model.canonical_id, expected_model_revision: Number(snapshot.model.revision),
        retail_price_min: band.min, retail_price_max: band.max,
      };
    }
  }
  return { items, skipped };
}

/**
 * Reverting a logged change: retract the row it appended (and reopen the ones it closed). The log entry's
 * after_revision becomes the expected revision, so a trim changed since is reported as STALE, never forced.
 */
export function planRevert(snapshot: ModelSnapshot, log: {
  id: string; entity_id: string; after_revision: number;
  record_id: string | null; closed_record_ids: string[]; asOf: string; reason: string;
}): { item: RpcItem | null; why?: string } {
  const trim = snapshot.trims.find((t) => t.canonical_id === log.entity_id);
  if (!trim) return { item: null, why: "UNKNOWN_TRIM" };
  let rows: Row[] = snapshot.prices.map((r) => ({ ...r }));
  if (log.record_id) {
    const target = rows.find((r) => r.record_id === log.record_id);
    if (!target || target.retracted_at) return { item: null, why: "ALREADY_RETRACTED" };
    target.retracted_at = log.asOf;
  }
  for (const id of log.closed_record_ids) {
    const row = rows.find((r) => r.record_id === id);
    if (row) row.effective_to = null;
  }
  const current = currentListPrice(rows, log.entity_id, log.asOf);
  const eligible = priceEligibleTrims(snapshot.model, snapshot.generations, snapshot.trims.filter((t) => t.catalog_payload),
    snapshot.lifecycle, log.asOf);
  const band = retailPriceBand(eligible, rows, log.asOf);
  return {
    item: {
      trim_id: log.entity_id, expected_trim_revision: log.after_revision, actor_kind: "ADMIN", new_row: null,
      retract_record_ids: log.record_id ? [log.record_id] : undefined, retraction_reason: log.reason,
      reopen_record_ids: log.closed_record_ids.length ? log.closed_record_ids : undefined,
      served: {
        current_list_price: current ? priceRecord(current) : null,
        price_history: recordsFor(rows, log.entity_id).map(priceRecord),
        campaign_quote: campaignQuote(rows, snapshot.campaigns, log.entity_id, log.asOf),
      },
      model: { model_id: snapshot.model.canonical_id, expected_model_revision: Number(snapshot.model.revision),
        retail_price_min: band.min, retail_price_max: band.max },
      reverts_id: log.id, reason: log.reason,
    },
  };
}

export { dayBefore };
