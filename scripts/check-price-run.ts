/** lib/price-refresh/run.ts end to end with fake ports: fetch -> read -> reconcile -> audit -> planned writes. No network, no database. */
import { refreshModel, type AiPort, type Ports, type RunOptions } from "../lib/price-refresh/run.ts";
import { Budget, DEFAULT_AI_SETTINGS, type Messages } from "../lib/price-refresh/ai.ts";
import type { History } from "../lib/price-refresh/store.ts";

let failed = 0, passed = 0;
function ok(name: string, c: unknown, detail?: unknown) {
  if (c) passed++; else { failed++; console.log(`  FAIL ${name}${detail === undefined ? "" : "\n       " + JSON.stringify(detail).slice(0, 700)}`); }
}
const NOW = new Date("2026-10-12T10:00:00Z");
const TODAY = "2026-10-12";
const MODEL = "toyota.yaris_ativ";
const trimRow = (id: string, name: string) => ({ canonical_id: id, model_id: MODEL, generation_id: "g1", revision: 1, name, status: "CURRENT", catalog_payload: {}, payload: {} });
const price = (id: string, trim: string, amount: number) => ({ record_id: id, trim_id: trim, amount_thb: amount, price_type: "LIST_PRICE", effective_from: "2026-01-01", observed_at: "2026-01-01",
  source: "seed", source_ref: "", source_document_id: "", notes: "", campaign_id: null, option_id: null, reference_price_thb: null, effective_to: null, retracted_at: null, retraction_reason: "", reviewed_by: "" });
const prices = { smart: 589_000, sport: 569_000, premium: 679_000 };
function loaded() {
  const trims = [trimRow("t.smart", "Smart"), trimRow("t.sport", "Sport"), trimRow("t.premium", "Premium")];
  return {
    brand_name: "Toyota", model_name: "Yaris Ativ",
    trims: trims.map((t) => ({ trim_id: t.canonical_id, name: t.name, aliases: [], status: "CURRENT" as const, price_thb: (prices as any)[t.canonical_id.slice(2)], name_locked: false })),
    snapshot: {
      model: { canonical_id: MODEL, revision: 3, retail_price_min: 569_000, retail_price_max: 679_000, payload: {}, status: "CURRENT" },
      generations: [{ id: "g1", model_id: MODEL, launched: "2022-01-01", ended: null, code: "XP210" }],
      trims, campaigns: new Map(),
      prices: [price("r1", "t.smart", 589_000), price("r2", "t.sport", 569_000), price("r3", "t.premium", 679_000)],
      lifecycle: { approved: new Map(), decisions: new Map(), maintenance: new Set<string>() },
    },
  };
}
const pageText = (smart: number, sport = 569_000, premium = 679_000) =>
  `Yaris Ativ\nเลือกรุ่นที่ใช่ และรายละเอียดทั้งหมดของรถรุ่นนี้ในประเทศไทย\nPremium\nราคาเริ่มต้น ${premium.toLocaleString("en-US")} บาท\nSmart\nราคาเริ่มต้น ${smart.toLocaleString("en-US")} บาท\nSport\nราคาเริ่มต้น ${sport.toLocaleString("en-US")} บาท\nผ่อนเริ่มต้น 7,990 บาท/เดือน ` + "x".repeat(200);

function harness(opts: { text?: string; fetchFail?: boolean; prior?: Record<string, number>; jumps?: any[] } = {}) {
  const calls = { observations: [] as any[], inbox: [] as any[], applied: [] as any[], states: [] as any[], marked: [] as any[] };
  const ports: Ports = {
    fetch: async (url) => opts.fetchFail ? { ok: false, kind: "FAILED", error: "timeout" }
      : { ok: true, page: { url, text: opts.text ?? pageText(589_000), content_hash: "sha256:" + (opts.text ?? "base").length, fetched_at: NOW.toISOString() } },
    loadModel: async () => loaded() as any,
    loadHistory: async (): Promise<History> => ({ prior_amounts: new Map(Object.entries(opts.prior ?? {})), last_seen: new Map(), first_observed: "2026-09-01" }),
    loadApprovedJumps: async () => opts.jumps ?? [],
    markJumpApplied: async (c) => { calls.marked.push(c); },
    insertObservations: async (rows) => { calls.observations.push(...rows); },
    proposeInbox: async (p) => { calls.inbox.push(p); return { status: "CREATED" }; },
    applyPriceChanges: async (_b, items) => { calls.applied.push(...items); return items.map((i) => ({ trim_id: i.trim_id, status: "APPLIED" })); },
    saveSourceState: async (row) => { calls.states.push(row); },
  };
  return { ports, calls };
}
const options = (over: Partial<RunOptions> = {}): RunOptions => ({ run_id: "run-1", now: NOW, today: TODAY, apply: true, use_ai: true, require_audit: false, source_state: new Map(), ...over });
const job = { model_id: MODEL, targets: [{ id: "toyota_th_yaris_ativ", url: "https://www.toyota.co.th/model/yarisativ" }] };
const reply = (text: string): Messages => async () => ({ status: 200, json: { content: [{ type: "text", text }], usage: { input_tokens: 800, output_tokens: 40 } } });
const aiPort = (cap: number, messages: Messages): AiPort => {
  const settings = { ...DEFAULT_AI_SETTINGS, monthly_cap_usd: cap };
  return { budget: new Budget(settings, [], NOW), messages, settings, onUsage: () => {} };
};

