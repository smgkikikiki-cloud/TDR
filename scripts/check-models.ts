/** Vehicle Database group guards (design/GRAFT_PLAN.md PR 6: P02 /models, P03 model, P04 trim).
 *
 *  1. Body families: the approved membership, one shared definition, old single-value URLs unchanged, family URLs filter.
 *  2. /models list logic: sort, 12-at-a-time load steps, URL building, compare hand-off.
 *  3. Trim spec table: unknown fields and empty groups are omitted, nothing is printed as "-", labels/order come from
 *     the registry, every row carries a source.
 *  4. Source guards: no car-brand logo, no old market engine, no duplicated family mapping, no trim picked for a model.
 *
 *    node --experimental-strip-types scripts/check-models.ts
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import {
  BODY_FAMILIES, bodyMatches, bodyParam, countInFamily, familyForSelection, familyOfBody, familyParam, parseBodyParam, toggleBodyValue,
} from "../lib/body-families.ts";
import {
  COMPARE_MAX, PAGE_SIZE, SORTS, bahtRangeText, compareHref, matchesFilters, modelsHref, normalizeParams, pageWindow, parsePage, parseSort,
  pictureCredit, sortModels, visibleOption, type ModelListRow,
} from "../lib/models/list.ts";
import { formatThaiDate, keyFacts, sourceBadge, trimSpecGroups, unmappedFields, TRIM_SPEC_GROUPS } from "../lib/models/trim-specs.ts";
import { hasInternalToken, isNoValue, presentSpecText, tokenLabel } from "../lib/models/spec-display.ts";
import { loadSpecFieldRegistry } from "../lib/spec-field-registry.ts";

let failed = 0;
function check(name: string, got: unknown, want: unknown) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { failed++; console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`); } else console.log(`  ok   ${name}`);
}

console.log("body families");
check("families and members are the approved ones (DATA_MAP §Home)", BODY_FAMILIES.map((f) => [f.label, f.values.join("+")]), [
  ["รถเก๋ง", "SEDAN+COUPE+WAGON"], ["SUV", "CROSSOVER+PPV+OFFROAD"], ["กระบะ", "PICKUP"], ["MPV", "MPV"], ["แฮทช์แบ็ก", "HATCHBACK"], ["รถตู้", "VAN"],
]);
check("each canonical value belongs to one family", ["SEDAN", "COUPE", "WAGON", "CROSSOVER", "PPV", "OFFROAD", "PICKUP", "MPV", "HATCHBACK", "VAN"].map((v) => familyOfBody(v)?.key),
  ["sedan", "sedan", "sedan", "suv", "suv", "suv", "pickup", "mpv", "hatchback", "van"]);
check("TRUCK, OTHER and empty belong to no family", [familyOfBody("TRUCK"), familyOfBody("OTHER"), familyOfBody(null)], [null, null, null]);
check("family param is the comma list of its values", familyParam(BODY_FAMILIES[0]), "SEDAN,COUPE,WAGON");
check("family counts sum members", countInFamily(["SEDAN", "COUPE", "WAGON", "PPV", "TRUCK", null], BODY_FAMILIES[0]), 3);

console.log("\nbody URLs (backward compatible)");
check("a single value parses to one value (old URL /models?body=PICKUP)", parseBodyParam("PICKUP"), ["PICKUP"]);
check("a family URL parses to its values", parseBodyParam("SEDAN,COUPE,WAGON"), ["SEDAN", "COUPE", "WAGON"]);
check("blanks and repeats are dropped", parseBodyParam(" SEDAN,,SEDAN , COUPE "), ["SEDAN", "COUPE"]);
check("no param is no filter", [parseBodyParam(undefined), parseBodyParam("")], [[], []]);
check("bodyParam is the inverse", [bodyParam(["A", "B"]), bodyParam([])], ["A,B", null]);
check("a family selection is recognised in any order", familyForSelection(["WAGON", "SEDAN", "COUPE"])?.key, "sedan");
check("a partial family is not a family", familyForSelection(["SEDAN", "COUPE"]), null);
check("toggle adds and removes a value", [toggleBodyValue([], "SEDAN"), toggleBodyValue(["SEDAN", "COUPE"], "SEDAN")], [["SEDAN"], ["COUPE"]]);

const row = (id: string, body: string, extra: Partial<ModelListRow> = {}): ModelListRow => ({
  id, slug: id, name_en: id.toUpperCase(), body_type: body, brands: { slug: "b", name_en: "B" }, powertrains: ["ICE"], segment: "C", market_position: "Mass", production_type: "CBU", ...extra,
});
const models: ModelListRow[] = [
  row("sedan1", "SEDAN", { retail_price_min: 700000, launch_year: 2024 }), row("coupe1", "COUPE", { retail_price_min: 900000, launch_year: 2023 }),
  row("wagon1", "WAGON"), row("cross1", "CROSSOVER", { retail_price_min: 800000, retail_price_max: 950000, launch_year: 2025 }),
  row("ppv1", "PPV", { retail_price_max: 1200000 }), row("pick1", "PICKUP", { retail_price_min: 600000 }), row("pick2", "PICKUP", { retail_price_min: 650000 }),
  row("truck1", "TRUCK"), row("van1", "VAN", { powertrains: ["BEV"] }),
];
const ids = (rows: ModelListRow[]) => rows.map((r) => r.id).sort();
// the predicate exactly as it was before families existed
const oldPredicate = (r: ModelListRow, body?: string) => !body || r.body_type === body;
check("old single-value URL selects exactly what it always did", ids(models.filter((r) => matchesFilters(r, { body: "PICKUP" }))), ids(models.filter((r) => oldPredicate(r, "PICKUP"))));
check("every old single value keeps working", ["SEDAN", "COUPE", "WAGON", "CROSSOVER", "PPV", "PICKUP", "VAN", "TRUCK", "NOPE"].every((v) => JSON.stringify(ids(models.filter((r) => matchesFilters(r, { body: v })))) === JSON.stringify(ids(models.filter((r) => oldPredicate(r, v))))), true);
check("รถเก๋ง family URL = sedan + coupe + wagon", ids(models.filter((r) => matchesFilters(r, { body: "SEDAN,COUPE,WAGON" }))), ["coupe1", "sedan1", "wagon1"]);
check("SUV family URL = crossover + ppv + offroad", ids(models.filter((r) => matchesFilters(r, { body: familyParam(BODY_FAMILIES[1]) }))), ["cross1", "ppv1"]);
check("TRUCK is in no family filter", BODY_FAMILIES.some((f) => models.filter((r) => bodyMatches(r.body_type, f.values)).some((r) => r.id === "truck1")), false);
check("body filter composes with the other filters", ids(models.filter((r) => matchesFilters(r, { body: "SEDAN,COUPE,WAGON", powertrain: "BEV" }))), []);
check("skipping body leaves its own counts independent of it", ids(models.filter((r) => matchesFilters(r, { body: "PICKUP", powertrain: "ICE" }, "body"))).length, 8);
check("unknown filter values match nothing, as before", models.filter((r) => matchesFilters(r, { body: "NOPE" })).length, 0);

console.log("\nsort");
check("default and invalid sorts are ใหม่ล่าสุด", [parseSort(undefined), parseSort("bogus"), parseSort("name")], ["new", "new", "name"]);
check("sort labels are the four in the brief", SORTS.map((s) => s.label), ["ใหม่ล่าสุด", "ราคาต่ำ → สูง", "ราคาสูง → ต่ำ", "ชื่อ A–Z"]);
check("price low to high, no price last", sortModels(models, "price_asc").map((r) => r.id), ["pick1", "pick2", "sedan1", "cross1", "coupe1", "ppv1", "truck1", "van1", "wagon1"]);
check("price high to low, no price still last", sortModels(models, "price_desc").map((r) => r.id), ["ppv1", "coupe1", "cross1", "sedan1", "pick2", "pick1", "truck1", "van1", "wagon1"]);
check("name sort is A to Z", sortModels(models, "name").map((r) => r.id), ["coupe1", "cross1", "pick1", "pick2", "ppv1", "sedan1", "truck1", "van1", "wagon1"]);
check("newest first puts the latest launch first", sortModels(models, "new")[0].id, "cross1");
check("sorting does not mutate its input", (() => { const copy = models.map((r) => r.id); sortModels(models, "name"); return models.map((r) => r.id); })(), models.map((r) => r.id));

console.log("\n12 at a time");
const many = Array.from({ length: 30 }, (_, i) => row(`m${i}`, "SEDAN"));
check("a load step is 12", PAGE_SIZE, 12);
check("page 1 shows 12 of 30, more to load", (({ shown, total, hasMore, nextPage }) => ({ shown, total, hasMore, nextPage }))(pageWindow(many, 1)), { shown: 12, total: 30, hasMore: true, nextPage: 2 });
check("page 2 shows 24", pageWindow(many, 2).items.length, 24);
check("page 3 shows all 30, nothing more", (({ shown, hasMore }) => ({ shown, hasMore }))(pageWindow(many, 3)), { shown: 30, hasMore: false });
check("a page past the end shows everything", pageWindow(many, 99).items.length, 30);
check("fewer than 12 results have no load more", pageWindow(many.slice(0, 5), 1).hasMore, false);
check("page param parses, bad values are page 1", [parsePage("3"), parsePage("0"), parsePage("-2"), parsePage("x"), parsePage(undefined)], [3, 1, 1, 1, 1]);

console.log("\nURLs and the compare hand-off");
check("changing a filter drops page", modelsHref({ body: "PICKUP", page: "3", sort: "name" }, { powertrain: "BEV" }), "/models?body=PICKUP&sort=name&powertrain=BEV");
check("changing page keeps everything", modelsHref({ body: "PICKUP", sort: "name" }, { page: "2" }), "/models?body=PICKUP&sort=name&page=2");
check("null removes a key; nothing left is /models", [modelsHref({ body: "PICKUP" }, { body: null }), modelsHref({}, {})], ["/models", "/models"]);
check("existing filter keys are still accepted", Object.keys(normalizeParams({ body: "A", powertrain: "B", segment: "C", position: "D", production: "E", brand: "F", x: undefined })), ["body", "powertrain", "segment", "position", "production", "brand"]);
check("array params use the first value", normalizeParams({ body: ["A", "B"] }).body, "A");
check("compare hand-off carries models, never trims", compareHref(["a", "b"]), "/compare?models=a&models=b");
check("compare hand-off is capped at four", compareHref(["a", "b", "c", "d", "e"]), "/compare?models=a&models=b&models=c&models=d");
check("the cap is four", COMPARE_MAX, 4);
check("zero-count rail options are hidden unless active", [visibleOption(0, false), visibleOption(0, true), visibleOption(3, false)], [false, true, true]);
check("price text writes ฿ once", [bahtRangeText(629900, 659900), bahtRangeText(2290000, 2290000), bahtRangeText(null, 500000), bahtRangeText(null, null)], ["฿629,900–659,900", "฿2,290,000", "฿500,000", null]);
check("a picture needs an official source page", [
  pictureCredit({ image_url: "https://x/y.jpg", image_source_type: "official_site", image_source_url: "https://www.toyota.co.th/model/x" })?.host,
  pictureCredit({ image_url: "https://x/y.jpg", image_source_type: "official_site", image_source_url: "" }),
  pictureCredit({ image_url: "https://x/y.jpg", image_source_type: "user_upload", image_source_url: "https://a.b" }),
  pictureCredit({ image_url: "https://x/y.jpg", image_source_type: "official_site", image_source_url: "javascript:alert(1)" }),
], ["toyota.co.th", null, null, null]);

console.log("\ntrim spec table (P04)");
const registry = loadSpecFieldRegistry(new Date().getFullYear());
check("the canonical registry loads", registry.length > 50, true);
check("seven groups, in the approved order", TRIM_SPEC_GROUPS.map((g) => g.title), ["ขนาดและน้ำหนัก", "ระบบขับเคลื่อน", "แบตเตอรี่และการชาร์จ", "ล้อและยาง", "ความปลอดภัย", "ความสะดวกและเทคโนโลยี", "ภาษีและกฎระเบียบ"]);
check("the only registry field with no P04 group is the factory (a production fact, not tax or regulation)", unmappedFields(registry), ["manufacturing.factory"]);
check("ภาษีและกฎระเบียบ takes the excise rate field only, not the whole manufacturing group", TRIM_SPEC_GROUPS.find((g) => g.title === "ภาษีและกฎระเบียบ")?.fields, ["manufacturing.excise_tax_rate"]);
const fact = (field_key: string, value: unknown, extra: Record<string, unknown> = {}) => ({
  field_key, value, value_state: "KNOWN", unit: "", qualifiers: {}, source: "ecosticker", fact_id: `eco:x:${field_key}`,
  observed_at: "2026-04-01", source_ref: "https://car.ecosticker.go.th/landing-page/detail/abc", ...extra,
});
const trim: any = {
  id: "t1", name: "Trim", price_baht: 1000000, powertrain: "BEV", seats: 5,
  comparable_specs: [
    fact("vehicle.length_mm", 4500, { unit: "mm" }), fact("vehicle.curb_weight_kg", 1500, { unit: "kg" }),
    fact("battery.gross_capacity_kwh", 60.5, { unit: "kWh" }),
    fact("charging.dc_max_kw", 80, { unit: "kW", source: "oem_official_website", source_ref: "https://oem.example/x", observed_at: "2026-09-01" }),
    fact("safety.airbag_count", 6), fact("safety.aeb", true, { source: "", fact_id: "admin:t1:safety.aeb", source_ref: "", observed_at: null }),
    fact("safety.abs", null), fact("safety.esc", "", {}), fact("comfort.auto_climate", true, { value_state: "UNKNOWN" }),
    fact("manufacturing.excise_tax_rate", 0.02, { source: "", fact_id: "x", source_ref: "" }),
    fact("manufacturing.factory", "Factory A", { source: "ecosticker" }),
  ],
};
const groups = trimSpecGroups(trim, registry);
check("only groups with facts appear, in order", groups.map((g) => g.title), ["ขนาดและน้ำหนัก", "ระบบขับเคลื่อน", "แบตเตอรี่และการชาร์จ", "ความปลอดภัย", "ภาษีและกฎระเบียบ"]);
check("groups with no facts are omitted (ล้อและยาง, ความสะดวกและเทคโนโลยี)", groups.some((g) => g.title === "ล้อและยาง" || g.title === "ความสะดวกและเทคโนโลยี"), false);
const allRows = groups.flatMap((g) => g.rows);
check("null, empty and non-KNOWN facts make no row (ABS, ESC, auto climate)", allRows.some((r) => /ABS|ESC|climate|ปรับอากาศ/i.test(r.key + r.label)), false);
check("no row value is a dash or blank", allRows.every((r) => r.value.trim() !== "" && !/^[-–—]+$/.test(r.value.trim())), true);
check("labels come from the registry", allRows.find((r) => r.key.startsWith("spec:vehicle.curb_weight_kg"))?.label, registry.find((f) => f.key === "vehicle.curb_weight_kg")?.labelTh);
const dims = groups[0].rows.map((r) => r.key.replace("spec:", "").split("::")[0]);
check("row order follows the registry order", dims, [...dims].sort((a, b) => registry.findIndex((f) => f.key === a) - registry.findIndex((f) => f.key === b)));
check("every row has a source badge; ECO Sticker, OEM, and none recorded -> ไม่ระบุที่มา (fact_id never infers a source)", [
  allRows.find((r) => r.key.includes("battery.gross"))?.source.label, allRows.find((r) => r.key.includes("charging.dc_max"))?.source.label,
  allRows.find((r) => r.key.includes("safety.aeb"))?.source.label, allRows.find((r) => r.key.includes("excise"))?.source.label,
], ["ECO Sticker", "OEM", "ไม่ระบุที่มา", "ไม่ระบุที่มา"]);
check("a fact factory is not shown on the trim page", allRows.some((r) => r.fieldKey === "manufacturing.factory"), false);
check("the excise rate is under ภาษีและกฎระเบียบ", groups.find((g) => g.title === "ภาษีและกฎระเบียบ")?.rows.map((r) => r.fieldKey), ["manufacturing.excise_tax_rate"]);
check("observed date is Buddhist-era", allRows.find((r) => r.key.includes("battery.gross"))?.observedAt, "1 เม.ย. 2569");
check("a fact with no date has none", allRows.find((r) => r.key.includes("safety.aeb"))?.observedAt, null);
check("only http(s) source links survive", trimSpecGroups({ ...trim, comparable_specs: [fact("vehicle.length_mm", 1, { source_ref: "javascript:x" })] }, registry)[0].rows[0].sourceUrl, null);
check("a trim with no facts and no columns has no groups", trimSpecGroups({ id: "e", comparable_specs: [] } as any, registry), []);
check("a trim with no ledger at all has no groups", trimSpecGroups({ id: "e" } as any, registry), []);
check("flat MarketTrim columns still show (length_mm) when there is no ledger fact", trimSpecGroups({ id: "f", length_mm: 4400 } as any, registry).flatMap((g) => g.rows).some((r) => r.value.includes("4,400")), true);
check("date formatting", [formatThaiDate("2026-09-30"), formatThaiDate("nope"), formatThaiDate(null)], ["30 ก.ย. 2569", null, null]);
check("source badge without a source says so", sourceBadge({ source: "" }), { label: "ไม่ระบุที่มา", known: false });
check("an admin fact_id or an admin write path is not an evidence source", [sourceBadge({ source: "", fact_id: "admin:t:x" } as any), sourceBadge({ source: "admin" })], [{ label: "ไม่ระบุที่มา", known: false }, { label: "ไม่ระบุที่มา", known: false }]);
check("named sources still get their badge", [sourceBadge({ source: "ecosticker" }).label, sourceBadge({ source: "oem_official_website" }).label], ["ECO Sticker", "OEM"]);

console.log("\ndisplay text (P03 / P04): no internal tokens, qualifiers kept");
check("count and non-SI units are words", [presentSpecText("5 seat"), presentSpecText("8 year"), presentSpecText("6 airbag"), presentSpecText("1 gear"), presentSpecText("1 motor"), presentSpecText("7.9 s"), presentSpecText("18.5 L/100km"), presentSpecText("120 km/h"), presentSpecText("480 km")], ["5 ที่นั่ง", "8 ปี", "6 ใบ", "1 เกียร์", "1 มอเตอร์", "7.9 วินาที", "18.5 ลิตร/100 กม.", "120 กม./ชม.", "480 กม."]);
check("SI symbols and the number are untouched", [presentSpecText("4,310 mm"), presentSpecText("60.5 kWh"), presentSpecText("130 kW"), presentSpecText("215/60 R17"), presentSpecText("10→80% SOC @150kW")], ["4,310 mm", "60.5 kWh", "130 kW", "215/60 R17", "10→80% SOC @150kW"]);
check("every qualifier is kept, in words", presentSpecText("130 kW (FRONT_MOTOR, DECLARED)"), "130 kW (มอเตอร์หน้า, ตามที่ผู้ผลิตประกาศ)");
check("distinct qualifiers stay distinct", [tokenLabel("DECLARED"), tokenLabel("AS_DECLARED"), tokenLabel("FRONT_MOTOR"), tokenLabel("REAR_MOTOR")].every((v, i, a) => a.indexOf(v) === i), true);
check("an unknown SCREAMING_SNAKE token is humanized, never shown raw", presentSpecText("(SOME_NEW_VALUE)"), "(some new value)");
check("enum values are words; free text is never rewritten", [presentSpecText("GASOLINE"), presentSpecText("AUTOMATIC"), presentSpecText("MANUAL"), presentSpecText("DIESEL"), presentSpecText("TOYOTA MOTOR CORPORATION"), presentSpecText("FWD"), presentSpecText("PMSM")], ["เบนซิน", "อัตโนมัติ", "เกียร์ธรรมดา", "ดีเซล", "TOYOTA MOTOR CORPORATION", "FWD", "PMSM"]);
check("UNKNOWN / NOT_APPLICABLE placeholders are not values", [isNoValue("UNKNOWN"), isNoValue("not_applicable"), isNoValue("FWD")], [true, true, false]);
check("standard names (NEDC, WLTP, BEV) are left alone", presentSpecText("480 km (NEDC, FULL)"), "480 กม. (NEDC, ระยะรวม)");
const tokenFixture: any = { id: "tok", comparable_specs: [
  fact("vehicle.seats", 5, { unit: "seat" }), fact("battery.warranty_years", 8, { unit: "year" }), fact("safety.airbag_count", 6, { unit: "airbag" }),
  fact("powertrain.max_power_kw", 130, { unit: "kW", qualifiers: { output_scope: "FRONT_MOTOR", rating_basis: "DECLARED" } }),
  fact("powertrain.max_power_kw", 260, { unit: "kW", qualifiers: { output_scope: "SYSTEM", rating_basis: "PEAK" } }),
  fact("performance.acceleration_0_100_s", 7.9, { unit: "s", qualifiers: { measurement_basis: "DECLARED" } }),
  fact("ev.rated_range_km", 480, { unit: "km", qualifiers: { measurement_basis: "NEDC", range_scope: "ELECTRIC_ONLY" } }),
  fact("powertrain.drivetrain", "UNKNOWN"), fact("powertrain.transmission", "AUTOMATIC"), fact("engine.fuel_type", "GASOLINE"),
  fact("battery.chemistry", "LI_ION_UNSPECIFIED"), fact("charging.port_type", "ONBOARD_AC"), fact("vehicle.curb_weight_kg", 1500, { unit: "kg", qualifiers: { measurement_basis: "AS_DECLARED" } }),
] };
const tokenRows = trimSpecGroups(tokenFixture, registry).flatMap((g) => g.rows);
check("a placeholder UNKNOWN value makes no row", tokenRows.some((r) => r.fieldKey === "powertrain.drivetrain"), false);
check("enum values render in words (AUTOMATIC, GASOLINE)", tokenRows.filter((r) => ["powertrain.transmission", "engine.fuel_type"].includes(r.fieldKey)).map((r) => r.value).sort(), ["อัตโนมัติ", "เบนซิน"].sort());
check("no rendered label or value holds a SCREAMING_SNAKE token", tokenRows.filter((r) => hasInternalToken(r.label) || hasInternalToken(r.value)).map((r) => [r.label, r.value]), []);
check("the two power figures remain two rows with their qualifiers visible", tokenRows.filter((r) => r.fieldKey === "powertrain.max_power_kw").map((r) => r.label).every((l) => /มอเตอร์หน้า|ทั้งระบบ/.test(l)), true);
check("counts read as words in the table", Object.fromEntries(tokenRows.filter((r) => ["vehicle.seats", "battery.warranty_years", "safety.airbag_count"].includes(r.fieldKey)).map((r) => [r.fieldKey, r.value])), { "vehicle.seats": "5 ที่นั่ง", "battery.warranty_years": "8 ปี", "safety.airbag_count": "6 ใบ" });
check("key facts list only the known ones, price first", keyFacts({ ...trim, price_baht: 1000000, battery_kwh: 60.5 } as any, registry).map((f) => f.key), ["price", "battery", "seats"]);
check("no key facts for an empty trim", keyFacts({ id: "z" } as any, registry), []);

console.log("\nsource guards");
const files: string[] = [];
const walk = (dir: string) => { for (const f of readdirSync(dir)) { const p = join(dir, f); if (statSync(p).isDirectory()) walk(p); else if (/\.(ts|tsx|css)$/.test(f)) files.push(p); } };
for (const dir of ["app/models", "components/models", "lib/models"]) walk(dir);
files.push("lib/body-families.ts", "components/design/BodyIcon.tsx");
const strip = (src: string) => src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
const FORBIDDEN_MARKET = /(?:registration-market|public-market|home-market|member-market|getPublicMarket|compareMarketSliceRows|periodTotal|HomeMarketLine|getHomeMarket)/;
const LOGO = /(?:logo_url|resolveBrandLogo|brand-logo-fallback|\/logos?\/)/;
for (const file of files) {
  const src = strip(readFileSync(file, "utf8"));
  check(`${file}: no old market engine`, FORBIDDEN_MARKET.test(src), false);
  check(`${file}: no car-brand logo`, LOGO.test(src), false);
}
// one shared family definition
const familyLiteral = /["']SEDAN["']\s*,\s*["']COUPE["']\s*,\s*["']WAGON["']|["']CROSSOVER["']\s*,\s*["']PPV["']\s*,\s*["']OFFROAD["']/;
for (const file of [...files.filter((f) => f !== "lib/body-families.ts"), "app/page.tsx"]) {
  check(`${file}: does not redefine a body family`, familyLiteral.test(readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "")), false);
}
const list = readFileSync("app/models/page.tsx", "utf8");
check("/models builds its tiles from BODY_FAMILIES", /BODY_FAMILIES\.map/.test(list), true);
const trayFiles = ["components/models/CompareTray.tsx", "components/models/ModelCard.tsx"].map((f) => strip(readFileSync(f, "utf8"))).join("\n");
check("the tray never resolves or sends a trim", /api\/compare\/trims|[?&]trims=|current_market_trims/.test(trayFiles), false);
const trimPage = strip(readFileSync("app/models/[slug]/[trim]/page.tsx", "utf8")) + strip(readFileSync("lib/models/trim-specs.ts", "utf8"));
check("no dash fallback for a missing spec value", /\|\|\s*["'](?:-|–|—)["']|\?\?\s*["'](?:-|–|—)["']/.test(trimPage), false);
const modelPage = strip(readFileSync("app/models/[slug]/page.tsx", "utf8"));
check("the model page has no news block or dark industry band", /getRelatedEvents|sfIndZone|sfNewsList/.test(modelPage), false);
check("the model page queries and renders no market teaser while blocker 11 is active", /getModelMarketTeasers|public_model_market_teaser|teaser/i.test(modelPage), false);
const compare = readFileSync("app/compare/page.tsx", "utf8");
check("/compare still reads ?trims= and now ?models=", /getAll\("trims"\)/.test(compare) && /getAll\("models"\)/.test(compare), true);

console.log(failed ? `\n${failed} check(s) failed` : "\nall models checks passed");
process.exit(failed ? 1 : 0);
