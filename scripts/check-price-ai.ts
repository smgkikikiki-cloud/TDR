/** lib/price-refresh/ai.ts: budget, fail-closed behaviour, and the literal-evidence gate on model output. No network. */
import {
  auditChange, Budget, cycleStart, DEFAULT_AI_SETTINGS, daysLeftInCycle, extractWithAi, type AiSettings, type Messages,
} from "../lib/price-refresh/ai.ts";

let failed = 0;
let passed = 0;
function ok(name: string, condition: unknown, detail?: unknown) {
  if (condition) { passed++; return; }
  failed++;
  console.log(`  FAIL ${name}${detail === undefined ? "" : `\n       ${JSON.stringify(detail).slice(0, 500)}`}`);
}

const NOW = new Date("2026-10-12T10:00:00Z");
const settings = (cap: number, extra: Partial<AiSettings> = {}): AiSettings => ({ ...DEFAULT_AI_SETTINGS, monthly_cap_usd: cap, ...extra });
const page = { url: "https://example.test", content_hash: "sha256:x", fetched_at: "2026-10-12T00:00:00Z",
  text: "Smart ราคาเริ่มต้น 599,000 บาท\nSport ราคาเริ่มต้น 569,000 บาท" };
const reply = (text: string, input = 1_200, output = 150): Messages => async () => ({
  status: 200, json: { content: [{ type: "text", text }], usage: { input_tokens: input, output_tokens: output } } });
const failing = (status: number, message: string): Messages => async () => ({ status, json: { error: { message } } });
const noUsage = () => {};

// --- billing cycle ----------------------------------------------------------------------------------------------
ok("cycle start: before the cycle day it is last month", cycleStart(new Date("2026-10-12T00:00:00Z"), 20).toISOString().startsWith("2026-09-20"));
ok("cycle start: on/after the cycle day it is this month", cycleStart(new Date("2026-10-25T00:00:00Z"), 20).toISOString().startsWith("2026-10-20"));
ok("days left in cycle counts today", daysLeftInCycle(new Date("2026-10-12T10:00:00Z"), 1) === 20, daysLeftInCycle(new Date("2026-10-12T10:00:00Z"), 1));

// --- budget -----------------------------------------------------------------------------------------------------
{
  ok("cap 0: nothing is affordable", !new Budget(settings(0), [], NOW).canAfford(100, 10));
  const b = new Budget(settings(10), [], NOW);
  ok("cap 10 USD: a small call is affordable", b.canAfford(20_000, 1_500));
  ok("daily allowance is the remaining month spread over the days left", Math.abs(b.allowanceToday() - 10 / 20) < 1e-9, b.allowanceToday());
  const spent = new Budget(settings(10), [{ at: "2026-10-12T01:00:00Z", cost_usd: 0.5 }], NOW);
  ok("today's allowance is used up", spent.allowanceToday() === 0, spent.allowanceToday());
  const earlier = new Budget(settings(10), [{ at: "2026-10-05T01:00:00Z", cost_usd: 1.9 }], NOW);
  ok("earlier days' spend lowers the remaining month, and so today's share",
    Math.abs(earlier.allowanceToday() - 8.1 / 20) < 1e-9, earlier.allowanceToday());
  const over = new Budget(settings(10), [{ at: "2026-10-05T01:00:00Z", cost_usd: 10.5 }], NOW);
  ok("month exhausted: nothing", over.allowanceToday() === 0);
  const lastCycle = new Budget(settings(10), [{ at: "2026-09-05T01:00:00Z", cost_usd: 99 }], NOW);
  ok("spend from a previous cycle does not count", lastCycle.allowanceToday() > 0);
  const hungry = new Budget(settings(0.01), [], NOW);
  ok("a call that could exceed today's allowance is not made", !hungry.canAfford(200_000, 4_000));
}

// --- extraction -------------------------------------------------------------------------------------------------
const ctx = (cap: number, messages: Messages) => ({
  budget: new Budget(settings(cap), [], NOW), messages, settings: settings(cap), model_name: "Yaris", onUsage: noUsage });