(async () => {
  // 1. first sighting of a new price: recorded, pending, nothing written to the master
  {
    const h = harness({ text: pageText(599_000) });
    const r = await refreshModel(job, h.ports, null, options());
    ok("first sighting: pending, not applied", r.pending.length === 1 && r.applied.length === 0 && h.calls.applied.length === 0, r);
    ok("first sighting: observations stored with the paired trim", h.calls.observations.length === 3 && h.calls.observations.every((o) => o.trim_id && o.source_kind === "SCRAPE"), h.calls.observations);
    ok("source state saved as OK", h.calls.states.length === 1 && h.calls.states[0].status === "OK" && h.calls.states[0].fail_count === 0);
  }
  // 2. second sighting of the same value: applied through the writer with served values
  {
    const h = harness({ text: pageText(599_000), prior: { "t.smart": 599_000 } });
    const r = await refreshModel(job, h.ports, null, options());
    ok("second sighting: applied", r.applied.length === 1 && r.applied[0].to === 599_000 && r.applied[0].from === 589_000, r);
    const item = h.calls.applied[0];
    ok("writer item carries expected revision, new row and served current price",
      item?.trim_id === "t.smart" && item.expected_trim_revision === 1 && item.new_row.amount_thb === 599_000 && item.served.current_list_price?.amount_thb === 599_000, item);
    ok("writer item records the source and the reason", item?.new_row.source_ref.includes("toyota.co.th") && item.reason.includes("run-1"));
    ok("model price band is updated only if it changed (569k..679k unchanged here)", item?.model === null, item?.model);
  }
  // 3. jump over 15 %: card, no write
  {
    const h = harness({ text: pageText(799_000), prior: { "t.smart": 799_000 } });
    const r = await refreshModel(job, h.ports, null, options());
    ok("jump: not applied, listed", r.applied.length === 0 && r.jumps.length === 1, r);
    ok("jump: a PRICE_JUMP card is proposed", h.calls.inbox.some((c) => c.kind === "PRICE_JUMP" && c.trim_id === "t.smart" && c.payload.amount_thb === 799_000), h.calls.inbox);
  }
  // 3b. an approved jump card is applied once, with the card id
  {
    const card = { id: "card-1", payload: { trim_id: "t.smart", amount_thb: 799_000 } };
    const h = harness({ text: pageText(799_000), prior: { "t.smart": 799_000 }, jumps: [card] });
    const r = await refreshModel(job, h.ports, null, options());
    ok("approved jump: applied with the card id", r.applied.length === 1 && h.calls.applied[0]?.approved_inbox_id === "card-1", { r, a: h.calls.applied });
    ok("approved jump: card marked applied", h.calls.marked.length === 1);
  }
  // 4. a failed page stops the model
  {
    const h = harness({ fetchFail: true });
    const r = await refreshModel(job, h.ports, null, options());
    ok("fetch failure: batch stopped, no write, no observations", r.status === "BATCH_STOPPED" && h.calls.applied.length === 0 && h.calls.observations.length === 0, r);
    ok("fetch failure: source state counts the failure", h.calls.states[0]?.status === "FAILED" && h.calls.states[0].fail_count === 1, h.calls.states);
    const h2 = harness({ fetchFail: true });
    await refreshModel(job, h2.ports, null, options({ source_state: new Map([["toyota_th_yaris_ativ", { fail_count: 2 }]]) }));
    ok("third failure in a row marks the source BROKEN", h2.calls.states[0]?.status === "BROKEN", h2.calls.states);
  }
  // 5. dry run writes nothing
  {
    const h = harness({ text: pageText(599_000), prior: { "t.smart": 599_000 } });
    const r = await refreshModel(job, h.ports, null, options({ apply: false }));
    const wrote = h.calls.applied.length + h.calls.observations.length + h.calls.inbox.length + h.calls.states.length + h.calls.marked.length;
    ok("dry run: reports the change but writes nothing", r.applied.length === 1 && wrote === 0, { r, wrote });
  }
  // 6. auditor veto and budget
  {
    const h = harness({ text: pageText(599_000), prior: { "t.smart": 599_000 } });
    const r = await refreshModel(job, h.ports, aiPort(10, reply('{"verdict":"WRONG","reason":"instalment"}')), options());
    ok("auditor WRONG: change held, not written", r.applied.length === 0 && r.held.length === 1 && h.calls.applied.length === 0, r);
    const h2 = harness({ text: pageText(599_000), prior: { "t.smart": 599_000 } });
    const r2 = await refreshModel(job, h2.ports, aiPort(10, reply('{"verdict":"CORRECT","reason":"ok"}')), options());
    ok("auditor CORRECT: written", r2.applied.length === 1);
    const h3 = harness({ text: pageText(599_000), prior: { "t.smart": 599_000 } });
    const r3 = await refreshModel(job, h3.ports, aiPort(0, reply('{"verdict":"WRONG"}')), options());
    ok("cap 0: no audit, change applied (default)", r3.applied.length === 1);
    const h4 = harness({ text: pageText(599_000), prior: { "t.smart": 599_000 } });
    const r4 = await refreshModel(job, h4.ports, aiPort(0, reply("{}")), options({ require_audit: true }));
    ok("cap 0 with --require-audit: held", r4.applied.length === 0 && r4.held.length === 1, r4);
  }
  // 7. unchanged price: nothing to do
  {
    const h = harness();
    const r = await refreshModel(job, h.ports, null, options());
    ok("no change: no write, no card", r.applied.length === 0 && r.pending.length === 0 && h.calls.applied.length === 0 && h.calls.inbox.length === 0, { r, inbox: h.calls.inbox });
  }
  // 8. unknown model
  {
    const h = harness();
    h.ports.loadModel = async () => null;
    const r = await refreshModel(job, h.ports, null, options());
    ok("unknown model reported", r.status === "UNKNOWN_MODEL");
  }
  console.log(failed ? `\n${failed} FAILED, ${passed} passed` : `all ${passed} price-run cases passed`);
  process.exit(failed ? 1 : 0);
})();
