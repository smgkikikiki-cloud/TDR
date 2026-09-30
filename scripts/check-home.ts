/** Home page guards (design/GRAFT_PLAN.md PR 5, blocker 11).
 *
 *  1. The catalogue logic (lib/home/catalog-logic.ts) counts and picks exactly what Home says it does.
 *  2. Home never reaches the market engine that is being replaced (blocker 11), the research table (blocker 3), or
 *     car-brand logos (DESIGN §9): no import of, or call to, any of them from app/page.tsx, components/home/ or lib/home/.
 *
 *    node --experimental-strip-types scripts/check-home.ts
 */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { HOME_BODY_CHIPS, bodyFamilyHref, HOME_BRAND_CHIP_LIMIT, pickCompareExamples, priceRange, summarizeCatalog, type HomeModel, type HomeTrim } from "../lib/home/catalog-logic.ts";

let failed = 0;
function check(name: string, got: unknown, want: unknown) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { failed++; console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`); } else console.log(`  ok   ${name}`);
}

const model = (id: string, brand: string, body: string, extra: Partial<HomeModel> = {}): HomeModel => ({
  id, slug: id, name_en: id.toUpperCase(), body_type: body, brands: { slug: brand, name_en: brand.toUpperCase() },
  powertrains: ["ICE"], market_position: "Mass", ...extra,
});
const models: HomeModel[] = [
  model("a1", "toyota", "SEDAN", { retail_price_min: 700000 }), model("a2", "toyota", "CROSSOVER", { retail_price_min: 900000 }),
  model("b1", "honda", "SEDAN", { retail_price_min: 800000 }), model("c1", "byd", "PICKUP"), model("c2", "byd", "VAN"),
  model("d1", "mg", "COUPE"), model("e1", "isuzu", "PICKUP", { retail_price_min: 600000 }),
];
const trims: HomeTrim[] = [
  { model_id: "a1", price_baht: 700000 }, { model_id: "a1", price_baht: 760000 }, { model_id: "a2", price_baht: 900000 },
  { model_id: "b1", price_baht: 800000 }, { model_id: "b1", price_baht: 850000 }, { model_id: "b1", price_baht: 0 },
  { model_id: "c1", price_baht: null },
];
const brands = [{ slug: "toyota", name_en: "Toyota" }, { slug: "honda", name_en: "Honda" }, { slug: "byd", name_en: "BYD" }];

console.log("catalogue summary");
const s = summarizeCatalog(models, brands, trims);
check("model, trim and brand counts", [s.models, s.trims, s.brands], [7, 7, 5]);
check("body-family counts follow DATA_MAP (sedan+coupe+wagon, crossover+ppv+offroad)", s.bodies.map((b) => [b.label, b.count]), [["รถเก๋ง", 3], ["SUV", 1], ["แฮทช์แบ็ก", 0], ["กระบะ", 2], ["MPV", 0], ["รถตู้", 1]]);
const fam = summarizeCatalog([model("w", "x", "WAGON"), model("p", "x", "PPV"), model("o", "x", "OFFROAD"), model("t", "x", "TRUCK"), model("h", "x", "HATCHBACK")], [], []);
check("wagon, ppv and offroad land in their families; TRUCK is in no chip", fam.bodies.map((b) => [b.key, b.count]), [["sedan", 1], ["suv", 2], ["hatchback", 1], ["pickup", 0], ["mpv", 0], ["van", 0]]);
check("family definitions are the approved ones", HOME_BODY_CHIPS.map((c) => [c.label, c.values.join("+")]), [["รถเก๋ง", "SEDAN+COUPE+WAGON"], ["SUV", "CROSSOVER+PPV+OFFROAD"], ["แฮทช์แบ็ก", "HATCHBACK"], ["กระบะ", "PICKUP"], ["MPV", "MPV"], ["รถตู้", "VAN"]]);
check("only one-value families link (/models?body= takes one value)", s.bodies.map((b) => b.href), [null, null, "/models?body=HATCHBACK", "/models?body=PICKUP", "/models?body=MPV", "/models?body=VAN"]);
check("a multi-value family never links to a partial result", bodyFamilyHref(["SEDAN", "COUPE"]), null);
check("brand chips are ordered by current model count, then name", s.brandChips.map((b) => [b.slug, b.count]), [["byd", 2], ["toyota", 2], ["honda", 1], ["isuzu", 1], ["mg", 1]]);
check("brand chip name falls back to the slug", s.brandChips.find((b) => b.slug === "mg")?.name, "mg");
const many = Array.from({ length: 30 }, (_, i) => model(`m${i}`, `brand${String(i).padStart(2, "0")}`, "SEDAN"));
check(`brand chips are capped at ${HOME_BRAND_CHIP_LIMIT}`, summarizeCatalog(many, [], []).brandChips.length, HOME_BRAND_CHIP_LIMIT);

console.log("\ncompare examples");
check("price range ignores zero, null and NaN", priceRange([0, Number.NaN, 760000, 700000]), { min: 700000, max: 760000 });
check("price range of nothing is null", priceRange([]), { min: null, max: null });
const ex = pickCompareExamples(models, trims);
check("two examples from two different brands, each with at least two trims and a price", ex.map((e) => [e.model, e.brand, e.trims, e.min, e.max]), [["A1", "TOYOTA", 2, 700000, 760000], ["B1", "HONDA", 3, 800000, 850000]]);
check("a model with one trim or no price is not an example", ex.some((e) => e.key === "a2" || e.key === "c1"), false);
check("fewer than two eligible models gives fewer examples", pickCompareExamples(models.slice(0, 1), trims).length, 1);
check("no trims, no examples", pickCompareExamples(models, []).length, 0);

console.log("\nblocker guards (no old market engine, no research table, no brand logos on Home)");
const files: string[] = ["app/page.tsx"];
for (const dir of ["components/home", "lib/home"]) for (const f of readdirSync(dir)) if (/\.(ts|tsx)$/.test(f)) files.push(join(dir, f));
const FORBIDDEN_IMPORT = /from\s+["']@\/(?:lib\/(?:home-market|registration-market|public-market|member-market|research|brand-logo-fallback)|components\/(?:HomeMarketLine|charts\/))/;
const FORBIDDEN_CALL = /\b(?:getHomeMarket|getPublicMarket|compareMarketSliceRows|periodTotal|resolveBrandLogo|getPublishedResearchArticles)\s*\(|\blogo_url\b/;
for (const file of files) {
  const src = readFileSync(file, "utf8");
  check(`${file}: no forbidden import`, FORBIDDEN_IMPORT.test(src), false);
  check(`${file}: no forbidden call or logo field`, FORBIDDEN_CALL.test(src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "")), false);
}
console.log("\nproduct-contract guards");
const read = (f: string) => readFileSync(f, "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
const states = read("components/home/states.tsx");
const updating = states.slice(states.indexOf("export function MarketUpdating"), states.indexOf("export function BlockError"));
check("blocked market blocks are not labelled 'coming soon'", /เร็วๆ นี้|kind="soon"|<Flag/.test(updating), false);
check("hero, Top 5 and band market cards use MarketUpdating", ["components/home/HomeHero.tsx", "components/home/InfoSample.tsx", "components/home/IntelligenceBand.tsx"].map((f) => read(f).includes("<MarketUpdating")), [true, true, true]);
const plans = read("components/home/PlansSection.tsx");
check("PlansSection embeds no price, saving or percentage (plan prices live in lib/plans.ts)", /[฿%]|\d,\d{3}/.test(plans), false);
const page = readFileSync("app/page.tsx", "utf8");
check("Home page is wrapped in .designPage (migrated page boundary)", /className="designPage /.test(page), true);

console.log(failed ? `\n${failed} check(s) failed` : "\nall home checks passed");
process.exit(failed ? 1 : 0);
