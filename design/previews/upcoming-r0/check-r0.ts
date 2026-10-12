import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { execFileSync } from "node:child_process";

// R0 source-structure checks only; NOT runtime or publication-security tests.
// Run from repo root: node --experimental-strip-types design/previews/upcoming-r0/check-r0.ts
const root = process.cwd();
const read = (path: string) => readFileSync(join(root, path), "utf8");
let checks = 0;
function check(condition: unknown, message: string): asserts condition {
  assert.ok(condition, message);
  checks += 1;
}

const contractPath = "docs/portfolio/UPCOMING_CARS_R0_CONTRACT.md";
const contract = read(contractPath);
for (const required of [
  "stage", "state", "confidence", "window_precision", "window_from", "window_to",
  "sources[]", "image_license", "published_at", "brand_canonical_id", "predecessor_model_id",
  "launched_model_id", "stage_history", "internal_notes", "upcoming_car_updates",
  "migration_v66_upcoming_vehicles.sql",
  "no migration was created or run", "not a dedicated approved mockup",
]) check(contract.toLowerCase().includes(required.toLowerCase()), `R0 contract is missing ${required}`);

for (const [page, expected] of [
  ["p16", ["P16", "รถที่กำลังมา", "ระยะการเปิดตัว", "ความเชื่อมั่น", "ตลาดโลกเท่านั้น", "SYNTHETIC SAMPLE DATA"]],
  ["p17", ["P17", "ข้อมูลประมาณการ", "แหล่งข้อมูล", "ระยะการเปิดตัว", "canonical", "SYNTHETIC SAMPLE DATA"]],
  ["p27", ["P27", "Admin", "RUMOR", "REPORTED", "OEM_TEASED", "OEM_CONFIRMED", "LAUNCH_DATE_SET", "PRE_ORDER", "ACTIVE", "DELAYED", "CANCELLED", "LAUNCHED", "LOW", "MEDIUM", "HIGH", "CONFIRMED", "draft", "published", "sources", "image_license", "last_verified_at", "SYNTHETIC SAMPLE DATA"]],
] as const) {
  const html = read(`design/previews/upcoming-r0/${page}.html`);
  check(html.includes("NOT AN APPROVED MOCKUP"), `${page} must disclaim mockup approval`);
  check(html.includes("SYNTHETIC"), `${page} must mark sample content synthetic`);
  check(html.includes("../../tokens.css") && html.includes("../../components.css"), `${page} must use local TDR design styles`);
  check(!/<script\b|<img\b|https?:\/\//i.test(html), `${page} must remain offline and use no vehicle photos`);
  if (page === "p27") check(!/<form\s[^>]*action\s*=|<button\s+(?![^>]*disabled)/i.test(html), "P27 must show disabled static controls only");
  for (const text of expected) check(html.toLowerCase().includes(text.toLowerCase()), `${page} missing ${text}`);
}

const css = read("design/previews/upcoming-r0/preview.css");
check(!/#[0-9a-f]{3,8}\b|\b(?:rgb|hsl)a?\s*\(/i.test(css), "preview styling must use design tokens, not literal colors");

const migrations = readdirSync(join(root, "supabase"))
  .map((name) => /^migration_v(\d+)_.*\.sql$/.exec(name))
  .filter((match): match is RegExpExecArray => Boolean(match));
const versions = migrations.map((match) => Number(match[1]));
const duplicateVersions = [...new Set(versions.filter((version, index) => versions.indexOf(version) !== index))].sort((a, b) => a - b);
check(JSON.stringify(duplicateVersions) === JSON.stringify([12, 36]), "documented legacy migration sequence collisions must match main");
check(Math.max(...versions) === 65, "R0 migration inventory should be pinned to main through v65");
// Snapshot assertions pin THIS R0 against the observed v65 main; they do not reserve v66.
const candidateMigrations = readdirSync(join(root, "supabase")).filter((name) => /^migration_v66_.*\.sql$/.test(name));
check(candidateMigrations.length === 0, "R0 must not create a migration; proposed candidate v66 must remain free");
check(versions.includes(66) === false, "proposed v66 candidate must be collision-free against main inventory");

const allowed = [
  contractPath,
  "design/previews/upcoming-r0/",
];
const committed = execFileSync("git", ["diff", "--name-only", "origin/main...HEAD"], { encoding: "utf8" }).trim().split("\n").filter(Boolean);
const working = execFileSync("git", ["status", "--porcelain", "--untracked-files=all"], { encoding: "utf8" }).split("\n")
  .filter(Boolean).map((line) => line.slice(3));
for (const path of new Set([...committed, ...working])) {
  check(allowed.some((prefix) => prefix.endsWith("/") ? path.startsWith(prefix) : path === prefix),
    `R0 scope does not allow ${path}`);
  check(!path.startsWith("supabase/") && !path.startsWith("app/") && !path.startsWith("automotive/vehicle_master/"),
    `R0 must not change runtime, migration, or Vehicle Master path ${path}`);
}

console.log(`Upcoming Cars R0 static contract checks passed (${checks} assertions).`);
