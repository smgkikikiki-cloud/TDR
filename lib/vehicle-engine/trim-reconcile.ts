/**
 * Trim-set and price reconcile (docs/vehicle-db/VEHICLE_DB_V3.md §5.1–§5.4, §6).
 *
 * A pure function: observations of one model's lineup + the master's current state -> a plan. It never reads or
 * writes the database and has no clock of its own; `today` is an input. The plan says which prices may be applied,
 * which wait for a second sighting, which need an admin (PRICE_JUMP), and which structural changes to *propose*.
 * Structure is only ever proposed, never applied (§4); a lower authority being refused is the writer's job.
 */

export const NORMALIZER_VERSION = "1";

export type TrimStatus = "CURRENT" | "UNVERIFIED" | "HISTORICAL";

export type TrimState = {
  trim_id: string;
  name: string;
  aliases?: string[];
  status: TrimStatus;
  /** Current list price, null when there is none yet. */
  price_thb: number | null;
  /** Set when an admin chose the name: the only structural proposal allowed is "add alias" (§5.3). */
  name_locked?: boolean;
  /** Latest time any source row was paired to this trim (from vm_observations), ISO date. */
  last_seen_at?: string | null;
};

export type Observation = {
  name_raw: string;
  /** null / 0 / "contact dealer" rows carry no price and never change one (§6.B). */
  amount_thb: number | null;
  vat_included?: boolean | null;
  /** Excel only: an explicit trim id (§5.1 step 2). */
  trim_id_hint?: string | null;
};

export type Policy = {
  jump_ratio: number;          // |Δ| above this needs a PRICE_JUMP card
  min_coverage: number;        // observations / CURRENT trims below this -> SOURCE_BROKEN for the model
  lineup_change_ratio: number; // changed share above this -> one card for the whole model
  discontinue_days: number;    // consecutive days missing before "discontinue" is even proposed
  pair_threshold: number;      // pairing score below this -> no pair
};

export const DEFAULT_POLICY: Policy = {
  jump_ratio: 0.15, min_coverage: 0.5, lineup_change_ratio: 0.5, discontinue_days: 7, pair_threshold: 0.5,
};

export type ReconcileInput = {
  model: { id: string; brand_name: string; model_name: string };
  trims: TrimState[];
  observations: Observation[];
  extraction_ok: boolean;
  /** Optional page headline (h1/title); facelift markers are looked for here and in the observation names. */
  headline?: string;
  /** trim_id -> the amount the previous completed run paired to it (for the "same value twice" rule). */
  prior_amounts: ReadonlyMap<string, number>;
  /** First time this model's source was successfully read; counts missing days for trims never seen. */
  model_first_observed_at?: string | null;
  /**
   * True only when every source read for this model is verified to list the WHOLE lineup (target `lineup_complete`).
   * A page that shows fewer trims than the maker sells (a model page vs the price list) must never make a trim
   * "missing": default false = discontinue is never proposed.
   */
  lineup_complete?: boolean;
  /** Dates (YYYY-MM-DD) on which this model was read successfully. A missing streak only counts across days that were really read. */
  read_dates?: string[];
  today: string; // YYYY-MM-DD
  policy?: Partial<Policy>;
};

export type Proposal =
  | { kind: "ADD_TRIM"; name_raw: string; amount_thb: number | null; vat_included: boolean | null }
  | { kind: "DISCONTINUE_TRIM"; trim_id: string; missing_days: number }
  | { kind: "ALIAS_TRIM"; trim_id: string; name_raw: string; score: number }
  | { kind: "RENAME_TRIM"; trim_id: string; name_raw: string; score: number }
  | { kind: "CONFIRM_CURRENT"; trim_id: string }
  | { kind: "REACTIVATE_TRIM"; trim_id: string }
  | { kind: "AMBIGUOUS_NAME"; name_raw: string; trim_ids: string[] }
  | { kind: "MODEL_REVIEW"; reason: "LINEUP_CHANGE" | "FACELIFT_MARKER"; detail: string };

export type ReconcileStatus = "OK" | "BATCH_STOPPED" | "SOURCE_BROKEN" | "MODEL_REVIEW";

