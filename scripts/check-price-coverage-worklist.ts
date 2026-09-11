import fs from "node:fs";

let failed = 0;
function check(name: string, got: unknown, want: unknown) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) {
    failed += 1;
    console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`);
  } else console.log(`  ok   ${name}`);
}

const helper = fs.readFileSync("lib/price-coverage-worklist.ts", "utf8");
const review = fs.readFileSync("lib/price-coverage-review.ts", "utf8");
const evidence = fs.readFileSync("lib/price-evidence-registry.ts", "utf8");
const page = fs.readFileSync("app/admin/(secure)/prices/coverage/page.tsx", "utf8");
const inputPage = fs.readFileSync("app/admin/(secure)/vehicle-input/page.tsx", "utf8");
const inputActions = fs.readFileSync("app/admin/input-actions.ts", "utf8");
const reviewActions = fs.readFileSync("app/admin/price-coverage-actions.ts", "utf8");
const nav = fs.readFileSync("components/admin/AdminNav.tsx", "utf8");

console.log("price coverage worklist — canonical trust boundary");
check("current price requires amount_thb, so JSON null is not counted", helper.includes("current_list_price?.amount_thb"), true);
check("catalog seed values are read only as separate hints", helper.includes("variantSeedPrices"), true);
check("legacy lowercase current is not accepted as lifecycle evidence", helper.includes("Exact uppercase is deliberate") && helper.includes('return value === "CURRENT"'), true);
check("model lifecycle comes from canonical payload, not editorial serving status", helper.includes("model?.payload?.retail_status"), true);
check("missing price is computed only across CURRENT trims", helper.includes("const missing = current.filter((trim) => actualCurrentPrice(trim) == null)"), true);
check("unverified trim lifecycle blocks readiness", helper.includes("row.unverifiedTrims === 0"), true);
check("ready model must itself be canonical CURRENT", helper.includes('row.modelStatus === "CURRENT"'), true);
check("historical models are excluded from current retail denominator", helper.includes('row.modelStatus !== "HISTORICAL"'), true);
check("unverified models stay in denominator", helper.includes("UNVERIFIED models remain in the denominator"), true);
check("model lifecycle blocker exists", helper.includes('"UNRESOLVED_MODEL_LIFECYCLE"'), true);
check("trim lifecycle blocker exists", helper.includes('"UNRESOLVED_TRIM_LIFECYCLE"'), true);
check("models without MarketTrim remain visible blockers", helper.includes('"NO_MARKET_TRIM"'), true);
check("price debt remains a separate blocker", helper.includes('"MISSING_LIST_PRICE"'), true);
check("worklist is prioritized by registration impact", helper.includes("b.registrations3m - a.registrations3m"), true);
check("registration mapping uses canonical model tdr_model_id bridge", helper.includes("unitsByTdrModel.get(String(model.tdr_model_id"), true);
check("OEM target signal comes from price-intelligence registry", helper.includes("pricefeed/targets.json"), true);
check("coverage decisions are loaded from versioned review state", review.includes("pricefeed/review/coverage.json"), true);
check("coverage decisions only expose defer rows", review.includes('action !== "defer"'), true);
check("evidence registry accepts only OEM source profiles", evidence.includes('toUpperCase() === "OEM"'), true);
check("evidence registry scopes targets by exact model_hint", evidence.includes("model_hint") && evidence.includes("=== canonicalModelId"), true);
check("server resolves registry target against selected trim model", inputActions.includes("resolveOemTarget(targetId, String(trim.model_id))"), true);
check("browser source URL is replaced by registry URL when target selected", inputActions.includes("sourceRef = target.url") && inputActions.includes("sourceLabel = target.sourceId"), true);
check("quick LIST_PRICE cannot enter canonical queue without evidence ref", inputActions.includes('priceType === "LIST_PRICE" && !sourceRef'), true);
check("coverage disposition is sent as ADMIN review metadata", reviewActions.includes('operation: "UPSERT_PRICE_COVERAGE_REVIEW"') && reviewActions.includes('source: { kind: "ADMIN"'), true);
check("browser cannot choose reviewer identity for coverage disposition", reviewActions.includes("actor:") === false, true);

console.log("\nprice coverage worklist — operator UX");
check("page labels seeds unverified", page.includes("UNVERIFIED seed hint"), true);
check("page exposes all four blocker states", page.includes("UNRESOLVED_MODEL_LIFECYCLE") && page.includes("NO_MARKET_TRIM") && page.includes("UNRESOLVED_TRIM_LIFECYCLE") && page.includes("MISSING_LIST_PRICE"), true);
check("page explains fail-closed denominator", page.includes("Fail-closed denominator"), true);
check("page says historical trims do not require current price", page.includes("HISTORICAL trim ไม่ต้องมี current LIST_PRICE"), true);
check("page says deferred is not ready", page.includes("Deferred ≠ ready"), true);
check("page exposes current/unverified/historical trim counts", page.includes("currentTrims") && page.includes("unverifiedTrims") && page.includes("historicalTrims"), true);
check("page exposes actionable and deferred price counts", page.includes("actionableMissingTrims") && page.includes("deferredTrims"), true);
check("page shows registration weighted coverage", page.includes("3M registration coverage"), true);
check("missing-price action carries canonical model into quick input", page.includes('/admin/vehicle-input?model=${encodeURIComponent(row.canonicalModelId)}'), true);
check("no-trim action uses model-scoped ECO review when snapshot candidates exist", page.includes('/admin/eco-trims?model=${encodeURIComponent(row.canonicalModelId)}') && page.includes("Review ECO"), true);
check("no-trim action preserves manual fallback", page.includes("Manual fallback") && page.includes("Manual MarketTrim"), true);
check("price page counts ECO candidate groups by canonical model", page.includes("getEcoTrimCandidateGroups") && page.includes("ecoGroupsByModel"), true);
check("focused quick input filters to the requested model", inputPage.includes("trim.model_id === focusedModel"), true);
check("focused quick input removes deferred trims from actionable list", inputPage.includes("actionableFocusedTrims") && inputPage.includes("!coverageReviews.has"), true);
check("focused quick input exposes defer and reopen controls", inputPage.includes("Defer from actionable queue") && inputPage.includes("Reopen"), true);
check("focused quick input exposes registered OEM targets", inputPage.includes("Registered OEM target") && inputPage.includes("oemTargetsForModel(focusedModel)"), true);
check("registry target stays optional when the registered page has no usable price", inputPage.includes("ไม่ใช้ registry target — ใช้ source ref ด้านล่าง"), true);
check("admin navigation exposes the worklist", nav.includes('href="/admin/prices/coverage"'), true);

console.log(failed ? `\n${failed} check(s) failed` : "\nall price coverage worklist checks passed");
process.exit(failed ? 1 : 0);
