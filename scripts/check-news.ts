import fs from "node:fs";
import { BREAKING_WINDOW_HOURS, isBreaking, parseExternalLinks, parseTagNames, splitParagraphs } from "../lib/news-format.ts";

let failed = 0;
function check(name: string, got: unknown, want: unknown = true) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { failed++; console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`); }
  else console.log(`  ok   ${name}`);
}

console.log("news — breaking badge window");
const now = Date.parse("2026-10-16T12:00:00Z");
const ago = (h: number) => new Date(now - h * 3600_000).toISOString();
check("window is 24h", BREAKING_WINDOW_HOURS, 24);
check("1h old story is breaking", isBreaking(ago(1), now));
check("25h old story is not", isBreaking(ago(25), now), false);
check("future / null / garbage are not", [isBreaking(ago(-2), now), isBreaking(null, now), isBreaking("x", now)], [false, false, false]);

console.log("\nnews — body, tags, links");
check("blank line splits paragraphs", splitParagraphs("a\nb\n\n\n c \r\n\r\nd"), ["a\nb", "c", "d"]);
check("tags: trim, dedupe, strip #", parseTagNames("EV, #ev ,ภาษี\nToyota,,"), ["EV", "ภาษี", "Toyota"]);
check("links: title | url", parseExternalLinks("ข่าวเดิม | https://a.example/x\nhttps://b.example"),
  [{ title: "ข่าวเดิม", url: "https://a.example/x" }, { title: "https://b.example", url: "https://b.example" }]);
let threw = false; try { parseExternalLinks("x | javascript:alert(1)"); } catch { threw = true; }
check("non-http link is rejected", threw);

console.log("\nnews — migration posture");
const sql = fs.readFileSync("supabase/migration_v71_news.sql", "utf8");
check("RLS on all four tables", (sql.match(/enable row level security/g) || []).length, 4);
check("anon/authenticated revoked", sql.includes("from public, anon, authenticated"));
check("published rows must carry a timestamp", sql.includes("news_articles_published_has_timestamp"));

if (failed) { console.log(`\n${failed} failed`); process.exit(1); }
console.log("\nall news checks passed");
