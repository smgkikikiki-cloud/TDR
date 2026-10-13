/**
 * OEM playbook architecture, offline: contract validation, per-strategy reading, MSRP / promotion separation,
 * incomplete lineups, missing prices, stale sources, fallbacks, and the PR #233 discontinue protections end to end.
 * Every page here is FAKE (scripts/fixtures/price-playbook.ts).
 */
import { htmlToText, openHttpFetchers } from "../lib/price-refresh/fetcher.ts";
import { lineupDeclared, legacySource, sourcesByModel, usablePlaybooks, validatePlaybook } from "../lib/price-refresh/playbook.ts";
import { mergeSources, parseDate, readSource, clipSection } from "../lib/price-refresh/source.ts";
import { refreshModel, type Ports, type RunOptions } from "../lib/price-refresh/run.ts";
import type { History } from "../lib/price-refresh/store.ts";
import * as F from "./fixtures/price-playbook.ts";

let failed = 0, passed = 0;
function ok(name: string, c: unknown, detail?: unknown) {
  if (c) passed++; else { failed++; console.log(`  FAIL ${name}${detail === undefined ? "" : "\n       " + JSON.stringify(detail).slice(0, 700)}`); }
}
const NOW = new Date("2026-10-12T10:00:00Z");
const page = (text: string, url = "https://acme.example/p") => ({ url, text, content_hash: "sha256:" + text.length, fetched_at: NOW.toISOString() });
const known = [{ trim_id: F.tid("smart"), name: "Smart" }, { trim_id: F.tid("sport"), name: "Sport" }, { trim_id: F.tid("premium"), name: "Premium" }];
const read = (src: ReturnType<typeof F.source>, text: string) => readSource(src, page(text, src.url), known, "ACME", "Roadster", F.TODAY);
const problems = (pb: unknown) => validatePlaybook(pb).join(" | ");

// --- 1. the contract --------------------------------------------------------------------------------------------------
const base = F.source({ id: "model", role: "MODEL_PAGE" });
ok("a plain valid playbook has no problems", validatePlaybook(F.playbook([base])).length === 0, validatePlaybook(F.playbook([base])));
ok("lineup_complete without a signed verification is refused", /needs lineup_verification/.test(problems(F.playbook([{ ...base, lineup_complete: true }]))));
ok("lineup_complete in a DRAFT playbook is refused", /only a VERIFIED playbook/.test(problems(F.playbook([{ ...base, ...F.VERIFIED_COMPLETE }], { status: "DRAFT" }))));
ok("a complete lineup needs existence authority", /needs authority.existence/.test(problems(F.playbook([{ ...base, ...F.VERIFIED_COMPLETE, authority: { prices: true, existence: false } }]))));
ok("VERIFIED without evidence is refused", /needs evidence/.test(problems(F.playbook([base], { evidence: [] }))));
ok("a brochure cannot carry price or existence authority", /evidence only/.test(problems(F.playbook([{ ...base, id: "b", role: "BROCHURE" }]))));
ok("a brochure with no authority is fine", validatePlaybook(F.playbook([base, { ...base, id: "b", role: "BROCHURE", authority: { prices: false, existence: false } }])).length === 0);
ok("PRICE_LIST_PDF must be fetched as PDF", /must be fetched as PDF/.test(problems(F.playbook([{ ...base, role: "PRICE_LIST_PDF" }]))));
ok("ROW_REGEX needs named groups name and price", /named group/.test(problems(F.playbook([{ ...base, extraction: { mode: "ROW_REGEX", row_regex: "(.*) (.*)" } }]))));
ok("a regex that does not compile is refused", /does not compile/.test(problems(F.playbook([{ ...base, extraction: { mode: "ROW_REGEX", row_regex: "(?<name>" } }]))));
ok("duplicate source ids, non-https urls and bad model ids are refused", /duplicate id/.test(problems(F.playbook([base, base]))) && /https/.test(problems(F.playbook([{ ...base, url: "http://x" }]))) && /canonical model ids/.test(problems(F.playbook([{ ...base, models: ["Roadster"] }]))));
ok("fallback_of must name a real primary, no chains", /not a source/.test(problems(F.playbook([{ ...base, fallback_of: "nope" }]))) && /chains/.test(problems(F.playbook([base, { ...base, id: "f1", fallback_of: "model" }, { ...base, id: "f2", fallback_of: "f1" }]))));
ok("as_of needs a date group", /named group/.test(problems(F.playbook([{ ...base, as_of: { pattern: "effective", stale_after_days: 30 } }]))));

