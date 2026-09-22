/** Checks for the two pieces of catalogue logic that have no other test.
 *
 *  This repository has no test runner and adding one was not the job, so these
 *  run on Node's own type stripping: `npm run check`. They cover the parts that
 *  are easy to get quietly wrong and impossible to see without the database —
 *  which name gets printed, and what order the grid comes out in.
 */

import { displayName, initials, titleFromSlug } from "../lib/display-name.ts";
import { byRelevance, freshness } from "../lib/relevance.ts";

let failed = 0;
function check(name: string, got: unknown, want: unknown) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) {
    failed++;
    console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`);
  } else {
    console.log(`  ok   ${name}`);
  }
}

console.log("display name — model and brand names are shown in Latin only");
check("name_en wins when it has one",
  displayName({ name_en: "Yaris Ativ", name_th: "ยารีส เอทีฟ", slug: "toyota-yaris-ativ" }), "Yaris Ativ");
check("no name_en falls back to the slug, never to the Thai name",
  displayName({ name_en: "", name_th: "ยารีส เอทีฟ", slug: "toyota-yaris-ativ" }), "Toyota Yaris Ativ");
check("a name_en that is itself Thai is not trusted",
  displayName({ name_en: "ยารีส", name_th: "ยารีส", slug: "yaris" }), "Yaris");
check("a short slug word is a marque or a code, not a word",
  titleFromSlug("bmw-x5"), "BMW X5");
check("a slug is lower case, so digits cannot mean 'already capitalised'",
  displayName({ name_en: null, name_th: "เอ็มจี 4", slug: "mg4" }), "MG4");
check("longer slug words are ordinary words", titleFromSlug("toyota-hilux-revo"), "Toyota Hilux Revo");
check("a row with neither is not left nameless", displayName(null, "—"), "—");
check("initials for a brand with no logo", initials({ name_en: "Toyota" }), "TO");

console.log("\nfreshness — as at September 2026");
const now = new Date(2026, 8, 8);
check("launched this year", freshness({ launch_year: 2026, launch_month: 6 }, now), 1);
check("not launched yet", freshness({ launch_year: 2027 }, now), 1);
check("two years old", Math.round(freshness({ launch_year: 2024, launch_month: 9 }, now) * 100) / 100, 0.75);
check("over five years old", freshness({ launch_year: 2019 }, now), 0);
check("launch year unknown", freshness({}, now), 0);

console.log("\nordering — best sellers and new launches lead, old cars do not");
const models = [
  { id: "old", body_type: "Pickup truck", launch_year: 2018, name_en: "Old Pickup" },
  { id: "seller", body_type: "Pickup truck", launch_year: 2020, name_en: "Best Seller" },
  { id: "new", body_type: "Pickup truck", launch_year: 2026, launch_month: 5, name_en: "Brand New" },
  { id: "suv", body_type: "Crossover", launch_year: 2018, name_en: "Old Crossover" },
];
const sales = new Map([["seller", 90000], ["old", 3000], ["suv", 50]]);
check("a best seller and a new launch both beat an old car",
  byRelevance(models, sales, now).map((m) => m.id), ["seller", "new", "suv", "old"]);
check("an empty registrations table still orders newest first",
  byRelevance(models, new Map(), now).map((m) => m.id), ["new", "old", "seller", "suv"]);
check("the sales scale is per body type, so a pickup is not measured against a coupe",
  byRelevance(models.filter((m) => m.body_type === "Crossover"), sales, now).map((m) => m.id), ["suv"]);

console.log("\nbrand logos — the field the pages render must actually be read");
// Four pages render a logo with an initials fallback. The homepage first runs
// logo_url through resolveBrandLogo(), while the catalogue pages use logo_url
// directly. The assertion cares about the user-visible fallback, not which
// variable name the JSX happens to use.
const fs = await import("node:fs");
const canonical = fs.readFileSync("lib/canonical-data.ts", "utf8");
const brandsLoader = canonical.slice(canonical.indexOf("export async function getCanonicalBrands"));
check("getCanonicalBrands no longer hardcodes a null logo",
  /logo_url: null,\s*\}\)\);/.test(brandsLoader), false);
check("the logo is linked through tdr_brand_id, not a mutable slug",
  brandsLoader.includes("logoByEditorialId.get(row.tdr_brand_id)"), true);
check("a missing editorial table leaves the catalogue standing",
  brandsLoader.includes("if (!editorialError)"), true);
for (const page of ["app/brands/page.tsx", "app/brands/[slug]/page.tsx",
                    "app/models/page.tsx"]) {
  check(`${page} still falls back to initials`,
    /logo_url \? <img[^>]*\/> : <span>\{initials\(/.test(fs.readFileSync(page, "utf8")), true);
}
const homePage = fs.readFileSync("app/page.tsx", "utf8");
check("app/page.tsx still falls back to initials",
  homePage.includes("resolveBrandLogo(brand.slug, brand.logo_url)")
    && /logo \? <img[^>]*\/> : <span>\{initials\(brand\)\}<\/span>/.test(homePage), true);
const backfill = fs.readFileSync("supabase/migration_v37_brand_logos.sql", "utf8");
check("the backfill never overwrites a curated logo",
  backfill.split("\n").filter((line: string) => line.startsWith("update public.brands"))
    .every((line: string) => line.includes("and logo_url is null")), true);

console.log(failed ? `\n${failed} check(s) failed` : "\nall checks passed");
process.exit(failed ? 1 : 0);