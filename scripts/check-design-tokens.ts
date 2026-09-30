/** Design guard for the Ice design-system migration (design/DESIGN.md).
 *
 *  The migration happens one page per PR. A file is "migrated" once its path is
 *  listed in design/migrated.json → "strict". Strict files must:
 *    1. use colours only through CSS variables from design/tokens.css
 *       (no #hex, rgb(), rgba(), hsl() literals — except rgba() inside the
 *       shadow token itself, which lives in tokens.css and is never scanned);
 *    2. never render a car-brand logo (no resolveBrandLogo(), no logo_url);
 *    3. never pair a delta colour with no sign: every "delta-up" needs ▲ and +,
 *       every "delta-down" needs ▼ and −, within 200 characters of the class.
 *
 *  Unmigrated files are only reported (use --report to list them), so the check
 *  can go into `npm run check` on day one without breaking the build.
 *
 *    node --experimental-strip-types scripts/check-design-tokens.ts            # strict files only
 *    node --experimental-strip-types scripts/check-design-tokens.ts --report   # + counts for everything
 */
import { readFileSync, readdirSync, statSync, existsSync } from "node:fs";
import { join } from "node:path";

const ROOTS = ["app", "components"];
const EXT = /\.(css|tsx|ts)$/;
const COLOR = /#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(/g;
const LOGO = /resolveBrandLogo\s*\(|\blogo_url\b/g;
// Allowed literal colours: pure white/black text on the TDR logo plate is the only
// sanctioned case (DESIGN.md §โลโก้) and it must still go through a token in new code.
const ALLOW_FILES = new Set(["design/tokens.css"]);

const migrated: { strict: string[] } = existsSync("design/migrated.json")
  ? JSON.parse(readFileSync("design/migrated.json", "utf8"))
  : { strict: [] };
const strict = new Set(migrated.strict);

function walk(dir: string, out: string[] = []): string[] {
  if (!existsSync(dir)) return out;
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (EXT.test(p)) out.push(p);
  }
  return out;
}

const report = process.argv.includes("--report");
let failed = 0;
const rows: [string, number, number][] = [];

for (const file of ROOTS.flatMap((r) => walk(r))) {
  if (ALLOW_FILES.has(file)) continue;
  const src = readFileSync(file, "utf8");
  const colors = src.match(COLOR)?.length ?? 0;
  const logos = src.match(LOGO)?.length ?? 0;
  if (strict.has(file)) {
    const before = failed;
    if (colors) { failed++; console.log(`  FAIL ${file}: ${colors} literal colour(s) — use var(--token) from design/tokens.css`); }
    if (logos) { failed++; console.log(`  FAIL ${file}: car-brand logo usage — logos are banned (DESIGN.md)`); }
    for (const [cls, arrow, sign] of [["delta-up", "▲", "+"], ["delta-down", "▼", "−"]] as const) {
      // The sign must sit next to the element that carries the class (±200 chars),
      // not merely somewhere in the file.
      for (const m of src.matchAll(new RegExp(cls, "g"))) {
        const near = src.slice(Math.max(0, m.index! - 200), m.index! + 200);
        if (!near.includes(arrow) || !near.includes(sign)) {
          failed++;
          console.log(`  FAIL ${file}: ${cls} at offset ${m.index} has no ${arrow} and ${sign} within 200 chars`);
        }
      }
    }
    if (failed === before) console.log(`  ok   ${file}`);
  } else if (colors || logos) {
    rows.push([file, colors, logos]);
  }
}

for (const f of strict) {
  if (!existsSync(f)) { failed++; console.log(`  FAIL design/migrated.json lists a missing file: ${f}`); }
}

if (report) {
  console.log(`\nnot yet migrated (${rows.length} files with literal colours or logos):`);
  for (const [f, c, l] of rows.sort((a, b) => b[1] - a[1])) console.log(`  ${String(c).padStart(4)} colours  ${String(l).padStart(2)} logos  ${f}`);
}
console.log(`\ndesign guard: ${strict.size} strict file(s), ${failed} failure(s)`);
if (failed) process.exit(1);