const draft = F.playbook([base], { status: "DRAFT" });
ok("DRAFT playbooks run in dry runs only", usablePlaybooks([draft], { apply: false }).usable.length === 1 && usablePlaybooks([draft], { apply: true }).rejected.length === 1);
ok("an invalid playbook is rejected with reasons, never partly used", usablePlaybooks([{ ...draft, sources: [] } as any], { apply: false }).rejected.length === 1);
{
  const verified = F.source({ id: "pl", ...F.VERIFIED_COMPLETE });
  ok("lineup is declared only by a verified, fresh, signed source", lineupDeclared(verified, F.TODAY));
  ok("a successful fetch alone declares nothing (default false)", !lineupDeclared(F.source({ id: "x" }), F.TODAY));
  ok("a verification older than 90 days no longer counts", !lineupDeclared(F.source({ id: "x", lineup_complete: true, lineup_verification: { verified_on: "2026-06-01", verified_by: "f", evidence_ref: "f" } }), F.TODAY));
  ok("a DRAFT playbook never declares completeness, even if the flag is set", !lineupDeclared({ ...verified, playbook_status: "DRAFT" }, F.TODAY));
  ok("a legacy registry target never declares completeness", !lineupDeclared(legacySource({ id: "t", url: "https://x.y" }, F.MODEL), F.TODAY));
  const idx = sourcesByModel([F.playbook([F.source({ id: "b", priority: 2 }), F.source({ id: "a", priority: 1 })])]);
  ok("sources are ordered most trusted first", idx.get(F.MODEL)!.map((s) => s.id).join() === "a,b");
}

