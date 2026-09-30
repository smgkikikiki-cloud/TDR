/** Contrast guard for the design tokens (design/DESIGN.md §3, §8), light and dark.
 *
 *  - Text pairs must reach 4.5:1.
 *  - --border-strong and every --chart-cat-N must reach 3:1 against the page.
 *  - Any --map-N / --diverge-N fill under 3:1 against the page (in either mode) needs the --border-strong
 *    outline; design/components.css must give .tdr-swatch a 1px border and .tdr-region a non-scaling 1px
 *    stroke in that colour (a thinner outline fails). This is where the
 *    known cases are covered: map-1/2, diverge-2/3/4, and --diverge-4 in dark mode at 2.9:1.
 *
 *    node --experimental-strip-types scripts/check-design-contrast.ts [path/to/components.css]
 */
import { readFileSync } from "node:fs";

type Mode = "light" | "dark";
const tokens = JSON.parse(readFileSync("design/tokens.json", "utf8"));
const color = new Map<string, Record<Mode, string>>(tokens.color.tokens.map((t: { name: string; value: Record<Mode, string> }) => [t.name, t.value]));
const get = (name: string, mode: Mode): string => {
  const v = color.get(name);
  if (!v) throw new Error(`unknown token --${name}`);
  return v[mode];
};

function luminance(hex: string): number {
  const h = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
function ratio(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

let failed = 0;
const fail = (msg: string) => { failed++; console.log(`  FAIL ${msg}`); };
const modes: Mode[] = ["light", "dark"];

// text on its surface, 4.5:1
const textPairs: [string, string][] = [
  ["ink", "surface-page"], ["ink", "surface-raised"], ["ink-muted", "surface-page"], ["ink-muted", "surface-raised"],
  ["red-text", "surface-page"], ["red-text", "surface-raised"], ["delta-up", "surface-page"], ["delta-up", "surface-raised"],
  ["delta-down", "surface-page"], ["delta-down", "surface-raised"], ["brand-blue", "surface-page"], ["brand-blue", "surface-raised"],
  ["brand-navy", "surface-page"], ["brand-navy", "surface-raised"],
  ["flag-estimate-ink", "flag-estimate-bg"], ["on-action", "action-primary"], ["on-action", "tier-pro"], ["surface-page", "tier-enterprise"],
  ["on-accent", "accent"], ["ink-on-inverse", "surface-inverse"],
];
for (const mode of modes) for (const [fg, bg] of textPairs) {
  const r = ratio(get(fg, mode), get(bg, mode));
  if (r < 4.5) fail(`${mode}: --${fg} on --${bg} is ${r.toFixed(2)}:1 (needs 4.5)`);
}

// non-text marks, 3:1 against the page
for (const mode of modes) {
  const page = get("surface-page", mode);
  for (const name of ["border-strong", "chart-cat-1", "chart-cat-2", "chart-cat-3", "chart-cat-4", "chart-cat-5"]) {
    const r = ratio(get(name, mode), page);
    if (r < 3) fail(`${mode}: --${name} is ${r.toFixed(2)}:1 against the page (needs 3)`);
  }
}

// pale map / diverging fills need the outline
const cssPath = process.argv[2] ?? "design/components.css";
const css = readFileSync(cssPath, "utf8");
/** The declaration block of the first rule that starts with `selector` ("" when missing). */
const ruleBody = (selector: string): string =>
  new RegExp(`(?:^|\\})\\s*${selector.replace(".", "\\.")}\\s*\\{([^}]*)\\}`, "m").exec(css)?.[1] ?? "";

// .tdr-swatch: a border of at least 1px, solid, in --border-strong.
const swatch = ruleBody(".tdr-swatch");
const swatchBorder = /border:\s*([\d.]+)px\s+solid\s+var\(--border-strong\)/.exec(swatch);
if (!swatchBorder) fail(`${cssPath}: .tdr-swatch needs "border: Npx solid var(--border-strong)"`);
else if (Number(swatchBorder[1]) < 1) fail(`${cssPath}: .tdr-swatch outline is ${swatchBorder[1]}px (needs at least 1px)`);

// .tdr-region: SVG strokes are in user units, so the 1px outline must be non-scaling.
const region = ruleBody(".tdr-region");
if (!/stroke:\s*var\(--border-strong\)/.test(region)) fail(`${cssPath}: .tdr-region must stroke with var(--border-strong)`);
const regionWidth = /stroke-width:\s*([\d.]+)(px)?/.exec(region);
if (!regionWidth) fail(`${cssPath}: .tdr-region needs a stroke-width`);
else if (regionWidth[2] !== "px") fail(`${cssPath}: .tdr-region stroke-width must be in px (got "${regionWidth[0]}")`);
else if (Number(regionWidth[1]) < 1) fail(`${cssPath}: .tdr-region outline is ${regionWidth[1]}px (needs at least 1px)`);
if (!/vector-effect:\s*non-scaling-stroke/.test(region)) fail(`${cssPath}: .tdr-region needs vector-effect: non-scaling-stroke so 1px stays 1px when the map SVG is scaled`);
const needsOutline: string[] = [];
for (const prefix of ["map", "diverge"]) for (let n = 1; n <= 5; n++) {
  const name = `${prefix}-${n}`;
  for (const mode of modes) {
    const r = ratio(get(name, mode), get("surface-page", mode));
    if (r < 3) needsOutline.push(`--${name} ${mode} ${r.toFixed(2)}:1`);
  }
}
const d4 = ratio(get("diverge-4", "dark"), get("surface-page", "dark"));
if (!(d4 < 3)) console.log(`  note --diverge-4 (dark) is now ${d4.toFixed(2)}:1; the outline is no longer required for it`);
console.log(`  outlined by --border-strong (${needsOutline.length}): ${needsOutline.join(", ")}`);
console.log(`\ndesign contrast: ${failed} failure(s)`);
if (failed) process.exit(1);
