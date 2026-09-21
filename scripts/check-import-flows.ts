import fs from "node:fs";
import { campaignIdFor } from "../lib/campaign-identity.ts";

let failed = 0;
function check(name: string, got: unknown, want: unknown = true) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { failed++; console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`); }
  else console.log(`  ok   ${name}`);
}
const read = (path: string) => fs.readFileSync(path, "utf8");

console.log("import routes by source — one file, the parser that understands it");
const worker = read("automotive/vehicle_master/tools/import_worker.py");
check("DLT is read by the registration importer", worker.includes("from vehreg.registration_import import"));
check("DLT does not reach the ECO importer",
  worker.includes('"DLT": _import_dlt') && !worker.includes('"DLT": _import_eco'));
check("a source with no parser is refused rather than routed to the nearest one",
  worker.includes("has no import profile yet"));
const ecoCli = read("automotive/vehicle_master/tools/import_source.py");
check("the ECO path refuses a non-ECO source outright",
  ecoCli.includes("has no parser on the ECO path"));
const uploadAction = read("app/admin/import-actions.ts");
check("upload only accepts sources that have a parser",
  uploadAction.includes('new Set(["ECO", "DLT"])'));

console.log("\nimport results outlive the worker");
check("exceptions are written onto the run row, not a temp directory",
  worker.includes("exception_rows"));
check("the run row has somewhere durable to keep them",
  read("supabase/migration_v40_import_run_results.sql").includes("exception_rows jsonb"));
check("/admin/exceptions reads them back from the run",
  read("app/admin/(secure)/exceptions/page.tsx").includes("listRunExceptions"));
check("a canonical run waits for its push before it claims to be done",
  worker.includes("WRITTEN_PENDING_PUBLISH") && worker.includes("CANONICAL_SOURCES"));
const importFlow = read(".github/workflows/source-import.yml");
check("finalize runs after the push, not before",
  importFlow.indexOf("git push origin HEAD:main") < importFlow.indexOf("import_worker.py finalize"));

console.log("\nno human approval in a deterministic write path");
check("uploaded imports go to main rather than a pull request",
  !importFlow.includes("gh pr create"));
const pricefeed = read(".github/workflows/pricefeed.yml");
check("the price tracker publishes instead of opening a PR to merge",
  !pricefeed.includes("gh pr create") && pricefeed.includes("git push origin HEAD:main"));
const canonicalInput = read(".github/workflows/canonical-input.yml");
check("a saved canonical edit is not held behind a merge",
  !canonicalInput.includes("gh pr create"));

console.log("\nprice: the owner's fields, the ledger's bookkeeping");
const priceAction = read("app/admin/trim-price-actions.ts");
check("no reason is asked for on a price save", !priceAction.includes('"reason", "เหตุผล'));
// A campaign window says when the promotion runs. Using it as the list
// price's effective date would backdate a price nobody said was in effect.
check("the campaign window is not applied to the list price",
  !/price_type: "LIST_PRICE",\s*\n\s*effective_from/.test(priceAction));
check("a campaign can be closed without a review workflow",
  priceAction.includes("closeTrimCampaign") && priceAction.includes("CLOSE_PRICE"));
check("two models' identically named grades get different campaign ids",
  campaignIdFor("toyota.camry.axvh70.trim.premium", "2026-09-01")
    !== campaignIdFor("toyota.corolla.e210.trim.premium", "2026-09-01"));
check("the same promotion re-saved keeps its id",
  campaignIdFor("toyota.camry.axvh70.trim.premium", "2026-09-01"),
  campaignIdFor("toyota.camry.axvh70.trim.premium", "2026-09-01"));
check("a campaign id stays inside the pipeline's safe token charset",
  /^[A-Za-z0-9][A-Za-z0-9_.:-]*$/.test(campaignIdFor("toyota.camry.axvh70.trim.premium", "2026-09-01")));

console.log("\nprice read: one release, and gifts from the campaign that holds them");
const editor = read("lib/canonical-editor.ts");
check("price history is scoped to the model's own release",
  editor.includes('.eq("release_id", model.release_id)'));
check("gifts are read from the campaign quote, not from a price row",
  editor.includes("firstCampaignOffer") && !editor.includes("payload as any)?.gifts"));
check("the release carries gifts for it to read",
  read("automotive/vehicle_master/vehreg/pricing.py").includes('"gifts": campaign.gifts if campaign else ""'));

console.log("\nregistration identity: one bridge, not a second one");
const exceptionActions = read("app/admin/exception-actions.ts");
check("no legacy models row is forged behind the crosswalk's back",
  !exceptionActions.includes('from("models")\n    .insert'));
check("a model with no registration identity says so instead of guessing",
  exceptionActions.includes("ยังไม่ได้เชื่อมกับ registration identity"));
check("assigning a label writes the alias that makes next month automatic",
  exceptionActions.includes("registration_model_aliases"));
check("and fixes the months already loaded",
  exceptionActions.includes("admin-assigned-alias"));

console.log("\nadmin surface: six doors");
const nav = read("components/admin/AdminNav.tsx");
for (const route of ["/admin/vehicles", "/admin/import", "/admin/exceptions", "/admin/market", "/admin/research"]) {
  check(`nav offers ${route}`, nav.includes(`href="${route}"`));
}
for (const route of ["/admin/prices", "/admin/eco-trims", "/admin/data-quality",
                     "/admin/retail-lifecycle", "/admin/vehicle-input", "/admin/registrations",
                     "/admin/plants/new", "/admin/companies/new", "/admin/events/new"]) {
  check(`nav does not offer ${route}`, !nav.includes(`href="${route}"`));
}
const home = read("app/admin/(secure)/page.tsx");
check("home does not lead back into the retired workflows",
  ["/admin/prices/coverage", "/admin/eco-trims", "/admin/retail-lifecycle",
   "/admin/data-quality", "/admin/registrations", "canonical_vehicle_releases"]
    .every((route) => !home.includes(route)));
const market = read("app/admin/(secure)/market/page.tsx");
check("market is read-only, with no ingest or review tabs",
  ["/admin/registrations", "/admin/prices", "/admin/data-quality"]
    .every((route) => !market.includes(`href="${route}"`)));
const workspace = read("app/admin/(secure)/vehicles/[modelId]/page.tsx");
check("the vehicle page does not send the owner to the raw queue",
  !workspace.includes("/admin/vehicle-input"));

console.log("\nuploads advertise a size that actually works");
check("the server action body limit is configured", read("next.config.ts").includes("bodySizeLimit"));
for (const path of ["app/admin/import-actions.ts", "app/admin/research-file-actions.ts"]) {
  check(`${path} enforces the advertised limit`, read(path).includes("4 * 1024 * 1024"));
}
check("no page advertises a limit the deployment cannot accept",
  !read("app/admin/(secure)/import/page.tsx").includes("40 MB")
  && !read("app/admin/(secure)/research/page.tsx").includes("50 MB"));

console.log("\nmember access: signing in is the entitlement");
for (const path of ["app/api/tools/compare/route.ts", "app/api/tools/sales-modules/route.ts",
                    "app/api/research/read/route.ts", "app/api/export/pdf/route.ts",
                    "lib/registration-analytics.ts"]) {
  check(`${path} does not gate the product on a profile`, !read(path).includes("requireActivatedAccess"));
}
check("paying still asks for verified identity", read("lib/billing.ts").includes("requireActivatedAccess("));

console.log("\nprofile is edited a field at a time, not re-submitted whole");
const profileRoute = read("app/api/account/profile/route.ts");
// A member updating one field is not also saying they withdrew consent and
// are no longer a company. Only keys the request actually carries are written.
check("only keys the request sends are written", profileRoute.includes("hasOwnProperty.call(body,"));
for (const field of ["postcode", "is_individual", "company_name", "marketing_consent"]) {
  check(`${field} is only touched when sent`, profileRoute.includes(`sent("${field}")`));
}
check("an omitted consent no longer writes false",
  !/const marketingConsent = body\.marketing_consent === true;\n\n/.test(profileRoute));
check("an empty body does not stamp the profile as filled in",
  profileRoute.includes("touchedFields"));

console.log("\ncopy matches the policy it describes");
const profilePage = read("app/member/profile/page.tsx");
check("the page does not claim the product needs a profile",
  profilePage.includes("ใช้ Compare และ Sales Tools ได้ทันที"));
// Checkout needs all three, not the phone alone -- saying otherwise sends
// somebody to Stripe to be turned away.
check("checkout is described as needing all three, not just a phone",
  profilePage.includes("สามข้อด้านบนต้องครบทั้งหมด")
  && !profilePage.includes("ยืนยันเบอร์มือถือจำเป็นเฉพาะ"));

console.log("\ncomments describe the gate that actually exists");
const policyServer = read("lib/access-policy-server.ts");
check("no comment still claims every tool route checks activation",
  !policyServer.includes("the single stored gate every tool route"));
check("resolveAccessContext is not described as insufficient for tools",
  !policyServer.includes("must use requireActivatedAccess() below instead"));
check("billing does not call activation the check every tool route uses",
  !read("lib/billing.ts").includes("the same centralized check every member tool route uses"));

console.log("\nresearch: the admin library is private, the public surface untouched");
check("public research still reads articles", fs.existsSync("app/research/[slug]/page.tsx"));
check("the research unlock route is still there", fs.existsSync("app/api/research/read/route.ts"));
check("the free monthly quota is still enforced",
  read("lib/access-policy.ts").includes("researchFullMonthlyLimit"));
check("admin research files are private and signed",
  read("lib/research-files.ts").includes("createSignedUrl"));

console.log(failed ? `\n${failed} check(s) failed` : "\nall import flow checks passed");
process.exit(failed ? 1 : 0);
