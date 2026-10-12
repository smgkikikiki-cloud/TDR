/**
 * The two AI skills of the price pipeline: lineup/price extraction and the change auditor.
 *
 * Rules (VEHICLE_DB_V3 §9 and the owner's 2026-10-12 amendments, §9.1):
 *  - Haiku only (`agent_model`, default claude-haiku-4-5-20251001), through an Anthropic API key held in the CI secret.
 *  - Spend is capped per month by `vm_settings.agent_monthly_cap_usd`. **0 means no call is ever made.** The daily cap
 *    is the remaining monthly cap spread over the days left in the billing cycle. Any credit / rate-limit / auth error
 *    halts every further call in the run.
 *  - The AI never decides what is true. Extraction is accepted only with a quote that is literally on the page
 *    (`validateEvidence`); the auditor can only veto a change, never create one.
 */
import { validateEvidence, MIN_LIST_PRICE_THB, type ExtractedPrice, type KnownTrim, type PageText } from "./extract.ts";

export type AiSettings = {
  monthly_cap_usd: number;
  cycle_start_day: number;     // 1..28
  model: string;
  rate_usd_per_mtok: { input: number; output: number };
};

export const DEFAULT_AI_SETTINGS: AiSettings = {
  monthly_cap_usd: 0, cycle_start_day: 1, model: "claude-haiku-4-5-20251001", rate_usd_per_mtok: { input: 1.0, output: 5.0 },
};

export type UsageRecord = { at: string; cost_usd: number };

/** Start of the billing cycle that contains `now` (UTC dates; the owner enters the cycle day from the billing page). */
export function cycleStart(now: Date, startDay: number): Date {
  const day = Math.min(Math.max(1, Math.floor(startDay)), 28);
  const y = now.getUTCFullYear();
  const m = now.getUTCMonth();
  const thisCycle = new Date(Date.UTC(y, m, day));
  return now >= thisCycle ? thisCycle : new Date(Date.UTC(y, m - 1, day));
}

export function daysLeftInCycle(now: Date, startDay: number): number {
  const start = cycleStart(now, startDay);
  const next = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + 1, Math.min(Math.max(1, Math.floor(startDay)), 28)));
  const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  return Math.max(1, Math.round((next.getTime() - today) / 86_400_000));
}

export class Budget {
  halted: string | null = null;
  private spentThisRun = 0;
  private settings: AiSettings;
  private usage: UsageRecord[];
  private now: Date;
  constructor(settings: AiSettings, usage: UsageRecord[], now: Date) {
    this.settings = settings;
    this.usage = usage;
    this.now = now;
  }

  private spentSince(since: Date): number {
    return this.usage.filter((u) => new Date(u.at) >= since).reduce((a, u) => a + u.cost_usd, 0) + this.spentThisRun;
  }

  /** Remaining dollars that may be spent today; 0 when the cap is 0 or the run was halted. */
  allowanceToday(): number {
    if (this.halted || !(this.settings.monthly_cap_usd > 0)) return 0;
    const cycle = cycleStart(this.now, this.settings.cycle_start_day);
    const remainingMonth = this.settings.monthly_cap_usd - this.spentSince(cycle);
    if (remainingMonth <= 0) return 0;
    const daily = (this.settings.monthly_cap_usd - this.spentSince(cycle) + this.spentSince(startOfDay(this.now))) / daysLeftInCycle(this.now, this.settings.cycle_start_day);
    return Math.max(0, Math.min(remainingMonth, daily - this.spentSince(startOfDay(this.now))));
  }

  estimate(inputChars: number, maxOutputTokens: number): number {
    const inputTokens = Math.ceil(inputChars / 2.2); // Thai is token-hungry: be pessimistic
    return (inputTokens * this.settings.rate_usd_per_mtok.input + maxOutputTokens * this.settings.rate_usd_per_mtok.output) / 1e6;
  }

  canAfford(inputChars: number, maxOutputTokens: number): boolean {
    return this.estimate(inputChars, maxOutputTokens) <= this.allowanceToday();
  }

  record(inputTokens: number, outputTokens: number): number {
    const cost = (inputTokens * this.settings.rate_usd_per_mtok.input + outputTokens * this.settings.rate_usd_per_mtok.output) / 1e6;
    this.spentThisRun += cost;
    return cost;
  }

  halt(reason: string) { this.halted = reason; }
  get spent() { return this.spentThisRun; }
}

const startOfDay = (d: Date) => new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));

export type Messages = (body: unknown) => Promise<{ status: number; json: any }>;

/** The Anthropic Messages API over fetch. `apiKey` must come from the CI secret, never from the repo. */
export function anthropicMessages(apiKey: string, fetchImpl: typeof fetch = fetch): Messages {
  return async (body) => {
    const response = await fetchImpl("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: { "content-type": "application/json", "x-api-key": apiKey, "anthropic-version": "2023-06-01" },
      body: JSON.stringify(body),
    });
    let json: any = null;
    try { json = await response.json(); } catch { /* non-JSON error page */ }
    return { status: response.status, json };
  };
}

export type AiCall = { text: string; input_tokens: number; output_tokens: number };

