/** lib/price-refresh/extract.ts: anchored extraction and the literal-evidence rule, on page shapes seen on OEM sites. */
import { extractAnchored, validateEvidence, amountsIn, type KnownTrim, type PageText } from "../lib/price-refresh/extract.ts";

let failed = 0;
let passed = 0;
function ok(name: string, condition: unknown, detail?: unknown) {
  if (condition) { passed++; return; }
  failed++;
  console.log(`  FAIL ${name}${detail === undefined ? "" : `\n       ${JSON.stringify(detail).slice(0, 600)}`}`);
}
const page = (text: string): PageText => ({ url: "https://example.test/model", text, content_hash: "sha256:x", fetched_at: "2026-10-12T00:00:00Z" });
const trims = (...names: string[]): KnownTrim[] => names.map((n) => ({ trim_id: `t.${n.toLowerCase().replace(/\W+/g, "_")}`, name: n }));
const priceOf = (r: ReturnType<typeof extractAnchored>, name: string) => r.observations.find((o) => o.name_raw === name)?.amount_thb;

// Toyota-style: grade headings on their own lines, price lines below, a headline price first.
const TOYOTA = `Yaris Ativ
ราคา ฿569,000 +
เลือกรุ่นที่ใช่
HEV Premium
ราคาเริ่มต้น 729,000 บาท
Premium Luxury
ราคาเริ่มต้น 709,000 บาท
NIGHTSHADE
ราคาเริ่มต้น 709,000 บาท
Premium
ราคาเริ่มต้น 679,000 บาท
Smart
ราคาเริ่มต้น 599,000 บาท
Sport
ราคาเริ่มต้น 569,000 บาท
ผ่อนเริ่มต้น 7,990 บาท/เดือน`;
{
  const r = extractAnchored(page(TOYOTA), trims("HEV Premium", "Premium Luxury", "NIGHTSHADE", "Premium", "Smart", "Sport"), "Toyota", "Yaris Ativ");
  ok("Toyota-style: all six grades read", r.observations.length === 6, r);
  ok("longer names mask shorter ones ('Premium Luxury' is not 'Premium')",
    priceOf(r, "Premium Luxury") === 709_000 && priceOf(r, "Premium") === 679_000 && priceOf(r, "HEV Premium") === 729_000, r.observations);
  ok("the headline price before any grade name is not attributed to a grade", priceOf(r, "Sport") === 569_000);
  ok("an instalment figure (7,990) is never taken as a price", !r.observations.some((o) => o.amount_thb < 150_000));
  ok("evidence keeps the surrounding text", r.observations.every((o) => o.evidence.length > 8 && amountsIn(o.evidence.replace(/\s+/g, " ")).length >= 0));
}

// Nissan-style: the grade name and its price are on one line.
{
  const text = `ALMERA
1.0L Turbo VL CVT 699,000 บาท
1.0L Turbo V CVT 669,000 บาท
1.0L Turbo EL CVT 589,000 บาท
1.0L Turbo E CVT 573,000 บาท`;
  const r = extractAnchored(page(text), trims("1.0L Turbo VL CVT", "1.0L Turbo V CVT", "1.0L Turbo EL CVT", "1.0L Turbo E CVT"), "Nissan", "Almera");
  ok("Nissan-style: one line per grade, decimals in names survive", r.observations.length === 4
    && priceOf(r, "1.0L Turbo VL CVT") === 699_000 && priceOf(r, "1.0L Turbo E CVT") === 573_000, r);
}

// A price shown as a reference ("MSRP") is not the list price of the grade next to it.
{
  const r = extractAnchored(page("TANK 300 HEV\nFROM 1,279,000.-\nMSRP : 1,799,000.-"), trims("TANK 300 HEV"), "GWM", "Tank 300");
  ok("first plausible price after the name wins, MSRP reference ignored", priceOf(r, "TANK 300 HEV") === 1_279_000, r);
}