export type ReconcileOutput = {
  status: ReconcileStatus;
  reason: string;
  matches: { obs_index: number; trim_id: string; how: "HINT" | "NAME" | "ALIAS" }[];
  price_applies: { trim_id: string; amount_thb: number; prior_amount: number | null; vat_included: boolean | null }[];
  /** Differs from the live price but not yet seen twice: store the observation, change nothing. */
  price_pending: { trim_id: string; amount_thb: number }[];
  price_jumps: { trim_id: string; amount_thb: number; prior_amount: number; ratio: number }[];
  proposals: Proposal[];
};

// ---------------------------------------------------------------------------
// §5.2 Normalize
// ---------------------------------------------------------------------------

// Order matters: longer phrases first.
const SYNONYMS: [RegExp, string][] = [
  [/ปลั๊กอินไฮบริด|ปลั๊กอิน|plug-?in hybrid|\bphev\b/g, " phev "],
  [/\be:?hev\b|ไฮบริด|\bhybrid\b|\bhev\b/g, " hev "],
  [/\bbev\b|ไฟฟ้า|\belectric\b|\bpure ev\b/g, " bev "],
  [/ขับเคลื่อนสี่ล้อ|ขับสี่ล้อ|\b4x4\b|\b4wd\b|\bawd\b|\bfour[ -]?wheel\b/g, " awd "],
  [/ขับเคลื่อนล้อหน้า|\bfwd\b|\b2wd\b|\b4x2\b/g, " 2wd "],
  [/ที่นั่ง|\bseater\b|\bseats?\b/g, " seat "],
];

function stripYear(text: string): string {
  return text
    .replace(/\bmy\s?-?(20)?[12]\d\b/g, " ")                  // my24, my2026, my 26
    .replace(/(?:ปี|model year|year)\s*(20)?[12]\d\b/g, " ")  // ปี 2026
    .replace(/(?<![\d.])20[1-3]\d(?![\d.])/g, " ");            // a bare 4-digit year, never a decimal like 2.0
}

/** lowercase -> strip leading brand/model -> strip model year -> synonyms -> drop spaces/dashes (keep decimals). */
export function normalizeTrimName(raw: string, brand = "", model = ""): string {
  return tokensOf(raw, brand, model).join("");
}

export function tokensOf(raw: string, brand = "", model = ""): string[] {
  let text = ` ${String(raw ?? "").toLowerCase().normalize("NFKC")} `;
  for (const lead of [brand, model]) {
    const l = lead.toLowerCase().trim();
    if (!l) continue;
    const trimmed = text.trimStart();
    if (trimmed.startsWith(l + " ") || trimmed === l) text = ` ${trimmed.slice(l.length)} `;
  }
  text = stripYear(text);
  for (const [pattern, replacement] of SYNONYMS) text = text.replace(pattern, replacement);
  // "7 seat" / "7seat" -> "7seat"
  text = text.replace(/(\d)\s+seat\b/g, "$1seat");
  return (text.match(/\d+(?:\.\d+)?[a-z]*|[a-z]+|[฀-๿]+|[+]/g) ?? []).filter((t) => t.length > 0);
}

// ---------------------------------------------------------------------------
// §5.3 Pairing
// ---------------------------------------------------------------------------

const POWERTRAIN_TOKENS = new Set(["hev", "phev", "bev", "awd", "2wd"]);
const isHeavy = (t: string) => /^\d/.test(t) || POWERTRAIN_TOKENS.has(t) || t === "+";

function weightedJaccard(a: string[], b: string[]): number {
  const sa = new Set(a);
  const sb = new Set(b);
  const weight = (t: string) => (isHeavy(t) ? 2 : 1);
  let inter = 0;
  let union = 0;
  for (const t of new Set([...sa, ...sb])) {
    union += weight(t);
    if (sa.has(t) && sb.has(t)) inter += weight(t);
  }
  return union === 0 ? 0 : inter / union;
}

type Parsed = { powertrain: string | null; displacement: string | null; drivetrain: string | null; seats: string | null };

export function parseAttributes(tokens: string[]): Parsed {
  const set = new Set(tokens);
  const powertrain = set.has("phev") ? "PHEV" : set.has("bev") ? "BEV" : set.has("hev") ? "HEV" : null;
  const displacement = tokens.find((t) => /^\d\.\d$/.test(t)) ?? null;
  const drivetrain = set.has("awd") ? "AWD" : set.has("2wd") ? "2WD" : null;
  const seats = tokens.map((t) => /^(\d)seat$/.exec(t)?.[1]).find(Boolean) ?? null;
  return { powertrain, displacement, drivetrain, seats };
}