// --- 2. reading, per strategy ------------------------------------------------------------------------------------------
ok("htmlToText keeps one table row on one line", /Smart \| 599,000 บาท/.test(htmlToText(F.PRICE_LIST_HTML)), htmlToText(F.PRICE_LIST_HTML).slice(0, 200));
ok("dates: ISO, dd/mm/yyyy and Buddhist years", parseDate("2026-09-23") === "2026-09-23" && parseDate("23/09/2569") === "2026-09-23" && parseDate("31/02/2026") === null);
ok("clipSection: missing marker means the layout changed", clipSection("a START b END c", { start: "start", end: "end" })?.trim() === "b" && clipSection("abc", { start: "zzz" }) === null);
{
  const s = F.source({ id: "anch" });
  const r = read(s, F.MODEL_PAGE_WITH_PRICES);
  ok("BROWSER/ANCHORED: reads each grade's list price", r.state === "OK" && r.observations.length === 3, r);
  const none = read(F.source({ id: "np" }), F.MODEL_PAGE_NO_PRICES);
  ok("a model page with NO prices: grades seen, no price invented", none.state === "OK" && none.names_seen.length === 3 && none.observations.length === 0, none);
  const noAuth = read(F.source({ id: "na", authority: { prices: false, existence: true } }), F.MODEL_PAGE_WITH_PRICES);
  ok("a source without price authority never supplies a price", noAuth.observations.length === 0 && noAuth.names_seen.length === 3);
  const html = read(F.source({ id: "html", role: "PRICE_LIST", fetch: { kind: "HTML" }, extraction: { mode: "ROW_REGEX", row_regex: F.SOURCE_ROW }, as_of: { pattern: "มีผล (?<date>[\\d/]+)", stale_after_days: 60 } }), htmlToText(F.PRICE_LIST_HTML));
  ok("HTML price list: row regex reads grade + price, the instalment row is not a price", html.state === "OK" && html.observations.length === 3 && !html.observations.some((o) => o.name_raw === "Ghost"), html);
  ok("...and the page date (Buddhist year) is understood", html.as_of === "2026-09-23", html.as_of);
  const pdf = read(F.source({ id: "pdf", role: "PRICE_LIST_PDF", fetch: { kind: "PDF" }, extraction: { mode: "ROW_REGEX", row_regex: F.PDF_ROW, section: { start: "Price (THB)" } } }), F.PRICE_LIST_PDF_TEXT);
  ok("PDF price list: four list prices read", pdf.state === "OK" && pdf.observations.length === 4, pdf);
  ok("PDF: the special price is a PROMOTION, the list price stays 699,000", pdf.promotions.length === 1 && pdf.promotions[0].amount_thb === 649_000 && pdf.observations.find((o) => o.name_raw === "Premium Edition")?.amount_thb === 699_000, pdf);
  ok("a section marker missing from the page is reported, nothing read", read(F.source({ id: "sm", extraction: { mode: "ANCHORED", section: { start: "no such heading" } } }), F.MODEL_PAGE_WITH_PRICES).state === "SECTION_MISSING");
  ok("a page with nothing recognisable is EMPTY, not OK", read(F.source({ id: "e" }), "สวัสดี ".repeat(80)).state === "EMPTY");
  const stale = read(F.source({ id: "st", extraction: { mode: "ROW_REGEX", row_regex: F.SOURCE_ROW }, as_of: { pattern: "มีผล (?<date>[\\d/]+)", stale_after_days: 10 } }), htmlToText(F.PRICE_LIST_HTML));
  ok("a price list dated 19 days ago with a 10 day limit is STALE and supplies nothing", stale.state === "STALE" && stale.observations.length === 0, stale);
  const undated = read(F.source({ id: "ud", as_of: { pattern: "effective (?<date>[\\d-]+)", stale_after_days: 30, required: true } }), F.MODEL_PAGE_WITH_PRICES);
  ok("a required date that cannot be found makes the source STALE", undated.state === "STALE");
  const promo = read(F.source({ id: "pr" }), F.PROMO_ONLY_PAGE);
  ok("a promotion-only page yields NO list observation", promo.observations.length === 0 && promo.promotions.length === 1 && promo.promotions[0].kind === "PROMOTION", promo);
  const mixed = read(F.source({ id: "mx" }), F.MSRP_AND_FROM_PAGE);
  ok("MSRP beside a lower FROM price: ambiguous until the playbook says", mixed.observations.length === 0 && mixed.ambiguous.length === 1, mixed);
  const msrp = read(F.source({ id: "mx2", price_semantics: { mixed_msrp: "MSRP_IS_LIST" } }), F.MSRP_AND_FROM_PAGE);
  ok("with mixed_msrp=MSRP_IS_LIST the MSRP is the list price and FROM is a promotion", msrp.observations[0]?.amount_thb === 569_000 && msrp.promotions[0]?.amount_thb === 539_000, msrp);
}

