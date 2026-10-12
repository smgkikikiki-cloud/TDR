/** lib/price-refresh/fetcher.ts: robots.txt reading only (the browser itself is exercised in CI). */
import { robotsAllows, sha256 } from "../lib/price-refresh/fetcher.ts";
let failed = 0, passed = 0;
const ok = (n: string, c: unknown) => { if (c) passed++; else { failed++; console.log("  FAIL " + n); } };
const R = "User-agent: *\nDisallow: /admin\nDisallow: /search?\nAllow: /admin/public\n\nUser-agent: badbot\nDisallow: /\n";
ok("open path", robotsAllows(R, "/model/yaris"));
ok("disallowed prefix", !robotsAllows(R, "/admin/x"));
ok("longest allow wins", robotsAllows(R, "/admin/public/a"));
ok("other bot's group does not apply", robotsAllows(R, "/model"));
ok("own group beats *", !robotsAllows("User-agent: *\nDisallow:\n\nUser-agent: TDR-PriceBot\nDisallow: /model\n", "/model/a"));
ok("empty disallow = allow all", robotsAllows("User-agent: *\nDisallow:\n", "/x"));
ok("comments ignored", !robotsAllows("User-agent: * # all\nDisallow: /p # private\n", "/p/1"));
ok("no robots content", robotsAllows("", "/x"));
ok("hash is stable", sha256("a") === sha256("a") && sha256("a") !== sha256("b"));
console.log(failed ? `${failed} FAILED, ${passed} passed` : `all ${passed} price-fetcher cases passed`);
process.exit(failed ? 1 : 0);