/** Hard rejects apply only when the attribute is parsed on BOTH sides (§5.3). */
function hardReject(a: Parsed, b: Parsed): boolean {
  return (a.powertrain && b.powertrain && a.powertrain !== b.powertrain)
    || (a.displacement && b.displacement && a.displacement !== b.displacement)
    || (a.drivetrain && b.drivetrain && a.drivetrain !== b.drivetrain)
    || false;
}

export type PairCandidate = { tokens: string[]; price: number | null; slot: number };

/** score = 0.40·tokens + 0.30·price + 0.30·slot, minus 0.3 for a different seat count; null = hard reject. */
export function pairScore(a: PairCandidate, b: PairCandidate): number | null {
  const pa = parseAttributes(a.tokens);
  const pb = parseAttributes(b.tokens);
  if (hardReject(pa, pb)) return null;
  const tokens = weightedJaccard(a.tokens, b.tokens);
  let price = 0;
  if (a.price && b.price) price = Math.max(0, 1 - (Math.abs(a.price - b.price) / b.price) * 100 / 10);
  const gap = Math.abs(a.slot - b.slot);
  const slot = gap === 0 ? 1 : gap === 1 ? 0.5 : 0;
  let score = 0.4 * tokens + 0.3 * price + 0.3 * slot;
  if (pa.seats && pb.seats && pa.seats !== pb.seats) score -= 0.3;
  return Math.round(score * 1e6) / 1e6;
}

/** Greedy 1:1, highest score first; ties broken by input order so the result is deterministic. */
export function greedyPairs(lefts: PairCandidate[], rights: PairCandidate[], threshold: number):
  { left: number; right: number; score: number }[] {
  const scored: { left: number; right: number; score: number }[] = [];
  lefts.forEach((l, i) => rights.forEach((r, j) => {
    const s = pairScore(l, r);
    if (s !== null && s >= threshold) scored.push({ left: i, right: j, score: s });
  }));
  scored.sort((x, y) => y.score - x.score || x.left - y.left || x.right - y.right);
  const usedL = new Set<number>();
  const usedR = new Set<number>();
  const out: typeof scored = [];
  for (const p of scored) {
    if (usedL.has(p.left) || usedR.has(p.right)) continue;
    usedL.add(p.left);
    usedR.add(p.right);
    out.push(p);
  }
  return out;
}

// ---------------------------------------------------------------------------
// §5.1 Trim-set reconcile + §5.4 prices
// ---------------------------------------------------------------------------

