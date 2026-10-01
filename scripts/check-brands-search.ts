/** Brands and search guards (design/GRAFT_PLAN.md PR 7: P05 /brands, P06 /brands/[slug], P07 search overlay + /search).
 *
 *  1. Brand index: which brands are listed, counts, price range, A–Z grouping, client filter.
 *  2. Search: normalisation, ranking, the old matching contract, suggestion limits, empty-state suggestions.
 *  3. Brand pages share the catalogue explorer: same URL params, brand as a preset, links built on the brand path.
 *  4. Source guards: no car-brand logo, no old market engine, no news block, upcoming left to PR 12, header search present.
 *
 *    node --experimental-strip-types scripts/check-brands-search.ts
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { JUMP_LETTERS, brandKpis, buildBrandIndex, filterBrands, groupByInitial, initialOf } from "../lib/brands/index.ts";
import { BODY_FAMILIES, familyParam } from "../lib/body-families.ts";
import { UPCOMING_CARD_MAX, capUpcoming, noUpcomingSource, safeUpcoming, upcomingSource } from "../lib/upcoming/boundary.ts";
import { PAGE_BRANDS, PAGE_MODELS, QUERY_MAX, SUGGEST_BRANDS, SUGGEST_MODELS, normalizeQuery, popularBrands, searchCatalog } from "../lib/search/catalog.ts";
import { matchesFilters, modelsHref } from "../lib/models/list.ts";

let failed = 0;
function check(name: string, got: unknown, want: unknown) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { failed++; console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`); } else console.log(`  ok   ${name}`);
}

console.log("brand index (P05)");
const brands = [
  { slug: "toyota", name_en: "Toyota" }, { slug: "byd", name_en: "BYD" }, { slug: "audi", name_en: "Audi" }, { slug: "ghost", name_en: "Ghost" },
  { slug: "9x", name_en: "9x" }, { slug: "thai", name_en: null, name_th: "ไทย" },
];
const m = (slug: string, min: number | null, max: number | null = null) => ({ brands: { slug }, retail_price_min: min, retail_price_max: max });
const models = [m("toyota", 700000, 900000), m("toyota", 500000), m("toyota", null), m("byd", 400000, 450000), m("audi", null), m("9x", 1), m("thai", 2)];
const index = buildBrandIndex(brands, models);
check("only brands with a current model are listed (Ghost has none)", index.map((r) => r.slug).includes("ghost"), false);
check("A to Z by name (a Thai-only brand name falls back to its Latin slug, like everywhere else)", index.map((r) => r.name).filter((n) => /^[A-Za-z]/.test(n)), ["Audi", "BYD", "Thai", "Toyota"]);
check("model counts per brand", Object.fromEntries(index.map((r) => [r.slug, r.count])), { "9x": 1, audi: 1, byd: 1, thai: 1, toyota: 3 });
check("price range is the lowest and highest stored price", index.find((r) => r.slug === "toyota") && [index.find((r) => r.slug === "toyota")!.min, index.find((r) => r.slug === "toyota")!.max], [500000, 900000]);
check("a brand with no stored price has no range (never 0)", [index.find((r) => r.slug === "audi")!.min, index.find((r) => r.slug === "audi")!.max], [null, null]);
check("initial letters; digits and Thai go to #", [initialOf("Toyota"), initialOf("byd"), initialOf("9x"), initialOf("ไทย")], ["T", "B", "#", "#"]);
const groups = groupByInitial(index);
check("groups run A to Z with # last", groups.map((g) => g.letter), ["A", "B", "T", "#"]);
check("the jump bar has 26 letters and #", [JUMP_LETTERS.length, JUMP_LETTERS[0], JUMP_LETTERS[25], JUMP_LETTERS[26]], [27, "A", "Z", "#"]);
check("filter is case-insensitive and ignores surrounding space", filterBrands(index, "  toy ").map((r) => r.slug), ["toyota"]);
check("an empty filter keeps every brand", filterBrands(index, "").length, index.length);
check("a filter with no match is empty", filterBrands(index, "zzz"), []);

console.log("\nsearch (P07)");
const sModels = [
  { id: "1", status: "CURRENT", slug: "toyota-yaris", canonical_id: "toyota.yaris", name_en: "Yaris", name_th: "ยาริส", brands: { name_en: "Toyota", slug: "toyota" } },
  { id: "2", status: "CURRENT", slug: "honda-jazz", canonical_id: "honda.jazz", name_en: "Jazz", brands: { name_en: "Honda", slug: "honda" } },
  { id: "3", status: "CURRENT", slug: "byd-seal", canonical_id: "byd.seal", name_en: "Seal", brands: { name_en: "BYD", slug: "byd" } },
  { id: "4", status: "CURRENT", slug: "mg-4", canonical_id: "mg.mg4", name_en: "MG4 Electric", brands: { name_en: "MG", slug: "mg" } },
  { id: "5", status: "CURRENT", slug: "ora-good-cat", canonical_id: "gwm.ora_goodcat", name_en: "Good Cat", brands: { name_en: "ORA", slug: "ora" } },
  { id: "6", status: "CURRENT", slug: "x-eagle", canonical_id: "x.eagle", name_en: "Eagle", brands: { name_en: "X", slug: "x" } },
  { id: "7", status: "CURRENT", slug: "tesla-model-3", canonical_id: "tesla.model3", name_en: "Model 3", brands: { name_en: "Tesla", slug: "tesla" } },
];
const sBrands = [{ slug: "toyota", name_en: "Toyota" }, { slug: "byd", name_en: "BYD" }, { slug: "tesla", name_en: "Tesla" }];
check("query is trimmed, collapsed and capped", [normalizeQuery("  a   b  "), normalizeQuery("x".repeat(500)).length, normalizeQuery(undefined), normalizeQuery(["a"])], ["a b", QUERY_MAX, "", ""]);
check("an empty query finds nothing", searchCatalog(sModels, sBrands, "   "), { q: "", models: [], brands: [] });
check("name match; Thai name match", [searchCatalog(sModels, sBrands, "yaris").models.map((r) => r.id), searchCatalog(sModels, sBrands, "ยาริส").models.map((r) => r.id)], [["1"], ["1"]]);
check("the old contract still holds: slug and canonical_id match", [searchCatalog(sModels, sBrands, "honda-jazz").models.map((r) => r.id), searchCatalog(sModels, sBrands, "ora_goodcat").models.map((r) => r.id)], [["2"], ["5"]]);
check("a name that starts with the query ranks before one that merely contains it", searchCatalog(sModels, sBrands, "ea").models.map((r) => r.id), ["6", "3"]);
check("a word-start match ranks before a mid-word match", searchCatalog(sModels, sBrands, "cat").models.map((r) => r.id), ["5"]);
const ids = (q: string) => searchCatalog(sModels, sBrands, q).models.map((r) => r.id);
check("brand + model phrase: 'Toyota Yaris' finds Yaris; case does not matter", [ids("Toyota Yaris"), ids("toyota yaris"), ids("TOYOTA YARIS")], [["1"], ["1"], ["1"]]);
check("brand + model phrase: a partial phrase still finds it", [ids("toyota yar"), ids("tesla model")], [["1"], ["7"]]);
check("brand + model phrase: the wrong brand does not match", [ids("Honda Yaris"), ids("Toyota Jazz")], [[], []]);
const phraseRows = [
  { id: "a", status: "CURRENT", slug: "a", name_en: "Corolla Cross", brands: { name_en: "Toyota", slug: "toyota" } },
  { id: "b", status: "CURRENT", slug: "b", name_en: "Crosstoyota", brands: { name_en: "Other", slug: "other" } },
  { id: "c", status: "CURRENT", slug: "c", name_en: "Yaris", name_th: "ยาริส", brands: { name_en: "Toyota", name_th: "โตโยต้า", slug: "toyota" } },
];
check("ranking is unchanged: name starts-with 0, word-start / brand+model phrase 1, contains 2", [
  searchCatalog(phraseRows, [], "cross").models.map((r) => r.id), // b starts with it (0), a has a word starting with it (1)
  searchCatalog(phraseRows, [], "toyota").models.map((r) => r.id), // a, c: phrase starts with it (1); b: name contains it (2)
  searchCatalog(phraseRows, [], "oyota").models.map((r) => r.id), // contains only (2): ties fall back to the name
], [["b", "a"], ["a", "c", "b"], ["a", "b", "c"]]);
check("the Thai brand + model phrase is searchable", searchCatalog(phraseRows, [], "โตโยต้า ยาริส").models.map((r) => r.id), ["c"]);
check("brands are searched too", searchCatalog(sModels, sBrands, "te").brands.map((b) => b.slug), ["tesla"]);
const many = Array.from({ length: 40 }, (_, i) => ({ id: String(i), status: "CURRENT", slug: `m${i}`, name_en: `Model ${String(i).padStart(2, "0")}`, brands: { name_en: "B" } }));
check("suggestions are capped at 6 models and 4 brands; the page at 24 and 12", [SUGGEST_MODELS, SUGGEST_BRANDS, PAGE_MODELS, PAGE_BRANDS], [6, 4, 24, 12]);
check("limits are applied", searchCatalog(many, [], "model", { models: SUGGEST_MODELS, brands: SUGGEST_BRANDS }).models.length, 6);
check("popular brands by model count", popularBrands([{ brands: { slug: "a", name_en: "A" } }, { brands: { slug: "b", name_en: "B" } }, { brands: { slug: "b", name_en: "B" } }], 2).map((b) => [b.slug, b.count]), [["b", 2], ["a", 1]]);

console.log("\nbrand page shares the explorer params (P06)");
check("a brand page builds its links on its own path", modelsHref({ body: "PICKUP", sort: "name" }, { page: "2" }, "/brands/toyota"), "/brands/toyota?body=PICKUP&sort=name&page=2");
check("clearing on a brand page returns to the brand page", modelsHref({}, {}, "/brands/toyota"), "/brands/toyota");
check("the default base path is still /models", modelsHref({ body: "VAN" }, {}), "/models?body=VAN");
check("the brand preset filters like the brand filter did", [{ brands: { slug: "toyota" }, body_type: "PICKUP" }, { brands: { slug: "byd" }, body_type: "PICKUP" }].filter((r) => matchesFilters(r as any, { brand: "toyota", body: "PICKUP" })).length, 1);

console.log("\nbrand KPIs (P06)");
const bModels = [
  { id: "t1", brands: { slug: "toyota" }, retail_price_min: 700000, retail_price_max: 900000 },
  { id: "t2", brands: { slug: "toyota" }, retail_price_min: 500000, retail_price_max: null },
  { id: "t3", brands: { slug: "toyota" }, retail_price_min: null, retail_price_max: null },
];
const counts = new Map([["t1", 3], ["t2", 2], ["other-brand-model", 9]]);
check("รุ่นที่จำหน่าย = the brand's current models", brandKpis(bModels, counts).models, 3);
check("รุ่นย่อย = CURRENT trims of those models only (another brand's trims never count)", brandKpis(bModels, counts).trims, 5);
check("ช่วงราคา = lowest and highest stored retail price", [brandKpis(bModels, counts).min, brandKpis(bModels, counts).max], [500000, 900000]);
check("no stored price means no range, never a made-up one", (({ min, max }) => [min, max])(brandKpis([bModels[2]], counts)), [null, null]);
check("no models means zero models and trims", (({ models, trims }) => [models, trims])(brandKpis([], counts)), [0, 0]);

console.log("\nnon-Latin brand names");
const thaiOnly = buildBrandIndex([{ slug: "บีวายดี", name_th: "บีวายดี", name_en: null }], [{ brands: { slug: "บีวายดี" } }]);
check("a name with no Latin form is kept as written (never transliterated) and grouped under #", [thaiOnly[0].name, initialOf(thaiOnly[0].name)], ["บีวายดี", "#"]);
check("# sorts after A–Z, deterministically", groupByInitial(buildBrandIndex([{ slug: "toyota", name_en: "Toyota" }, { slug: "บีวายดี", name_th: "บีวายดี" }], [{ brands: { slug: "toyota" } }, { brands: { slug: "บีวายดี" } }])).map((g) => g.letter), ["T", "#"]);

console.log("\nbrand + body family URLs");
const sedan = BODY_FAMILIES[0];
check("a brand family link uses the PR 6 encoding", modelsHref({ brand: "toyota", body: familyParam(sedan) }, {}), "/models?brand=toyota&body=SEDAN%2CCOUPE%2CWAGON");
check("a single-value family keeps the old single value", modelsHref({ brand: "toyota", body: familyParam(BODY_FAMILIES[2]) }, {}), "/models?brand=toyota&body=PICKUP");
check("the brand preset + family filter selects the brand's family models", [{ brands: { slug: "toyota" }, body_type: "COUPE" }, { brands: { slug: "toyota" }, body_type: "PICKUP" }, { brands: { slug: "byd" }, body_type: "SEDAN" }].filter((r) => matchesFilters(r as any, { brand: "toyota", body: familyParam(sedan) })).length, 1);

console.log("\nsearch: current identities only, URLs");
const lifecycle = [
  { id: "c", slug: "toyota-camry", name_en: "Camry", status: "CURRENT", brands: { slug: "toyota", name_en: "Toyota" } },
  { id: "h", slug: "toyota-corolla-old", name_en: "Corolla Old", status: "HISTORICAL", brands: { slug: "toyota", name_en: "Toyota" } },
  { id: "u", slug: "toyota-concept", name_en: "Concept", status: "UNVERIFIED", brands: { slug: "toyota", name_en: "Toyota" } },
  { id: "g", slug: "ghost-only", name_en: "Ghost Only", status: "HISTORICAL", brands: { slug: "ghost", name_en: "Ghost" } },
];
const lifeBrands = [{ slug: "toyota", name_en: "Toyota" }, { slug: "ghost", name_en: "Ghost" }];
check("HISTORICAL and UNVERIFIED models never appear in results", searchCatalog(lifecycle, lifeBrands, "toyota").models.map((r) => r.id), ["c"]);
check("a brand with no current model cannot be found", searchCatalog(lifecycle, lifeBrands, "ghost").brands.map((b) => b.slug), []);
check("a brand with a current model can", searchCatalog(lifecycle, lifeBrands, "toy").brands.map((b) => b.slug), ["toyota"]);
check("the search URL encodes Thai, spaces and &", [`/search?q=${encodeURIComponent("ยาริส")}`, `/search?q=${encodeURIComponent("a b&c")}`], ["/search?q=%E0%B8%A2%E0%B8%B2%E0%B8%A3%E0%B8%B4%E0%B8%AA", "/search?q=a%20b%26c"]);

console.log("\nUpcoming boundary (PR 12 owns the source)");
check("while PR 12 is absent the source returns no rows, so the strip and the group are omitted", [await upcomingSource.forBrand({ slug: "toyota", name: "Toyota" }, 3), await upcomingSource.matching("x", 3)], [[], []]);
check("the active source is the empty one", upcomingSource === noUpcomingSource, true);
check("a strip never exceeds 3 cards", [UPCOMING_CARD_MAX, capUpcoming(Array.from({ length: 5 }, (_, i) => ({ slug: `s${i}` }) as any)).length], [3, 3]);
check("a failing source omits the strip instead of failing the page", await safeUpcoming(async () => { throw new Error("down"); }), []);

console.log("\nsource guards");
const files: string[] = [];
const walk = (dir: string) => { for (const f of readdirSync(dir)) { const p = join(dir, f); if (statSync(p).isDirectory()) walk(p); else if (/\.(ts|tsx|css)$/.test(f)) files.push(p); } };
for (const dir of ["app/brands", "app/search", "app/api/search", "components/brands", "components/search", "components/upcoming", "lib/brands", "lib/search", "lib/upcoming"]) walk(dir);
files.push("components/Header.tsx", "components/models/ModelsExplorer.tsx");
const strip = (src: string) => src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
const MARKET = /(?:registration-market|public-market|home-market|member-market|getPublicMarket|compareMarketSliceRows|periodTotal|HomeMarketLine|getModelMarketTeasers)/;
const LOGO = /(?:logo_url|resolveBrandLogo|brand-logo-fallback|\binitials\()/;
for (const f of files) {
  const src = strip(readFileSync(f, "utf8"));
  check(`${f}: no old market engine`, MARKET.test(src), false);
  check(`${f}: no car-brand logo`, LOGO.test(src), false);
}
const brandPage = readFileSync("app/brands/[slug]/page.tsx", "utf8");
check("a brand page renders the shared ModelsExplorer with the brand as a preset", /<ModelsExplorer[^>]*fixedBrand=/.test(brandPage) && /basePath=\{`\/brands\/\$\{slug\}`\}/.test(brandPage), true);
check("/models renders the same explorer", /<ModelsExplorer/.test(readFileSync("app/models/page.tsx", "utf8")), true);
check("an unknown brand is a real 404 (looked up before the Suspense boundary)", brandPage.indexOf("notFound()") !== -1 && brandPage.indexOf("notFound()") < brandPage.indexOf("<Suspense"), true);
check("the brand page has no news block", /getRelatedEvents|sfNewsList|\/news/.test(strip(brandPage)), false);
check("upcoming (PR 12) is not queried on the brand page or on /search", /upcoming_vehicles|getUpcoming/.test(strip(brandPage) + strip(readFileSync("app/search/page.tsx", "utf8"))), false);
check("the header carries the search overlay", /<SearchOverlay \/>/.test(readFileSync("components/Header.tsx", "utf8")), true);
const overlay = readFileSync("components/search/SearchOverlay.tsx", "utf8");
check("the overlay is a modal dialog with Escape, a focus trap and focus return", /aria-modal="true"/.test(overlay) && /"Escape"/.test(overlay) && /trap/.test(overlay) && /openerRef\.current\?\.focus\(\)/.test(overlay), true);
check("the overlay cancels stale suggestion requests", /AbortController/.test(overlay) && /controller\.abort\(\)/.test(overlay), true);
const route = readFileSync("app/api/search/suggest/route.ts", "utf8");
check("the suggest route caps the query and the result sizes", /normalizeQuery/.test(route) && /SUGGEST_MODELS/.test(route) && /SUGGEST_BRANDS/.test(route), true);
check("the suggest route runs the shared searchCatalog, which keeps CURRENT models only", /searchCatalog\(/.test(route) && /isCurrentLifecycleStatus/.test(readFileSync("lib/search/catalog.ts", "utf8")), true);
check("searchCanonicalCatalog delegates to the same searchCatalog (one algorithm)", /searchCatalog\(models/.test(readFileSync("lib/canonical-data.ts", "utf8")), true);
check("/search reads results through searchCanonicalCatalog", /searchCanonicalCatalog\(/.test(readFileSync("app/search/page.tsx", "utf8")), true);
check("no Supabase client is imported in browser code for brands or search", /supabase|publicDb|adminDb|service/i.test(["components/brands/BrandIndex.tsx", "components/search/SearchOverlay.tsx"].map((f) => strip(readFileSync(f, "utf8"))).join("\n")), false);
check("overlay and page build /search?q= with encodeURIComponent", (strip(readFileSync("components/search/SearchOverlay.tsx", "utf8")).match(/\/search\?q=\$\{encodeURIComponent/g) || []).length >= 2 && /\/search\?q=\$\{encodeURIComponent/.test(strip(readFileSync("app/search/page.tsx", "utf8"))), true);
check("the brand page opens the catalogue from its family tiles (tilesToCatalogue)", /tilesToCatalogue/.test(brandPage), true);
check("pages go through the Upcoming boundary and never write a car themselves", /upcomingSource\./.test(brandPage) && /upcomingSource\./.test(readFileSync("app/search/page.tsx", "utf8")) && !/nameProvisional: (true|false)|windowText: "/.test(brandPage + readFileSync("app/search/page.tsx", "utf8")), true);
check("the Upcoming card draws nothing without rows", /if \(!rows\.length\) return null/.test(readFileSync("components/upcoming/UpcomingCards.tsx", "utf8")), true);
check("the search page H1 is ผลการค้นหา \"q\" (straight quotes)", /`ผลการค้นหา "\$\{q\}"`/.test(readFileSync("app/search/page.tsx", "utf8")), true);
check("the suggest route never uses a service role", /service_role|SERVICE_ROLE|adminDb/i.test(route), false);

console.log("\nheader at small phones (360 regression)");
const shell = readFileSync("app/shell.css", "utf8");
check("header compaction guard: <=400px shrinks the logo and tightens the controls", /@media \(max-width: 400px\)[^{]*\{[^@]*?\.tdr-logo img \{ height: 26px/.test(shell), true);
check("Sign up / drawer guard: <=340px hides the header Sign up (the drawer still carries it)", /@media \(max-width: 340px\)[^{]*\{[^@]*?\.tdr-signup \{ display: none/.test(shell) && /tdr-signup/.test(readFileSync("components/MobileNav.tsx", "utf8")), true);
check("right-alignment guard: the phone header keeps its controls on the right edge (nav + acts rule overridden)", /\.tdr-nav \+ \.tdr-acts \{ margin-left: auto; \}/.test(shell), true);

console.log(failed ? `\n${failed} check(s) failed` : "\nall brands and search checks passed");
process.exit(failed ? 1 : 0);
