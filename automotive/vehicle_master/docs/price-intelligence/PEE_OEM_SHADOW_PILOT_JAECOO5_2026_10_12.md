# PEE real-OEM shadow pilot — JAECOO 5 EV Thailand — 2026-10-12

Issue: smgkikikiki-cloud/TDR#222. Branch `claude/pee-oem-shadow-pilot`, base
`4e7b3adb537e04b7a995d99b525b66aae30d921f` (QA-accepted PR #215 HEAD, verified
with `git rev-parse HEAD`). Engine/source code unchanged.

## Outcome: `CAPTURE_BLOCKED_NETWORK` — no measurements taken

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