const good = JSON.stringify({ rows: [
  { name: "Smart", amount_thb: 599000, vat_included: null, quote: "Smart ราคาเริ่มต้น 599,000 บาท" },
  { name: "Sport", amount_thb: 559000, vat_included: null, quote: "Sport ราคาเริ่มต้น 559,000 บาท" },      // invented
  { name: "Sport", amount_thb: 569000, vat_included: null, quote: "Sport ราคาเริ่มต้น 569,000 บาท" },
  { name: "Premium", amount_thb: 679000, vat_included: null, quote: "Premium ราคาเริ่มต้น 679,000 บาท" },  // not on the page
] });
(async () => {
  {
    const zero = await extractWithAi(page, [], ctx(0, reply(good)));
    ok("cap 0: the model is never called", zero.called === false && zero.rows.length === 0);
    let calls = 0;
    const counting: Messages = async (body) => { calls++; return reply(good)(body); };
    await extractWithAi(page, [], ctx(0, counting));
    ok("cap 0: zero HTTP calls", calls === 0, calls);
  }
  {
    const c = ctx(10, reply("Here you go:\n" + good));
    const out = await extractWithAi(page, [], c);
    ok("accepts only rows whose quote is literal page text", out.rows.length === 2 && out.rows.map((r) => r.amount_thb).sort().join() === "569000,599000", out);
    ok("rejects the invented amount and the absent grade", out.rejected.length === 2, out.rejected);
    ok("spend is recorded", c.budget.spent > 0);
    ok("rows are marked as AI-read", out.rows.every((r) => r.method === "AI"));
  }
  {
    const c = ctx(10, failing(400, "Your credit balance is too low to access the Anthropic API"));
    const out = await extractWithAi(page, [], c);
    ok("credit error: no rows and the run is halted", out.called === false && c.budget.halted !== null, c.budget.halted);
    const again = await extractWithAi(page, [], { ...c, messages: reply(good) });
    ok("after a halt no further call is made even if the API would answer", again.called === false);
  }
  for (const status of [401, 429, 529]) {
    const c = ctx(10, failing(status, "x"));
    await extractWithAi(page, [], c);
    ok(`HTTP ${status} halts the run`, c.budget.halted !== null);
  }
  {
    const c = ctx(10, failing(500, "boom"));
    const out = await extractWithAi(page, [], c);
    ok("HTTP 500 fails this call only (not a halt)", out.called === false && c.budget.halted === null);
  }
  {
    const c = ctx(10, reply("not json at all"));
    const out = await extractWithAi(page, [], c);
    ok("garbage answer: no rows, no crash", out.rows.length === 0 && out.called === true);
  }

  // --- auditor ---------------------------------------------------------------------------------------------------
  const change = { trim_name: "Smart", old_amount_thb: 589_000, new_amount_thb: 599_000, evidence: "Smart ราคาเริ่มต้น 599,000 บาท" };
  {
    const a = await auditChange(change, ctx(10, reply('{"verdict":"CORRECT","reason":"stated"}')));
    ok("auditor: CORRECT", a.verdict === "CORRECT", a);
    const w = await auditChange(change, ctx(10, reply('{"verdict":"WRONG","reason":"that is an instalment"}')));
    ok("auditor: WRONG", w.verdict === "WRONG");
    const s = await auditChange(change, ctx(0, reply('{"verdict":"CORRECT","reason":"x"}')));
    ok("auditor with cap 0: SKIPPED, never silently CORRECT", s.verdict === "SKIPPED", s);
    const bad = await auditChange(change, ctx(10, reply('{"verdict":"MAYBE"}')));
    ok("auditor: an unknown verdict is UNSURE", bad.verdict === "UNSURE", bad);
  }

  console.log(failed ? `\n${failed} FAILED, ${passed} passed` : `all ${passed} price-ai cases passed`);
  process.exit(failed ? 1 : 0);
})();