// --- 3. merging several sources ----------------------------------------------------------------------------------------
{
  const model = read(F.source({ id: "m", priority: 2, authority: { prices: false, existence: true } }), F.MODEL_PAGE_NO_PRICES);
  const list = read(F.source({ id: "l", role: "PRICE_LIST", priority: 1, extraction: { mode: "ROW_REGEX", row_regex: F.SOURCE_ROW } }), htmlToText(F.PRICE_LIST_HTML));
  const m = mergeSources([model, list]);
  ok("names from a price-less model page + prices from the price list = one row per grade", m.rows.length === 3 && m.rows.every((r) => r.amount_thb !== null), m.rows);
  const priced = read(F.source({ id: "p", priority: 2 }), F.MODEL_PAGE_WITH_PRICES);
  ok("two sources agreeing on a price: one row, no conflict", mergeSources([list, priced]).rows.length === 3 && mergeSources([list, priced]).conflicts.length === 0);
  const differing = read(F.source({ id: "d", priority: 2 }), F.MODEL_PAGE_WITH_PRICES.replace("599,000", "589,000"));
  const c = mergeSources([list, differing]);
  ok("two sources disagreeing: a conflict and NO price for that grade", c.conflicts.length === 1 && c.rows.find((r) => r.name_raw === "Smart")?.amount_thb === null, c);
  const promoOnly = mergeSources([read(F.source({ id: "pr" }), F.PROMO_ONLY_PAGE)]);
  ok("promotions are carried separately: the grade is a name-only row, the promo price is not a row amount", promoOnly.rows.every((r) => r.amount_thb === null) && promoOnly.promotions.length === 1, promoOnly);
  const stale = read(F.source({ id: "s", priority: 1, extraction: { mode: "ROW_REGEX", row_regex: F.SOURCE_ROW }, as_of: { pattern: "มีผล (?<date>[\\d/]+)", stale_after_days: 5 } }), htmlToText(F.PRICE_LIST_HTML));
  ok("a stale source is ignored by the merge", mergeSources([stale]).rows.length === 0);
}

// --- 4. end to end through refreshModel ---------------------------------------------------------------------------------
function loaded(extraTrims: { id: string; name: string; price: number }[] = []) {
  const specs = [{ id: "smart", name: "Smart", price: 589_000 }, { id: "sport", name: "Sport", price: 569_000 }, { id: "premium", name: "Premium", price: 679_000 }, ...extraTrims];
  const trims = specs.map((t) => F.trimRow(t.id, t.name));
  return {
    brand_name: "ACME", model_name: "Roadster",
    trims: specs.map((t) => ({ trim_id: F.tid(t.id), name: t.name, aliases: [], status: "CURRENT" as const, price_thb: t.price, name_locked: false })),
    snapshot: {
      model: { canonical_id: F.MODEL, revision: 3, retail_price_min: 569_000, retail_price_max: 679_000, payload: {}, status: "CURRENT" },
      generations: [{ id: "g1", model_id: F.MODEL, launched: "2022-01-01", ended: null, code: "G1" }],
      trims, campaigns: new Map(), prices: specs.map((t, i) => F.ledgerRow(i + 1, t.id, t.price)),
      lifecycle: { approved: new Map(), decisions: new Map(), maintenance: new Set<string>() },
    },
  };
}
function harness(pages: Record<string, string | null>, opts: { prior?: Record<string, number>; lastSeen?: Record<string, string>; extra?: { id: string; name: string; price: number }[]; noPdf?: boolean } = {}) {
  const calls = { observations: [] as any[], inbox: [] as any[], applied: [] as any[], fetched: [] as string[] };
  const get = (url: string) => {
    calls.fetched.push(url);
    const text = pages[url];
    return text == null ? ({ ok: false, kind: "FAILED", error: "HTTP 503" } as const) : ({ ok: true, page: page(text, url) } as const);
  };
  const history = (): History => ({ prior_amounts: new Map(Object.entries(opts.prior ?? {}).map(([k, v]) => [F.tid(k), v])),
    last_seen: new Map(Object.entries(opts.lastSeen ?? {}).map(([k, v]) => [F.tid(k), v])), first_observed: "2026-09-01",
    read_dates: Array.from({ length: 42 }, (_, i) => new Date(Date.parse("2026-09-01") + i * 86_400_000).toISOString().slice(0, 10)) });
  const ports: Ports = {
    fetch: async (url) => get(url), fetchHtml: async (url) => get(url), fetchPdf: opts.noPdf ? undefined : async (url) => get(url),
    loadModel: async () => loaded(opts.extra) as any, loadHistory: async () => history(), loadApprovedJumps: async () => [], markJumpApplied: async () => {},
    insertObservations: async (rows) => { calls.observations.push(...rows); },
    proposeInbox: async (p) => { calls.inbox.push(p); return {}; },
    applyPriceChanges: async (_b, items) => { calls.applied.push(...items); return items.map((i) => ({ trim_id: i.trim_id, status: "APPLIED" })); },
    saveSourceState: async () => {},
  };
  return { ports, calls };
}
const opts = (over: Partial<RunOptions> = {}): RunOptions => ({ run_id: "run-p", now: NOW, today: F.TODAY, apply: true, use_ai: false, require_audit: false, source_state: new Map(), ...over });
const SEEN_TWICE = { smart: 599_000 };

