# PEE real-OEM shadow pilot — JAECOO 5 EV Thailand — 2026-10-12

Issue: smgkikikiki-cloud/TDR#222. Branch `claude/pee-oem-shadow-pilot`, base
`4e7b3adb537e04b7a995d99b525b66aae30d921f` (QA-accepted PR #215 HEAD, verified
with `git rev-parse HEAD`). Engine/source code unchanged.

## Outcome (updated): `CAPTURE_BLOCKED_RIGHTS_UNCLEAR` — no measurements taken

Round 1 was blocked by network policy (section below). After the owner allowed the
host, round 2 (addendum at the end) cleared the network and robots.txt but stopped
on the site's own terms. No vehicle page has been fetched in either round.

| Item | Value |
|---|---|
| Target / source | `jaecoo_th_j5_model` / `official_jaecoo_th` |
| URL | `https://www.omodajaecoo.co.th/th/model/jaecoo-5-ev` (role `CURRENT_MODEL_PAGE`) |
| Live fetch performed | **No** |
| Snapshot hash / captured-at / `source_batch_id` | none — nothing was captured |
| P3 claims, PEE disposition, P4 matches | not run |
| Price-change detection | `PRICE_CHANGE_DETECTION_NOT_TESTED` (and no timepoint at all) |
| Verdict | `NO_TESTABLE_PRICE_EVIDENCE` — not a PASS |

## Permission determination (step 2) — unresolved, so capture stopped

1. **Network obstacle.** This cloud session's network policy denies the host:
   `curl https://www.omodajaecoo.co.th/robots.txt` fails with
   `CONNECT tunnel failed, response 403`; the agent proxy status lists
   `connect_rejected ... host www.omodajaecoo.co.th:443` (2026-10-12T13:32Z).
   This is a policy denial of the gateway, not an answer from the OEM site.
2. **`tools/robots_check.py` gave a false "allowed".** Run as-is it reports
   `official_jaecoo_th: robots_txt=false, may_fetch=true, verdict "allowed: no
   robots.txt"`. That is wrong evidence here: `fetch()` catches
   `URLError`/`TimeoutError` and returns `""`, so "unreachable" is
   indistinguishable from "site has no robots.txt". (A 403 CONNECT surfaces as
   `URLError`.) I did **not** treat it as permission.
   Narrow remediation (not applied, per "source unchanged"): make `fetch()`
   return `None` on error and have `verdict()` report
   `unknown: robots.txt unreachable` (exit non-zero). Separate small PR.
3. **Not obtained:** the site's actual robots.txt/Content-Signal, and the
   publisher's terms/permission for storing snapshots. Without them there is no
   documented fetch/storage decision, so per the issue: STOP, no bypass, no
   substitute data. The repo's existing P3 pilot note
   (`P3_LIVE_PILOT_2026_09_09.md`) records 2026-09 observations only as
   interpretation notes; those are not raw snapshots and were not used as a
   timepoint.

## Not done (and why)

- Steps 3–5 (CLI run, report inspection, worksheet of extracted facts): no
  data. No worksheet rows were written; inventing `PROPOSED_PENDING_OWNER_REVIEW`
  rows without a real source would be fabrication. Nothing is labelled
  `OWNER_LABELLED`.
- No Production/Supabase/Price Ledger writes, no paid AI (provider unset), no
  polling, no merge, #215 untouched.

## Regression check

`python3 -m unittest tests.test_price_event_engine tests.test_price_event_fact_binding tests.test_price_event_shadow` — **135 passed** (pytest, 104 s) on this branch; only this markdown file changed.

## Owner decisions needed to unblock

1. Allow `www.omodajaecoo.co.th` (443) in this environment's network policy
   (Allowed domains), restricted to the one target + `/robots.txt`.
2. Owner/legal decision on snapshot storage rights for omodajaecoo.co.th
   (terms page not reviewed — unreachable). Keep snapshots in `/tmp`, commit
   only hash + short necessary snippets.
3. Decide whether to fix `robots_check.py` fail-open behaviour first.

After 1–2, rerun the exact CLI from the issue (step 3) once.