const FACELIFT_MARKERS = ["facelift", "ไมเนอร์เชนจ์", "โฉมใหม่", "ใหม่", "new"];
const daysBetween = (from: string, to: string) =>
  Math.floor((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 86_400_000);

/** Verified missing days: since `since` the model was read at least every 2 days (today's read counts), so a broken fetcher cannot age a trim into "missing". */
function readEveryFewDays(since: string, today: string, readDates: string[]): boolean {
  const dates = [...new Set([...readDates, today])].filter((d) => d > since).sort();
  let previous = since;
  for (const d of dates) {
    if (daysBetween(previous, d) > 2) return false;
    previous = d;
  }
  return true;
}

export function reconcileModel(input: ReconcileInput): ReconcileOutput {
  const policy: Policy = { ...DEFAULT_POLICY, ...(input.policy ?? {}) };
  const { brand_name: brand, model_name: modelName } = input.model;
  const out: ReconcileOutput = {
    status: "OK", reason: "", matches: [], price_applies: [], price_pending: [], price_jumps: [], proposals: [],
  };

  // 1. Batch gate: extraction failed or 0 rows -> stop, and above all never infer "discontinued" from nothing.
  if (!input.extraction_ok || input.observations.length === 0) {
    return { ...out, status: "BATCH_STOPPED", reason: input.extraction_ok ? "0 rows extracted" : "extraction failed" };
  }

  const trims = input.trims;
  const current = trims.filter((t) => t.status === "CURRENT");
  const byId = new Map(trims.map((t) => [t.trim_id, t]));

  // 2 + 3. Match by trim_id hint, then by normalized name / alias within this model.
  const nameIndex = new Map<string, { trim: TrimState; how: "NAME" | "ALIAS" }[]>();
  for (const t of trims) {
    const keys: [string, "NAME" | "ALIAS"][] = [[normalizeTrimName(t.name, brand, modelName), "NAME"],
      ...(t.aliases ?? []).map((a) => [normalizeTrimName(a, brand, modelName), "ALIAS"] as [string, "ALIAS"])];
    for (const [key, how] of keys) {
      if (!key) continue;
      const list = nameIndex.get(key) ?? [];
      if (!list.some((e) => e.trim.trim_id === t.trim_id)) list.push({ trim: t, how });
      nameIndex.set(key, list);
    }
  }
  const obsKeys = input.observations.map((o) => normalizeTrimName(o.name_raw, brand, modelName));
  const keyCount = new Map<string, number>();
  obsKeys.forEach((k) => keyCount.set(k, (keyCount.get(k) ?? 0) + 1));

  const matchedTrims = new Set<string>();
  const matchedObs = new Set<number>();
  input.observations.forEach((o, i) => {
    const hint = o.trim_id_hint ? byId.get(o.trim_id_hint) : undefined;
    if (hint && !matchedTrims.has(hint.trim_id)) {
      out.matches.push({ obs_index: i, trim_id: hint.trim_id, how: "HINT" });
      matchedTrims.add(hint.trim_id);
      matchedObs.add(i);
      return;
    }
    const key = obsKeys[i];
    if (!key) return;
    const hits = nameIndex.get(key) ?? [];
    if (hits.length === 1 && (keyCount.get(key) ?? 0) === 1 && !matchedTrims.has(hits[0].trim.trim_id)) {
      out.matches.push({ obs_index: i, trim_id: hits[0].trim.trim_id, how: hits[0].how });
      matchedTrims.add(hits[0].trim.trim_id);
      matchedObs.add(i);
    } else if (hits.length > 1 || (keyCount.get(key) ?? 0) > 1) {
      // Same normalized name twice (on the page or in the master): never guess which is which (§6.A).
      const ids = hits.map((h) => h.trim.trim_id);
      if (!out.proposals.some((p) => p.kind === "AMBIGUOUS_NAME" && p.name_raw === o.name_raw)) {
        out.proposals.push({ kind: "AMBIGUOUS_NAME", name_raw: o.name_raw, trim_ids: ids });
      }
      matchedObs.add(i); // consumed: it is neither "new" nor evidence for "missing"
      ids.forEach((id) => matchedTrims.add(id));
    }
  });

  // 4. Model gate: far fewer rows than CURRENT trims means the extraction is broken, not that the lineup shrank.
  if (current.length > 0 && input.observations.length < policy.min_coverage * current.length) {
    return { ...out, status: "SOURCE_BROKEN", matches: [], proposals: [],
      reason: `${input.observations.length} rows for ${current.length} CURRENT trims (< ${policy.min_coverage * 100}%)` };
  }

  // 5. Topology.
  const newObs = input.observations.map((o, i) => ({ o, i })).filter(({ i }) => !matchedObs.has(i));
  const missing = current.filter((t) => !matchedTrims.has(t.trim_id));
  // Share of the lineup that changed: the larger of "new" and "missing" over the larger lineup. A rename is one
  // changed trim (one missing + one new), not two.
  const denominator = Math.max(current.length, input.observations.length);
  const changedShare = denominator === 0 ? 0 : Math.max(newObs.length, missing.length) / denominator;

  const hasMarker = (text: string, marker: string) => {
    const t = text.toLowerCase();
    return /[\u0E00-\u0E7F]/.test(marker) ? t.includes(marker) : t.split(/[^a-z0-9]+/).includes(marker);
  };
  const markerHit = FACELIFT_MARKERS.find((m) =>
    (input.headline ? hasMarker(input.headline, m) : false) || newObs.some(({ o }) => hasMarker(o.name_raw, m)));

  // 6. Big lineup change or a facelift marker -> ONE card for the model; no pairing, no price changes (unsure = nothing).
  if (changedShare > policy.lineup_change_ratio) {
    out.status = "MODEL_REVIEW";
    out.reason = `${newObs.length} new + ${missing.length} missing of ${denominator}`;
    out.proposals.push({ kind: "MODEL_REVIEW", reason: "LINEUP_CHANGE", detail: out.reason });
    return out;
  }
  if (markerHit) {
    out.status = "MODEL_REVIEW";
    out.reason = `facelift/new-generation marker "${markerHit}" on an unmatched row or the headline`;
    out.proposals.push({ kind: "MODEL_REVIEW", reason: "FACELIFT_MARKER", detail: out.reason });
    return out;
  }

  // 7. Pair missing x new into rename / alias proposals.
  // Anchors are the matched pairs, ordered by price; the "slot" of an item is how many anchors sit below it.
  const anchorPrices = out.matches
    .map((m) => ({ price: current.find((t) => t.trim_id === m.trim_id)?.price_thb ?? input.observations[m.obs_index].amount_thb ?? 0 }))
    .map((a) => a.price)
    .filter((p) => p > 0)
    .sort((a, b) => a - b);
  const slotOf = (price: number | null) => (price ? anchorPrices.filter((p) => p < price).length : 0);
  const missingCand: PairCandidate[] = missing.map((t) => ({
    tokens: tokensOf(t.name, brand, modelName), price: t.price_thb, slot: slotOf(t.price_thb) }));
  const newCand: PairCandidate[] = newObs.map(({ o }) => ({
    tokens: tokensOf(o.name_raw, brand, modelName), price: o.amount_thb ?? null, slot: slotOf(o.amount_thb ?? null) }));
  const pairs = greedyPairs(missingCand, newCand, policy.pair_threshold);
  const pairedMissing = new Set<number>();
  const pairedNew = new Set<number>();
  for (const p of pairs) {
    const trim = missing[p.left];
    const obs = newObs[p.right].o;
    pairedMissing.add(p.left);
    pairedNew.add(p.right);
    out.proposals.push({ kind: trim.name_locked ? "ALIAS_TRIM" : "RENAME_TRIM", trim_id: trim.trim_id,
      name_raw: obs.name_raw, score: p.score });
  }

  // 8. The rest: new -> propose add; missing -> propose discontinue only after N consecutive days.
  newObs.forEach(({ o }, j) => {
    if (pairedNew.has(j)) return;
    out.proposals.push({ kind: "ADD_TRIM", name_raw: o.name_raw,
      amount_thb: o.amount_thb && o.amount_thb > 0 ? o.amount_thb : null, vat_included: o.vat_included ?? null });
  });
  missing.forEach((t, j) => {
    if (pairedMissing.has(j)) return;
    const since = t.last_seen_at ?? input.model_first_observed_at ?? null;
    if (!since) return;
    if (!input.lineup_complete) return;
    const days = daysBetween(since, input.today);
    if (days >= policy.discontinue_days && readEveryFewDays(since, input.today, input.read_dates ?? [])) out.proposals.push({ kind: "DISCONTINUE_TRIM", trim_id: t.trim_id, missing_days: days });
  });

  // Matched but not CURRENT: found on the official page -> confirm / reactivate (both need an admin). No price change.
  for (const m of out.matches) {
    const trim = byId.get(m.trim_id)!;
    if (trim.status === "UNVERIFIED") out.proposals.push({ kind: "CONFIRM_CURRENT", trim_id: trim.trim_id });
    if (trim.status === "HISTORICAL") out.proposals.push({ kind: "REACTIVATE_TRIM", trim_id: trim.trim_id });
  }

  // 5.4 Prices, only for matched CURRENT trims.
  for (const m of out.matches) {
    const trim = byId.get(m.trim_id)!;
    const obs = input.observations[m.obs_index];
    if (trim.status !== "CURRENT") continue;
    const amount = obs.amount_thb;
    if (!amount || amount <= 0) continue;                         // "contact dealer", 0, blank: no change
    if (trim.price_thb === amount) continue;                      // nothing to do
    const seenBefore = input.prior_amounts.get(trim.trim_id) === amount;
    if (!seenBefore) {
      out.price_pending.push({ trim_id: trim.trim_id, amount_thb: amount });
      continue;
    }
    if (trim.price_thb === null) {
      out.price_applies.push({ trim_id: trim.trim_id, amount_thb: amount, prior_amount: null, vat_included: obs.vat_included ?? null });
      continue;
    }
    const ratio = Math.abs(amount - trim.price_thb) / trim.price_thb;
    if (ratio <= policy.jump_ratio) {
      out.price_applies.push({ trim_id: trim.trim_id, amount_thb: amount, prior_amount: trim.price_thb, vat_included: obs.vat_included ?? null });
    } else {
      out.price_jumps.push({ trim_id: trim.trim_id, amount_thb: amount, prior_amount: trim.price_thb, ratio });
    }
  }
  return out;
}
