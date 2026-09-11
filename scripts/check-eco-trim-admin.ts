import fs from "node:fs";
import {
  ECO_TRIM_SNAPSHOT_DATE,
  exactCandidateSignature,
  getEcoTrimCandidateGroups,
  getEcoTrimSnapshotHash,
} from "../lib/eco-trim-snapshot.ts";

let failed = 0;
function check(name: string, got: unknown, want: unknown) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) {
    failed += 1;
    console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`);
  } else console.log(`  ok   ${name}`);
}

console.log("ECO MarketTrim admin — immutable snapshot");
const groups = getEcoTrimCandidateGroups();
const hash = getEcoTrimSnapshotHash();
const sourceIds = groups.flatMap((group) => group.sourceIds);
check("snapshot date is pinned", ECO_TRIM_SNAPSHOT_DATE, "2026-09-08");
check("snapshot hash is full sha256", /^[0-9a-f]{64}$/.test(hash), true);
check("ready candidate groups are non-empty", groups.length > 0, true);
check("candidate group keys are unique", new Set(groups.map((group) => group.key)).size, groups.length);
check("candidate signatures are exact and unique", new Set(groups.map(exactCandidateSignature)).size, groups.length);
check("every group has model generation powertrain and sources", groups.every((group) => Boolean(group.modelId && group.generationId && group.powertrain && group.sourceIds.length)), true);
check("source UUIDs are unique inside each exact group", groups.every((group) => new Set(group.sourceIds).size === group.sourceIds.length), true);
console.log(`  info groups=${groups.length} source_refs=${sourceIds.length} snapshot_sha256=${hash.slice(0, 12)}…`);

console.log("\nECO MarketTrim admin — write boundary");
const action = fs.readFileSync("app/admin/eco-trim-actions.ts", "utf8");
const page = fs.readFileSync("app/admin/(secure)/eco-trims/page.tsx", "utf8");
const nextConfig = fs.readFileSync("next.config.ts", "utf8");
check("action reuses existing canonical queue action", action.includes("return enqueueVehicleInput(advanced)"), true);
check("action requires admin", action.includes("if (!(await isAdmin()))"), true);
check("action requires HUMAN editor identity", action.includes("HUMAN editor identity required"), true);
check("action checks existing ECO source refs", action.includes("alreadyAttached"), true);
check("action checks duplicate trim identity", action.includes("duplicateIdentity"), true);
check("action never emits ECO price into identity command", action.includes("price_thb"), false);
check("action never emits tyre/wheel into identity command", /wheel|tyre|tire/i.test(action), false);
check("action never emits battery fields into identity command", /battery/i.test(action), false);
check("page does not prefill canonical trim name from raw ECO label", page.includes('name="trim_name" defaultValue='), false);
check("page labels ECO price as evidence only", page.includes("ECO evidence price"), true);
check("server bundle explicitly traces normalized snapshot", nextConfig.includes("normalized.jsonl.gz"), true);
check("server bundle explicitly traces manifest", nextConfig.includes("manifest.json"), true);

console.log(failed ? `\n${failed} check(s) failed` : "\nall ECO MarketTrim admin checks passed");
process.exit(failed ? 1 : 0);