async function call(budget: Budget, messages: Messages, settings: AiSettings, system: string, user: string, maxTokens: number,
  onUsage: (skill: string, model: string, input: number, output: number, cost: number) => void, skill: string): Promise<AiCall | null> {
  if (budget.halted) return null;
  if (!budget.canAfford(system.length + user.length, maxTokens)) return null;
  const { status, json } = await messages({
    model: settings.model, max_tokens: maxTokens, temperature: 0, system, messages: [{ role: "user", content: user }],
  });
  if (status === 200 && json?.content) {
    const text = (json.content as any[]).filter((b) => b.type === "text").map((b) => b.text).join("");
    const input = Number(json.usage?.input_tokens ?? 0);
    const output = Number(json.usage?.output_tokens ?? 0);
    onUsage(skill, settings.model, input, output, budget.record(input, output));
    return { text, input_tokens: input, output_tokens: output };
  }
  // 400 (credit balance too low is a 400 invalid_request_error), 401, 402, 403, 429, 529: stop for the whole run.
  if ([400, 401, 402, 403, 429, 529].includes(status)) {
    budget.halt(`Anthropic API ${status}: ${String(json?.error?.message ?? "").slice(0, 160)}`);
    return null;
  }
  return null; // 5xx: this call fails, the next may succeed; the caller treats null as "no AI answer"
}

function firstJson(text: string): any | null {
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  if (start < 0 || end <= start) return null;
  try { return JSON.parse(text.slice(start, end + 1)); } catch { return null; }
}

export const MAX_PAGE_CHARS = 24_000;

/** Narrow the page to the part that mentions prices when it is too long for one cheap call. */
export function clipPage(text: string, maxChars = MAX_PAGE_CHARS): string {
  if (text.length <= maxChars) return text;
  const firstPrice = text.search(/\d{1,3}(?:,\d{3})+/);
  const from = Math.max(0, (firstPrice < 0 ? 0 : firstPrice) - 2_000);
  return text.slice(from, from + maxChars);
}

const EXTRACT_SYSTEM = `You read the visible text of a Thai car-maker's model page and list the price of each grade (trim).
Return JSON only: {"rows":[{"name":"<grade name exactly as written on the page>","amount_thb":<integer>,"vat_included":<true|false|null>,"quote":"<the shortest exact text from the page that contains both the grade name and the price>"}]}
Rules: list price of the grade only (the "starting price" / "ราคา" of that grade). Skip monthly instalments, down payments, discounts, accessories, financing, "from" prices that belong to the whole model rather than a grade, and prices of other models. If the page shows no per-grade list prices return {"rows":[]}. Never guess a number that is not written on the page.`;

export type AiExtraction = { rows: ExtractedPrice[]; rejected: { name: string; reason: string }[]; called: boolean };

export async function extractWithAi(
  page: PageText, known: KnownTrim[], ctx: { budget: Budget; messages: Messages; settings: AiSettings; model_name: string;
    onUsage: Parameters<typeof call>[6] },
): Promise<AiExtraction> {
  const user = `Model: ${ctx.model_name}\nGrades already known for this model (names may differ on the page): ${known.map((k) => k.name).join(" | ") || "none"}\n\nPAGE TEXT:\n${clipPage(page.text)}`;
  const answer = await call(ctx.budget, ctx.messages, ctx.settings, EXTRACT_SYSTEM, user, 1_500, ctx.onUsage, "price-extract");
  if (!answer) return { rows: [], rejected: [], called: false };
  const parsed = firstJson(answer.text);
  const rows: ExtractedPrice[] = [];
  const rejected: AiExtraction["rejected"] = [];
  for (const raw of Array.isArray(parsed?.rows) ? parsed.rows : []) {
    const name = String(raw?.name ?? "").trim();
    const amount = Number(raw?.amount_thb);
    const quote = String(raw?.quote ?? "");
    if (!name || !Number.isInteger(amount)) { rejected.push({ name, reason: "malformed row" }); continue; }
    if (!validateEvidence(page, { name_raw: name, amount_thb: amount, quote })) { rejected.push({ name, reason: "quote is not literal page text containing the name and the price" }); continue; }
    const vat = raw?.vat_included === true ? true : raw?.vat_included === false ? false : null;
    rows.push({ name_raw: name, amount_thb: amount, vat_included: vat, evidence: quote, method: "AI" });
  }
  return { rows, rejected, called: true };
}

const AUDIT_SYSTEM = `You audit one proposed car list-price change against the quoted page text.
Return JSON only: {"verdict":"CORRECT"|"WRONG"|"UNSURE","reason":"<one short sentence>"}
CORRECT only if the quoted text clearly states that this grade's list price is the new amount (not an instalment, discount, promotion price, price of a different grade, or a different model). WRONG if the text contradicts it. UNSURE otherwise.`;

export type AuditVerdict = { verdict: "CORRECT" | "WRONG" | "UNSURE" | "SKIPPED"; reason: string };

export async function auditChange(
  change: { trim_name: string; old_amount_thb: number | null; new_amount_thb: number; evidence: string },
  ctx: { budget: Budget; messages: Messages; settings: AiSettings; onUsage: Parameters<typeof call>[6] },
): Promise<AuditVerdict> {
  const user = `Grade: ${change.trim_name}\nOld list price: ${change.old_amount_thb ?? "none"}\nNew list price proposed: ${change.new_amount_thb}\nQuoted page text:\n${change.evidence.slice(0, 1_200)}`;
  const answer = await call(ctx.budget, ctx.messages, ctx.settings, AUDIT_SYSTEM, user, 200, ctx.onUsage, "price-audit");
  if (!answer) return { verdict: "SKIPPED", reason: ctx.budget.halted ?? "no AI budget available" };
  const parsed = firstJson(answer.text);
  const verdict = parsed?.verdict;
  if (verdict === "CORRECT" || verdict === "WRONG" || verdict === "UNSURE") return { verdict, reason: String(parsed.reason ?? "").slice(0, 300) };
  return { verdict: "UNSURE", reason: "unparseable auditor answer" };
}

export { MIN_LIST_PRICE_THB };