## STOP / GO for additional OEM sources

**STOP.** No evidence from any OEM yet; expanding would repeat the same
unverified-permission problem.

---

# Addendum — round 2 (2026-10-12, after network allow-listing)

## 1. Robots (HTTP evidence)

`GET https://www.omodajaecoo.co.th/robots.txt` → **HTTP 200**, 125 bytes:
`User-Agent: *`, `Allow: /`, `Disallow: /admin`, `/api`, `/hidden`, plus a
Sitemap line. No `Content-Signal`, no AI-agent blocks. Target path
`/th/model/jaecoo-5-ev` is not disallowed. **Robots: permitted.**

## 2. Website terms (read from the official `/en/legal-notices` page, HTTP 200, linked from the footer of every page; the Thai page is the same notice)

Page text is kept in /tmp only; short necessary quotes below.

- No clause mentions crawlers, bots, scraping or automated access. The page's own
  `<meta name="robots">` is `index, follow, nocache`.
- §2: site content is "for informational purposes only"; prices are
  "recommended for sale to the public" and dealer prices may differ; the company
  does not guarantee accuracy or timeliness.
- §6 Intellectual Property: all content is protected by copyright; the user
  "cannot reproduce, modify, distribute, transmit, publish, assign, sell or market
  in any way" the site's elements "or create new products or services derived from
  the information obtained"; and "only … the visualization and loading of the
  Website for personal and non-commercial use" is authorised, "without it being
  able to extend it to third persons or entities".
- No explicit licence for snapshot storage or machine processing is given anywhere.

## 3. Permission decision: **UNRESOLVED → capture NOT performed**

Robots allows the path, but the terms limit use to personal, non-commercial
viewing and bar derived products/services. TDR is a commercial intelligence
product, and the pilot would store a snapshot and derive price facts for it. That
is at best unclear and plausibly outside the licence. Per the issue ("if rights
are unclear or disallowed, stop"), no live fetch was made, no data substituted, no
review table fabricated.

Exact blocker: **written owner/legal determination (or a licence/permission from
OMODA & JAECOO Thailand) that TDR may fetch, store a transient snapshot of, and
extract price facts from the public model page for internal evaluation.**
Options for the owner: (a) obtain permission from the OEM; (b) legal sign-off that
internal, non-published, price-fact extraction of a public recommended price is
acceptable; (c) pilot on a source whose terms permit it, or on owner-provided
snapshots. A narrow low-risk reading (one GET, `/tmp` only, hash + facts committed,
no raw page) is available, but it is the owner's call, not mine.

## 4. Robots fail-closed fix (PR #223 equivalent)

Reviewed PR #223 head `b28c4028` and applied its three commits with
`git cherry-pick -x` (44674fca → 19637a12, 6578b317 → 4683b4a7,
b28c4028 → 0bd12988); they applied cleanly, touching only `tools/robots_check.py`,
`tools/pricefetch_targets.py` and a new `tests/test_robots_check_fail_closed.py`.
Changes: `fetch()` returns `None` on 403/429/5xx/transport errors (only 404/410 mean
"absent"); `audit()` reports `UNREACHABLE` → verdict `unknown: robots.txt
unreachable`; `can_fetch` is evaluated on the actual URL path; the CLI cache is
keyed by full URL. Tests: `pytest tests/test_robots_check_fail_closed.py
tests/test_price_event_engine.py tests/test_price_event_fact_binding.py
tests/test_price_event_shadow.py` → **146 passed**. `robots_check.py` now returns
`PRESENT … allowed` for this host. Note `robots_check.py --url` still audits origin
roots (`checked_url` = origin for registry sources); the per-path check happens in
`pricefetch_targets.py`.

## 5. Not done

Steps 3–4 (single fetch; P3/PEE/P4 evaluation; human-review table):
`NO_TESTABLE_PRICE_EVIDENCE`, `PRICE_CHANGE_DETECTION_NOT_TESTED`. No Production,
Supabase, paid-AI or polling activity. Nothing merged.

## 6. STOP / GO

**STOP** capture and expansion pending the rights determination above. On a
written GO, rerun the single CLI from the issue once.
