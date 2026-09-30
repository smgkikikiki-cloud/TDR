/** Regenerates design/tokens.css from design/tokens.json.
 *
 *  design/tokens.json is the single source of truth for colours, type, spacing,
 *  radius, shadow and breakpoints (TDR Design System v2, extended from Ice's v1).
 *  Never edit design/tokens.css by hand: edit tokens.json, then run
 *
 *    node --experimental-strip-types scripts/build-design-tokens.ts
 *
 *  Pass --check to fail (exit 1) when tokens.css is out of date instead of
 *  rewriting it; `npm run check:design` does that.
 */
import { readFileSync, writeFileSync } from "node:fs";

type Mode = "light" | "dark";
type ColorToken = { name: string; value: Record<Mode, string>; usage?: string };
type Plain = { name: string; value: string };

const tokens = JSON.parse(readFileSync("design/tokens.json", "utf8"));
const colors: ColorToken[] = tokens.color.tokens;
const block = (mode: Mode, indent: string) =>
  colors.map((t) => `${indent}--${t.name}: ${t.value[mode]};`).join("\n");

const fam = tokens.type.families as Record<string, string>;
const extra: string[] = [
  `  --font-display: ${fam.display};`,
  `  --font-sans: ${fam.sans};`,
  `  --font-mono: ${fam.mono};`,
];
for (const g of tokens.type.groups) {
  for (const s of g.styles) {
    extra.push(`  --type-${s.name}: ${s.fontWeight} ${s.fontSize}/${s.lineHeight} var(--font-${g.family});`);
  }
}
for (const k of ["spacing", "radius", "shadow", "breakpoint"]) {
  for (const t of tokens[k].tokens as Plain[]) extra.push(`  --${t.name}: ${t.value};`);
}

const css = `/* TDR Design System v2 — สร้างอัตโนมัติจาก design/tokens.json ห้ามแก้ไฟล์นี้ด้วยมือ
   แก้ tokens.json แล้วรัน: node --experimental-strip-types scripts/build-design-tokens.ts */
:root {
  color-scheme: light;
${block("light", "  ")}
${extra.join("\n")}
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
${block("dark", "    ")}
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
${block("dark", "  ")}
}
`;

if (process.argv.includes("--check")) {
  const current = readFileSync("design/tokens.css", "utf8");
  if (current !== css) {
    console.log("  FAIL design/tokens.css is out of date — run: node --experimental-strip-types scripts/build-design-tokens.ts");
    process.exit(1);
  }
  console.log("  ok   design/tokens.css matches design/tokens.json");
} else {
  writeFileSync("design/tokens.css", css);
  console.log(`wrote design/tokens.css (${colors.length} colour tokens)`);
}
