import fs from "node:fs";

let failed = 0;
function check(name: string, got: unknown, want: unknown) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) {
    failed += 1;
    console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`);
  } else console.log(`  ok   ${name}`);
}

const action = fs.readFileSync("app/admin/retail-lifecycle-actions.ts", "utf8");
const queue = fs.readFileSync("lib/canonical-input-queue.ts", "utf8");
const page = fs.readFileSync("app/admin/(secure)/retail-lifecycle/page.tsx", "utf8");
const bulk = fs.readFileSync("components/admin/BulkRetailLifecycleReview.tsx", "utf8");
const nav = fs.readFileSync("components/admin/AdminNav.tsx", "utf8");

console.log("retail lifecycle review — trust boundary");
check("only CURRENT/HISTORICAL can be reviewed", action.includes('new Set(["CURRENT", "HISTORICAL"])'), true);
check("review requires HTTP(S) evidence", action.includes("http:") && action.includes("https:") && action.includes("Evidence ต้องเป็น HTTP(S) URL"), true);
check("review requires checked date", action.includes("reviewed_at") && action.includes("retail_checked_at: reviewedAt"), true);
check("review writes canonical retail status/source/date", action.includes("retail_status: status") && action.includes("retail_source: sourceRef") && action.includes("retail_checked_at: reviewedAt"), true);
check("review uses normal canonical model bundle writer", action.includes('operation: "UPSERT_MODEL_BUNDLE"'), true);
check("server resolves model parent brand/generation", action.includes("current_vehicle_models") && action.includes("current_vehicle_brands") && action.includes("current_vehicle_generations"), true);
check("browser cannot supply actor in review action", action.includes("actor:") === false, true);
check("registered evidence target is resolved server-side against model", action.includes("resolveOemTarget(targetId, modelId)"), true);
check("invalid cross-model registry target is rejected", action.includes("registered OEM evidence target ไม่ตรงกับ canonical model นี้"), true);
check("registry URL overrides browser source value", action.includes("target?.url || evidenceUrl"), true);
check("queue injects authenticated editor actor", queue.includes("currentEditor") && queue.includes("actor,") && queue.includes("commands.map"), true);
check("queue only accepts ADMIN review source", queue.includes('kind !== "ADMIN"'), true);
check("queue keeps idempotent batch hash", queue.includes("payload_sha256") && queue.includes('error?.code === "23505"'), true);

console.log("\nbulk model lifecycle review — trust boundary");
check("bulk review caps one atomic batch", action.includes("MAX_BULK_REVIEW = 20") && action.includes("bulk review รองรับสูงสุด"), true);
check("bulk re-resolves every target against exact canonical model", action.includes("const target = resolveOemTarget(targetId, modelId)"), true);
check("bulk only accepts CURRENT_MODEL_PAGE evidence", action.includes('target.role !== "CURRENT_MODEL_PAGE"'), true);
check("bulk rejects stale already-reviewed models", action.includes('canonicalStatus !== "UNVERIFIED"') && action.includes("refresh lifecycle bench"), true);
check("bulk requires one active release", action.includes("releaseIds.size !== 1") && action.includes("active release เดียวกัน"), true);
check("bulk remains HUMAN-selected, not auto-approved", bulk.includes('type="checkbox" name="bulk_model_id"') && bulk.includes("ไม่มี auto-approve"), true);
check("bulk UI only surfaces registered CURRENT_MODEL_PAGE targets", bulk.includes('target.role === "CURRENT_MODEL_PAGE"'), true);
check("bulk selection is unchecked by default", bulk.includes('type="checkbox" name="bulk_model_id"') && !bulk.includes("defaultChecked"), true);
check("bulk queues canonical model bundle commands", action.includes("admin-retail-lifecycle-bulk-") && action.includes("commands,"), true);

console.log("\nretail lifecycle review — operator UX");
check("workbench is registration prioritized", page.includes("getPriceCoverageWorklist") && page.includes("registrations3m"), true);
check("workbench exposes model lifecycle debt", page.includes('row.blocker === "UNRESOLVED_MODEL_LIFECYCLE"'), true);
check("workbench exposes registered OEM evidence targets", page.includes("oemTargetsForModel") && page.includes("Official evidence URL"), true);
check("OEM target can prefill without auto-approving lifecycle", page.includes("Use evidence →") && page.includes("selectedTarget") && page.includes('name="retail_status"'), true);
check("selected registry target id is posted for server re-resolution", page.includes('name="target_id" value={selectedTarget.id}'), true);
check("registry-bound URL is read-only in browser form", page.includes("readOnly={Boolean(selectedTarget)}"), true);
check("bulk HUMAN review session is surfaced on lifecycle bench", page.includes("BulkRetailLifecycleReview") && page.includes("bulkQueued"), true);
check("workbench explains identity is not retail evidence", page.includes("Identity, ECO record, registration") && page.includes("ไม่ใช่ retail evidence"), true);
check("admin nav exposes lifecycle workbench", nav.includes('href="/admin/retail-lifecycle"'), true);

console.log(failed ? `\n${failed} check(s) failed` : "\nall retail lifecycle review checks passed");
process.exit(failed ? 1 : 0);