(async () => {
  const listSrc = F.source({ id: "list", role: "PRICE_LIST", fetch: { kind: "HTML" }, priority: 1, extraction: { mode: "ROW_REGEX", row_regex: F.SOURCE_ROW }, ...F.VERIFIED_COMPLETE });
  const modelSrc = F.source({ id: "model", role: "MODEL_PAGE", priority: 2, authority: { prices: false, existence: true } });
  const listHtml = htmlToText(F.PRICE_LIST_HTML.replace("23/09/2569", "23/09/2569"));

  // 4a. maker whose model page has no prices: the price list is the authority
  {
    const h = harness({ [listSrc.url]: listHtml, [modelSrc.url]: F.MODEL_PAGE_NO_PRICES }, { prior: SEEN_TWICE });
    const r = await refreshModel({ model_id: F.MODEL, targets: [], sources: [listSrc, modelSrc] }, h.ports, null, opts());
    ok("price-less model page + price list: the price is applied from the list (second sighting)", r.applied.length === 1 && r.applied[0].to === 599_000, r);
    ok("...through the existing writer, as a LIST_PRICE row from the list's url", h.calls.applied[0]?.new_row.price_type === "LIST_PRICE" && h.calls.applied[0].new_row.source_ref.includes("acme.example/list"), h.calls.applied[0]);
    ok("both sources are reported", r.sources.length === 2 && r.sources.every((s) => s.used), r.sources);
  }
  // 4b. promotions never become LIST_PRICE
  {
    const promoSrc = F.source({ id: "promo" });
    const h = harness({ [promoSrc.url]: F.PROMO_ONLY_PAGE }, { prior: { sport: 539_000 } });
    const r = await refreshModel({ model_id: F.MODEL, targets: [], sources: [promoSrc] }, h.ports, null, opts());
    ok("a promotion-only page changes no price", r.applied.length === 0 && h.calls.applied.length === 0, r);
    ok("...and is stored as a CAMPAIGN_PRICE observation, not LIST_PRICE", h.calls.observations.some((o) => o.field_key === "CAMPAIGN_PRICE" && o.amount_thb === 539_000) && !h.calls.observations.some((o) => o.field_key === "LIST_PRICE" && o.amount_thb === 539_000), h.calls.observations);
    const pdfSrc = F.source({ id: "pdf", role: "PRICE_LIST_PDF", fetch: { kind: "PDF" }, extraction: { mode: "ROW_REGEX", row_regex: F.PDF_ROW, section: { start: "Price (THB)" } } });
    const h2 = harness({ [pdfSrc.url]: F.PRICE_LIST_PDF_TEXT }, { prior: { smart: 599_000 } });
    const r2 = await refreshModel({ model_id: F.MODEL, targets: [], sources: [pdfSrc] }, h2.ports, null, opts());
    ok("PDF strategy end to end: list price applied, special price only recorded as a promotion", r2.applied.length === 1 && r2.promotions === 1 && !h2.calls.applied.some((i) => i.new_row.amount_thb === 649_000), r2);
  }
  // 4c. incomplete lineup: the model page shows fewer grades; PR #233 protections
  {
    const partial = F.source({ id: "partial" });             // lineup_complete defaulted to false
    const h = harness({ [partial.url]: F.MODEL_PAGE_PARTIAL }, { lastSeen: { sport: "2026-10-01", premium: "2026-10-01" } });
    const r = await refreshModel({ model_id: F.MODEL, targets: [], sources: [partial] }, h.ports, null, opts({ apply: false }));
    ok("a partial page (1 of 3 grades) never proposes discontinuing the other grades", !r.proposals.some((p) => p.startsWith("DISCONTINUE")), r);
    ok("...and lineup_complete is false", r.lineup_complete === false);
  }
  {
    const ghost = { id: "ghost", name: "Ghost", price: 450_000 };
    const h = harness({ [listSrc.url]: listHtml }, { extra: [ghost], lastSeen: { ghost: "2026-10-01" } });
    const r = await refreshModel({ model_id: F.MODEL, targets: [], sources: [listSrc] }, h.ports, null, opts({ apply: false }));
    ok("a VERIFIED complete price list that really lacks a grade for 7+ read days: discontinue is proposed (as a card)", r.proposals.some((p) => p.startsWith("DISCONTINUE")) && r.lineup_complete, r);
    const stale = { ...listSrc, lineup_verification: { ...listSrc.lineup_verification!, verified_on: "2026-05-01" } };
    const h2 = harness({ [listSrc.url]: listHtml }, { extra: [ghost], lastSeen: { ghost: "2026-10-01" } });
    const r2 = await refreshModel({ model_id: F.MODEL, targets: [], sources: [stale] }, h2.ports, null, opts({ apply: false }));
    ok("an expired verification: same page, no discontinue", !r2.proposals.some((p) => p.startsWith("DISCONTINUE")) && !r2.lineup_complete, r2);
    const draftSrc = { ...listSrc, playbook_status: "DRAFT" as const };
    const h3 = harness({ [listSrc.url]: listHtml }, { extra: [ghost], lastSeen: { ghost: "2026-10-01" } });
    const r3 = await refreshModel({ model_id: F.MODEL, targets: [], sources: [draftSrc] }, h3.ports, null, opts({ apply: false }));
    ok("a DRAFT playbook cannot declare completeness", !r3.proposals.some((p) => p.startsWith("DISCONTINUE")), r3);
    const legacy = harness({ "https://acme.example/legacy": F.MODEL_PAGE_WITH_PRICES }, { extra: [ghost], lastSeen: { ghost: "2026-10-01" } });
    const r4 = await refreshModel({ model_id: F.MODEL, targets: [{ id: "legacy", url: "https://acme.example/legacy", lineup_complete: true }] }, legacy.ports, null, opts({ apply: false }));
    ok("the legacy registry path ignores a lineup_complete flag", !r4.proposals.some((p) => p.startsWith("DISCONTINUE")) && !r4.lineup_complete, r4);
  }
  // 4d. stale, failing, fallback
  {
    const staleList = { ...listSrc, as_of: { pattern: "มีผล (?<date>[\\d/]+)", stale_after_days: 5 } };
    const h = harness({ [listSrc.url]: listHtml }, { prior: SEEN_TWICE });
    const r = await refreshModel({ model_id: F.MODEL, targets: [], sources: [staleList] }, h.ports, null, opts());
    ok("a stale required price list stops the model: nothing written", r.status === "BATCH_STOPPED" && h.calls.applied.length === 0 && h.calls.observations.length === 0, r);
    const fallback = F.source({ id: "fb", priority: 3, fallback_of: "list", ...F.VERIFIED_COMPLETE });
    const h2 = harness({ [listSrc.url]: listHtml, [fallback.url]: F.MODEL_PAGE_WITH_PRICES }, { prior: SEEN_TWICE });
    const r2 = await refreshModel({ model_id: F.MODEL, targets: [], sources: [staleList, fallback] }, h2.ports, null, opts());
    ok("with a fallback the model continues from it", r2.status !== "BATCH_STOPPED" && r2.applied.length === 1 && r2.sources.find((s) => s.id === "fb")?.degraded, r2);
    ok("a fallback never completes the lineup, verified or not", r2.lineup_complete === false, r2);
    const h3 = harness({ [listSrc.url]: listHtml, [fallback.url]: F.MODEL_PAGE_WITH_PRICES }, { prior: SEEN_TWICE });
    await refreshModel({ model_id: F.MODEL, targets: [], sources: [listSrc, fallback] }, h3.ports, null, opts());
    ok("a healthy primary: its fallback is never fetched", !h3.calls.fetched.includes(fallback.url), h3.calls.fetched);
    const down = harness({ [listSrc.url]: null, [fallback.url]: null });
    const r4 = await refreshModel({ model_id: F.MODEL, targets: [], sources: [listSrc, fallback] }, down.ports, null, opts());
    ok("primary and fallback both down: batch stopped", r4.status === "BATCH_STOPPED" && down.calls.applied.length === 0, r4);
    const optional = { ...modelSrc, required: false };
    const h5 = harness({ [listSrc.url]: listHtml, [optional.url]: null }, { prior: SEEN_TWICE });
    const r5 = await refreshModel({ model_id: F.MODEL, targets: [], sources: [listSrc, optional] }, h5.ports, null, opts());
    ok("an optional source that fails does not stop the model", r5.status !== "BATCH_STOPPED" && r5.applied.length === 1, r5);
    const h6 = harness({ [listSrc.url]: listHtml }, { prior: SEEN_TWICE, noPdf: true });
    const pdfOnly = F.source({ id: "pdfsrc", role: "PRICE_LIST_PDF", fetch: { kind: "PDF" }, extraction: { mode: "ROW_REGEX", row_regex: F.PDF_ROW } });
    const r6 = await refreshModel({ model_id: F.MODEL, targets: [], sources: [pdfOnly] }, h6.ports, null, opts());
    ok("a strategy with no adapter fails the source instead of silently using another", r6.status === "BATCH_STOPPED" && /no PDF adapter/.test(r6.fetch_errors[0] ?? ""), r6);
  }
  // 4e. disagreement between sources
  {
    const modelPriced = F.source({ id: "model", priority: 2 });
    const h = harness({ [listSrc.url]: listHtml, [modelPriced.url]: F.MODEL_PAGE_WITH_PRICES.replace("599,000", "589,000") }, { prior: SEEN_TWICE });
    const r = await refreshModel({ model_id: F.MODEL, targets: [], sources: [listSrc, modelPriced] }, h.ports, null, opts());
    ok("price list says 599,000, model page says 589,000: reported, nothing applied for that grade", r.conflicts.length === 1 && !h.calls.applied.some((i) => i.trim_id === F.tid("smart")), r);
  }
  // 4f. evidence-only roles are not even fetched
  {
    const brochure = F.source({ id: "brochure", role: "BROCHURE", authority: { prices: false, existence: false } });
    const h = harness({ [listSrc.url]: listHtml, [brochure.url]: "brochure with GT-Line 899,000" + F.pad }, { prior: SEEN_TWICE });
    await refreshModel({ model_id: F.MODEL, targets: [], sources: [listSrc, brochure] }, h.ports, null, opts({ apply: false }));
    ok("brochures and announcements are not fetched into the price path", !h.calls.fetched.includes(brochure.url), h.calls.fetched);
  }
  // 4g. HTTP adapters: robots + blocked
  {
    const f = openHttpFetchers({ pauseMs: 0, fetchImpl: (async (url: string) => {
      const u = String(url);
      if (u.endsWith("/robots.txt")) return new Response("User-agent: *\nDisallow: /private\n");
      if (u.includes("/private")) return new Response("x".repeat(500));
      if (u.includes("/blocked")) return new Response("no", { status: 403 });
      return new Response("<html><body><p>" + "ราคา Smart 599,000 บาท ".repeat(20) + "</p></body></html>");
    }) as any });
    ok("HTML adapter: reads a page", (await f.html("https://acme.example/ok")).ok === true);
    const robots = await f.html("https://acme.example/private/x");
    ok("HTML adapter: robots.txt refusal is BLOCKED", !robots.ok && robots.kind === "BLOCKED");
    const blocked = await f.html("https://acme.example/blocked");
    ok("HTML adapter: HTTP 403 is BLOCKED, not retried around", !blocked.ok && blocked.kind === "BLOCKED");
  }

  console.log(failed ? `\n${failed} FAILED, ${passed} passed` : `all ${passed} price-playbook cases passed`);
  process.exit(failed ? 1 : 0);
})();
