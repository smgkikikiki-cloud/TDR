import fs from "node:fs";
import { FEATURES, TIER_POLICIES } from "../lib/access-policy.ts";

let failed = 0;
function check(name: string, got: unknown, want: unknown = true) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { failed++; console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`); }
  else console.log(`  ok   ${name}`);
}

console.log("research — a real content model, not a stub");
const migration = fs.readFileSync("supabase/migration_v38_research_articles.sql", "utf8");
check("articles have a status/publish invariant", migration.includes("research_articles_published_has_timestamp"));
check("RLS is enabled on both tables",
  (migration.match(/enable row level security/g) || []).length >= 2);
check("anon/authenticated are revoked on both tables",
  (migration.match(/revoke all on table .* from public, anon, authenticated/g) || []).length >= 2);
check("only service_role can write research_articles",
  migration.includes("grant select, insert, update, delete on table public.research_articles to service_role"));
check("reads existing = the entitlement is a row, not a counter",
  migration.includes("primary key (user_id, article_id)"));

console.log("\nno anonymous reader ever reaches the full text");
const route = fs.readFileSync("app/api/research/read/route.ts", "utf8");
check("missing bearer token is refused before any query runs",
  /if \(!accessToken\) \{\s*\n\s*return NextResponse\.json/.test(route));
check("only published articles resolve", route.includes('.eq("status", "published")'));
check("an unknown or unpublished slug reads as 404, not leaked draft content",
  route.includes('status: 404'));
check("unlocking is POST, not GET -- it mutates state (spends quota, writes an entitlement row)",
  route.includes("export async function POST(request: NextRequest)"));
check("the route never exports a GET handler that could do the same thing by accident",
  !route.includes("export async function GET"));
const unlockPage = fs.readFileSync("app/research/[slug]/ResearchUnlock.tsx", "utf8");
check("the client actually calls with POST, matching the route",
  /method: "POST"/.test(unlockPage));

console.log("\nrereading an unlocked article never spends quota again");
// The two server-rendered public pages have no legitimate reason to mention
// body_th at all -- neither ever fetches an unlocked article, so any
// occurrence there would be a real leak. ResearchUnlock.tsx is the one
// deliberate exception on the client side: it legitimately RECEIVES body_th
// as response data from the protected route after a successful authenticated
// unlock and has to reference the field name to render it -- that is not a
// query, so it is not a leak.
for (const path of ["app/research/page.tsx", "app/research/[slug]/page.tsx"]) {
  check(`${path} never references body_th`, fs.readFileSync(path, "utf8").includes("body_th"), false);
}
check("the public article page reads the preview-only loader, not the body_th-selecting one",
  fs.readFileSync("app/research/[slug]/page.tsx", "utf8").includes("getPublishedResearchArticlePreviewBySlug"));
const researchLib = fs.readFileSync("lib/research.ts", "utf8");
check("the old body_th-selecting loader is gone, not just unused -- there is nothing left to accidentally import",
  !researchLib.includes("getPublishedResearchArticleBySlug"));
check("no query built in lib/research.ts ever selects body_th -- the one place that still may is the protected route's own inline query",
  !researchLib.includes('.select("id,slug,title_th,summary_th,body_th'));
check("the existence check, quota spend and read-record insert are one atomic RPC call, not three separate round trips",
  route.includes("unlockResearchArticle(ctx, article.id,"));
check("the route itself no longer queries research_article_reads or calls requireUsage directly -- that all moved into the atomic RPC",
  !route.includes('.from("research_article_reads")') && !route.includes("requireUsage("));
const helper = fs.readFileSync("lib/access-policy-server.ts", "utf8");
check("unlockResearchArticle calls the atomic RPC, not the three-step sequence",
  helper.includes('ctx.db.rpc("tdr_unlock_research_article"'));
const unlockMigration = fs.readFileSync("supabase/migration_v50_research_article_unlock_atomic.sql", "utf8");
check("the RPC serializes on an advisory lock keyed by (user, article), not tdr_consume_usage's own fingerprint bucket",
  unlockMigration.includes("perform pg_advisory_xact_lock(hashtextextended("));
check("the RPC is locked down to service_role only, same posture as tdr_consume_usage",
  unlockMigration.includes("revoke all on function public.tdr_unlock_research_article")
  && unlockMigration.includes("grant execute on function public.tdr_unlock_research_article(uuid, uuid, text, integer) to service_role"));

console.log("\nFree's limit is real, not a placeholder");
check("researchAccess (the old binary preview/full gate) is gone",
  !fs.readFileSync("lib/access-policy.ts", "utf8").includes("researchAccess"));
check("Free gets a concrete, decided number of full reads a month",
  TIER_POLICIES.FREE.researchFullMonthlyLimit, 2);
check("Pro is not capped at Free's number -- unlimited", TIER_POLICIES.PRO.researchFullMonthlyLimit, null);
check("the feature is released", FEATURES.research_reports.released, true);
check("Free's ladder state is 'limited', not 'teaser' -- it is a real product now",
  FEATURES.research_reports.stateByAudience.FREE, "limited");
check("the limited-tier policy is declared defined, matching a real number existing",
  FEATURES.research_reports.limitedAccessPolicyDefined, true);

console.log("\nauthoring: the admin surface an editor actually uses");
const actions = fs.readFileSync("app/admin/actions.ts", "utf8");
check("saveResearchArticle requires an admin session",
  /export async function saveResearchArticle[\s\S]{0,40}await requireAdmin\(\)/.test(actions));
check("publishing without a title, summary or body is refused",
  actions.includes('if (!title) throw new Error') &&
  actions.includes('if (!summary) throw new Error') &&
  actions.includes('if (!body) throw new Error'));
check("re-publishing an already-published piece keeps its original date",
  actions.includes("existing?.published_at || new Date().toISOString()"));
const deleteButton = fs.readFileSync("components/admin/DeleteButton.tsx", "utf8");
check("the delete button is wired for research articles", deleteButton.includes("research:deleteResearchArticle"));
const library = fs.readFileSync("app/admin/(secure)/library/page.tsx", "utf8");
check("research_articles is reachable from the generic library viewer",
  library.includes('"research_articles"') && library.includes('add: "/admin/research/new"'));
const nav = fs.readFileSync("components/admin/AdminNav.tsx", "utf8");
// The sidebar's Research door is the internal file library, not the article
// editor. Published articles, their access policy and their quota are
// untouched -- authoring still lives behind the generic library viewer
// (asserted above), it is just not one of the six operator doors.
check("the sidebar's research door is the file library", nav.includes('href="/admin/research"'));
check("article authoring is not an operator door", !nav.includes('href="/admin/research/new"'));

console.log("\npublic pages: everyone sees the list, nobody free-rides the body");
const listPage = fs.readFileSync("app/research/page.tsx", "utf8");
check("the list is real data now, not a hardcoded empty array",
  listPage.includes("getPublishedResearchArticles") && !listPage.includes(": Array<{ id: string;"));
check("an honest empty state survives for a quiet month",
  listPage.includes("ยังไม่มีบทวิเคราะห์เผยแพร่"));
const articlePage = fs.readFileSync("app/research/[slug]/page.tsx", "utf8");
check("a draft or missing slug 404s rather than rendering blank",
  articlePage.includes("if (!article) notFound();"));
check("the summary is server-rendered, so it is public without any client fetch",
  articlePage.includes("article.summaryTh"));
const unlock = fs.readFileSync("app/research/[slug]/ResearchUnlock.tsx", "utf8");
check("an anonymous reader sees a sign-up CTA, never a request that would 401",
  unlock.includes('if (token === null)') && unlock.includes("สมัครฟรี"));
check("a selection survives the login round trip",
  unlock.includes("/member/login?next="));
check("hitting the monthly cap reads as an upgrade path, not a dead end",
  unlock.includes('status === "quota"') && unlock.includes('href="/pricing"'));

const pricing = fs.readFileSync("app/pricing/page.tsx", "utf8");
check("the pricing page's Free bullet states the real number, not an invented one",
  pricing.includes("FREE_POLICY = TIER_POLICIES.FREE") && pricing.includes("FREE_POLICY.researchFullMonthlyLimit"));

console.log(failed ? `\n${failed} check(s) failed` : "\nall research checks passed");
process.exit(failed ? 1 : 0);
