/** Tests for the design component helpers (lib/design/format.ts) and structural guarantees of the
 *  component layer (design/components.css, components/design/). Runs under Node's type stripping.
 *
 *    node --experimental-strip-types scripts/check-design-components.ts
 */
import { readFileSync, readdirSync } from "node:fs";
import { TIER_CLASS, TIER_LABEL, clampStep, formatDelta, formatNumber, tierForReport, type Tier } from "../lib/design/format.ts";

let failed = 0;
function check(name: string, got: unknown, want: unknown) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { failed++; console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`); } else console.log(`  ok   ${name}`);
}

console.log("delta: arrow and sign always");
check("up shows ▲ and +", formatDelta(1.24), { direction: "up", text: "▲ +1.2 pp" });
check("down shows ▼ and the true minus sign", formatDelta(-0.8), { direction: "down", text: "▼ −0.8 pp" });
check("rounds to zero: no arrow, no sign", formatDelta(0.04), { direction: "zero", text: "0.0 pp" });
check("negative rounding to zero is also zero", formatDelta(-0.04), { direction: "zero", text: "0.0 pp" });
check("missing value is a dash", formatDelta(null), { direction: "na", text: "–" });
check("NaN is a dash", formatDelta(Number.NaN), { direction: "na", text: "–" });
check("percent needs a base", formatDelta(12, { unit: "%" }), { direction: "na", text: "–" });
check("percent with base below 30 is a dash", formatDelta(12, { unit: "%", base: 29 }), { direction: "na", text: "–" });
check("percent with base 29 is a dash (boundary)", formatDelta(5, { unit: "%", base: 29 }), { direction: "na", text: "–" });
check("percent with base 30 is shown", formatDelta(12, { unit: "%", base: 30 }), { direction: "up", text: "▲ +12.0 %" });
check("pp with a small base is still shown", formatDelta(2, { unit: "pp", base: 10 }), { direction: "up", text: "\u25B2 +2.0 pp" });
check("pp with base 0 is still shown", formatDelta(-1.5, { unit: "pp", base: 0 }), { direction: "down", text: "\u25BC \u22121.5 pp" });
check("pp without a base is shown", formatDelta(2), { direction: "up", text: "▲ +2.0 pp" });
check("thousands separators in large changes", formatDelta(-12345.6, { unit: "%", base: 100, digits: 0 }), { direction: "down", text: "▼ −12,346 %" });
for (const v of [0.1, -0.1, 5, -5, 123.4, -123.4]) {
  const t = formatDelta(v).text;
  check(`every non-dash delta carries an arrow and a sign (${v})`, /^(▲ \+|▼ −)/.test(t), true);
}

console.log("\ntier badges: four distinct looks");
const tiers: Tier[] = ["free", "member", "pro", "enterprise"];
check("four distinct classes", new Set(tiers.map((t) => TIER_CLASS[t])).size, 4);
check("four distinct labels", new Set(tiers.map((t) => TIER_LABEL[t])).size, 4);
check("member label", TIER_LABEL.member, "สมาชิก");
check("MEMBER report maps to member, never free", tierForReport("MEMBER"), "member");
check("PRO report maps to pro", tierForReport("PRO"), "pro");
check("ENTERPRISE report maps to enterprise", tierForReport("ENTERPRISE"), "enterprise");
check("no report tier maps to free", (["MEMBER", "PRO", "ENTERPRISE"] as const).some((t) => tierForReport(t) === "free"), false);

console.log("\nsteps and numbers");
check("stage step clamps high", clampStep(9, 6), 6);
check("stage step clamps low", clampStep(-2, 6), 0);
check("non-finite step is 0", clampStep(Number.NaN, 4), 0);
check("thousands separators", formatNumber(1432), "1,432");
check("strings pass through", formatNumber("62"), "62");

console.log("\ncomponent layer structure");
const css = readFileSync("design/components.css", "utf8");
for (const cls of ["tdr-btn", "tdr-chip", "tdr-tier--free", "tdr-tier--member", "tdr-tier--pro", "tdr-tier--enterprise", "tdr-flag", "tdr-kpi", "tdr-delta", "tdr-card", "tdr-pagehead", "tdr-locked", "tdr-stagebar", "tdr-conf", "tdr-table", "tdr-field", "tdr-input", "tdr-select", "tdr-swatch", "tdr-region"]) {
  check(`components.css defines .${cls}`, new RegExp(`\\.${cls}[\\s{.:,\\[]`).test(css), true);
}
check("no colour literal in components.css (hex, rgb, hsl, or a colour fallback inside var())", /#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(/.test(css), false);
check("member badge is not styled as free", /\.tdr-tier--member\s*\{[^}]*brand-blue/.test(css), true);
const button = readFileSync("components/design/Button.tsx", "utf8");
check("Button has no generic solid-navy primary variant", /\bprimary\b/.test(button.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "")), false);
check("Button defaults to secondary", /variant = "secondary"/.test(button), true);
check("contact is the only navy button", /\.tdr-btn--contact\s*\{[^}]*action-primary/.test(css) && !/\.tdr-btn--primary/.test(css), true);
const chip = readFileSync("components/design/Chip.tsx", "utf8");
check("toggle Chip accepts button attributes (onClick, disabled, aria-*)", /ButtonHTMLAttributes<HTMLButtonElement>/.test(chip) && /\.\.\.rest\} type=/.test(chip), true);
check("Chip holds no filter state", /useState|useReducer/.test(chip), false);
const locked = readFileSync("components/design/LockedBlock.tsx", "utf8");
check("LockedBlock takes no children (no real values in the DOM)", /children/.test(locked.replace(/\/\*[\s\S]*?\*\//g, "")), false);
const files = readdirSync("components/design").filter((f) => f.endsWith(".tsx"));
check("no component reaches for car-brand logos", files.some((f) => /resolveBrandLogo|logo_url/.test(readFileSync(`components/design/${f}`, "utf8"))), false);

console.log(failed ? `\n${failed} check(s) failed` : "\nall design component checks passed");
process.exit(failed ? 1 : 0);
