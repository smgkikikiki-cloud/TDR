import fs from "node:fs";

let failed = 0;
function check(name: string, got: unknown, want: unknown) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) {
    failed += 1;
    console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`);
  } else console.log(`  ok   ${name}`);
}

const action = fs.readFileSync("app/admin/trim-retail-lifecycle-actions.ts", "utf8");
const page = fs.readFileSync("app/admin/(secure)/retail-lifecycle/page.tsx", "utf8");
const coverage = fs.readFileSync("app/admin/(secure)/prices/coverage/page.tsx", "utf8");
const input = fs.readFileSync("automotive/vehicle_master/vehreg/input_pipeline.py", "utf8");
const reviewStore = fs.readFileSync("automotive/vehicle_master/vehreg/retail_lifecycle_review.py", "utf8");
const lifecycle = fs.readFileSync("automotive/vehicle_master/tdr_bridge/lifecycle.py", "utf8");

console.log("trim retail lifecycle — trust boundary");
check("trim review uses ADMIN special operation", action.includes('operation: "UPSERT_TRIM_RETAIL_LIFECYCLE_REVIEW"'), true);
check("browser action never supplies reviewer actor", action.includes("actor:") === false, true);
check("server binds selected trim to canonical model", action.includes("trim.model_id !== modelId"), true);
check("server requires canonical parent CURRENT for new decisions", action.includes('action !== "reopen" && canonicalModelStatus !== "CURRENT"'), true);
check("workflow store enforces canonical parent CURRENT", reviewStore.includes('_parent_model_status(catalog, trim_id) != "CURRENT"'), true);
check("workflow store exempts reopen from parent guard", reviewStore.includes('if action != "reopen" && _parent_model_status'), true);
check("current/historical require HTTP(S) evidence", action.includes("Evidence ต้องเป็น HTTP(S) URL"), true);
check("dispatcher requires ADMIN source", input.includes("UPSERT_TRIM_RETAIL_LIFECYCLE_REVIEW requires source.kind ADMIN"), true);
check("dispatcher requires HUMAN actor", input.includes("_validate_trim_lifecycle_review_command") && input.includes("_validated_human_actor(command, operation)"), true);
check("review-only batches do not fake canonical state changes", input.includes("canonical_write_applied = False") && input.includes("if canonical_write_applied:"), true);
check("HUMAN trim review precedes price inference", lifecycle.indexOf("elif trim_id in decisions:") < lifecycle.indexOf("elif _positive_amount"), true);
check("historical parent precedes HUMAN trim review", lifecycle.indexOf('model_status.get(model_id) == "HISTORICAL"') < lifecycle.indexOf("elif trim_id in decisions:"), true);

console.log("\ntrim retail lifecycle — operator UX");
check("lifecycle bench includes both model and trim debt", page.includes("UNRESOLVED_MODEL_LIFECYCLE") && page.includes("UNRESOLVED_TRIM_LIFECYCLE"), true);
check("trim form only appears after worklist reaches trim blocker", page.includes('focused.blocker === "UNRESOLVED_TRIM_LIFECYCLE"'), true);
check("trim UI exposes CURRENT and HISTORICAL decisions", page.includes("CURRENT — grade นี้ยังอยู่ใน line-up") && page.includes("HISTORICAL — grade นี้ไม่อยู่ current line-up"), true);
check("trim UI exposes reopen path", page.includes("Reopen HUMAN decision") && page.includes('value="reopen"'), true);
check("price worklist routes model lifecycle debt to bench", coverage.includes("Review model lifecycle ↗"), true);
check("price worklist routes trim lifecycle debt to bench", coverage.includes("Review trim lifecycle ↗"), true);

console.log(failed ? `\n${failed} check(s) failed` : "\nall trim retail lifecycle checks passed");
process.exit(failed ? 1 : 0);