// Conflicting prices for one name -> reported ambiguous, no observation.
{
  const r = extractAnchored(page("Sport 569,000 บาท ... ภายหลัง ... Sport 599,000 บาท"), trims("Sport"), "Toyota", "Yaris");
  ok("two different prices after the same name: ambiguous, nothing observed",
    r.observations.length === 0 && r.ambiguous.length === 1, r);
}
// The same price twice is fine.
{
  const r = extractAnchored(page("Sport 569,000 บาท ... ภายหลัง ... Sport 569,000 บาท"), trims("Sport"), "Toyota", "Yaris");
  ok("the same price repeated is one observation", r.observations.length === 1 && r.observations[0].amount_thb === 569_000, r);
}
// A name that is not on the page.
{
  const r = extractAnchored(page("Smart 599,000 บาท"), trims("Smart", "Sport"), "Toyota", "Yaris");
  ok("a known trim not found is reported, not invented", r.not_found.length === 1 && r.not_found[0].endsWith("sport"), r);
}
// Out-of-range numbers.
{
  const r = extractAnchored(page("Smart 99,000 บาท\nSport 569,000 บาท"), trims("Smart", "Sport"), "Toyota", "Yaris");
  ok("a number under 150,000 is not a list price", priceOf(r, "Smart") === undefined && priceOf(r, "Sport") === 569_000, r);
}
// VAT hint.
{
  const r = extractAnchored(page("Sport ราคา 569,000 บาท ไม่รวม VAT"), trims("Sport"), "Toyota", "Yaris");
  ok("'ไม่รวม VAT' next to the price sets vat_included=false", r.observations[0]?.vat_included === false, r);
  const r2 = extractAnchored(page("Sport ราคา 569,000 บาท"), trims("Sport"), "Toyota", "Yaris");
  ok("no VAT wording leaves it unknown", r2.observations[0]?.vat_included === null, r2);
}
// Model year in the page text must not break matching.
{
  const r = extractAnchored(page("Sport MY2026 569,000 บาท"), trims("Sport"), "Toyota", "Yaris");
  ok("a model-year token does not get in the way", priceOf(r, "Sport") === 569_000, r);
}

// --- validateEvidence: the rule that stops a model inventing a price ---------------------------------------------
{
  const p = page("Premium Luxury\nราคาเริ่มต้น 709,000 บาท\nSmart ราคาเริ่มต้น 599,000 บาท");
  ok("evidence: a real quote validates", validateEvidence(p, { name_raw: "Smart", amount_thb: 599_000, quote: "Smart ราคาเริ่มต้น 599,000 บาท" }));
  ok("evidence: whitespace and case differences are tolerated", validateEvidence(p, { name_raw: "smart", amount_thb: 599_000, quote: "smart  ราคาเริ่มต้น   599,000 บาท" }));
  ok("evidence: an invented amount is refused", !validateEvidence(p, { name_raw: "Smart", amount_thb: 589_000, quote: "Smart ราคาเริ่มต้น 589,000 บาท" }));
  ok("evidence: a quote that is not on the page is refused", !validateEvidence(p, { name_raw: "Smart", amount_thb: 599_000, quote: "Smart now only 599,000 baht" }));
  ok("evidence: the amount must be in the quote", !validateEvidence(p, { name_raw: "Smart", amount_thb: 599_000, quote: "Smart ราคาเริ่มต้น" }));
  ok("evidence: the name must be in the quote", !validateEvidence(p, { name_raw: "Sport", amount_thb: 599_000, quote: "Smart ราคาเริ่มต้น 599,000 บาท" }));
  ok("evidence: an instalment-sized amount is refused", !validateEvidence(page("Smart ผ่อน 7,990 บาท"), { name_raw: "Smart", amount_thb: 7_990, quote: "Smart ผ่อน 7,990 บาท" }));
}

console.log(failed ? `\n${failed} FAILED, ${passed} passed` : `all ${passed} price-extract cases passed`);
process.exit(failed ? 1 : 0);
