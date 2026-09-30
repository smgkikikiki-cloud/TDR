/** Design guard for the Ice design-system migration (design/DESIGN.md).
 *
 *  The migration happens one page per PR. A file is "migrated" once its path is
 *  listed in design/migrated.json → "strict". Strict files must:
 *    1. use colours only through CSS variables from design/tokens.css
 *       (no #hex, rgb(), rgba(), hsl() literals — except rgba() inside the
 *       shadow token itself, which lives in tokens.css and is never scanned);
 *    2. never render a car-brand logo (no resolveBrandLogo(), no logo_url);
 *    3. never pair a delta colour with no sign: every "delta-up" needs ▲ and +,
 *       every "delta-down" needs ▼ and −, inside the element that carries the class.
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

/** The source text of the element that carries a class at `idx`: from the opening
 *  tag's "<" to its matching closing tag (depth-aware for same-name nesting), so a
 *  neighbouring element's ▲/+ or ▼/− can never satisfy this one. Self-closing or
 *  unbalanced tags fall back to the rest of the opening tag plus 300 characters. */
function elementRegion(src: string, idx: number): string {
  const open = src.lastIndexOf("<", idx);
  const name = open >= 0 ? /^<([A-Za-z][\w.-]*)/.exec(src.slice(open))?.[1] : undefined;
  if (open < 0 || !name) return src.slice(Math.max(0, idx - 80), idx + 300);
  const tagEnd = src.indexOf(">", idx);
  if (tagEnd < 0 || src[tagEnd - 1] === "/") return src.slice(open, Math.min(src.length, (tagEnd < 0 ? idx : tagEnd) + 1));
  const re = new RegExp(`<(/?)${name.replace(/[.]/g, "\\.")}(?=[\\s>/])`, "g");
  re.lastIndex = tagEnd;
  let depth = 1;
  for (let t = re.exec(src); t; t = re.exec(src)) {
    const selfClosing = !t[1] && src[src.indexOf(">", t.index) - 1] === "/";
    if (t[1]) depth--; else if (!selfClosing) depth++;
    if (depth === 0) return src.slice(open, src.indexOf(">", t.index) + 1);
  }
  return src.slice(open, tagEnd + 301);
}

const report = process.argv.includes("--report");
let failed = 0;
const rows: [string, number, number][] = [];

// Strict files that live outside app/ and components/ (design/components.css) are scanned too.
const scanned = new Set(ROOTS.flatMap((r) => walk(r)));
for (const f of strict) if (existsSync(f) && !ALLOW_FILES.has(f)) scanned.add(f);

for (const file of scanned) {
  if (ALLOW_FILES.has(file)) continue;
  const src = readFileSync(file, "utf8");
  const colors = src.match(COLOR)?.length ?? 0;
  const logos = src.match(LOGO)?.length ?? 0;
  if (strict.has(file)) {
    const before = failed;
    if (colors) { failed++; console.log(`  FAIL ${file}: ${colors} literal colour(s) — use var(--token) from design/tokens.css`); }
    if (logos) { failed++; console.log(`  FAIL ${file}: car-brand logo usage — logos are banned (DESIGN.md)`); }
    for (const [cls, arrow, sign] of [["delta-up", "▲", "+"], ["delta-down", "▼", "−"]] as const) {
      // CSS files only define the classes and reference the --delta-* tokens; the sign rule
      // applies to the markup that uses a delta class. `(?<![-\\w])` skips --delta-up tokens.
      if (file.endsWith(".css")) break;
      for (const m of src.matchAll(new RegExp(`(?<![-\\w])${cls}`, "g"))) {
        const region = elementRegion(src, m.index!);
        if (!region.includes(arrow) || !region.includes(sign)) {
          failed++;
          console.log(`  FAIL ${file}: ${cls} at offset ${m.index} — its own element has no ${arrow} and ${sign}`);
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
