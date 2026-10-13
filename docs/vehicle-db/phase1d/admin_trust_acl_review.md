# Phase 1D — TDR Admin trust and ACL review

**Verdict: `ADMIN_AUTH_ACCEPTANCE_BLOCKED`.** The repository Admin code was reviewed directly, and a focused test invokes its real authentication/token helpers. That is evidence about this checkout's helper semantics only. No authorized deployed Admin configuration, DB role snapshot, current session, or immutable approval decision record was available; no live account was queried.

## Actual application boundary in this checkout

- `lib/admin-auth.ts` authenticates either named password pairs in `TDR_ADMIN_USERS` or a shared `TDR_ADMIN_PASSWORD`. With the shared password, the entered display name is accepted as the editor label; that label is not a stable authenticated principal.
- The `tdr_admin_session` cookie is an HMAC-SHA256 token made from `admin:<encoded name>:<timestamp>`, signed using `ADMIN_SESSION_SECRET`, with a 30-day age limit. `currentEditor()` returns only `{ name }`; there is no immutable user ID, issuer ID, permission version, revocation record, or approval ID in this contract. The cookie is HTTP-only and SameSite Lax; production sets Secure.
- `app/admin/actions.ts` checks `isAdmin()` before many legacy admin actions. Those actions commonly obtain `adminDb()` and enqueue through the older canonical input pipeline. This route is not the Phase 1C structural RPC boundary and does not mint a verified database capability.
- `lib/supabase.ts` uses the server-side Supabase secret/service-role key for `adminDb()` requests. This repository code shows the privileged credential path, but not the deployed key, grants, gateway session binding, or restrictions in the live database.
- The Phase 1C SQL RPC uses separate PostgreSQL issuer and executor roles, `session_user`, operation/payload/expiry/nonce binding, and the 61-case isolated regression suite. Its `p_admin_evidence_ref` is validated as nonblank text and recorded. No repository-connected verifier checks that reference against the actual TDR Admin login, a stable principal, or an immutable approval ledger. A local test issuer role is not a production Admin identity.
- `BasicIdentityDbAdapter.submit()` remains fail-closed; no structural RPC route/adapter is connected.

## Tested and unverified

`npm run check:phase1d-admin-contract` runs actual `authenticate`, `makeAdminToken` and `readAdminToken` helpers with temporary process-only test credentials. It checks valid/invalid named credentials, signed-cookie round-trip and tamper rejection, and confirms the shared-password fallback accepts a supplied label. It uses no live credentials and writes no session/cookie to an external system.

Not proven: real deployment secret/credential mode; named editor-to-person identity mapping; current login/logout/session revocation; immutable approval-record source and uniqueness; Admin actor to DB issuer mapping; DB grants/RLS/owners on deployed PostgreSQL; inability of service-role holders to invoke or grant structural approval; expiry/revocation binding; real route-to-RPC call context; approval receipt audit/replay in the deployed system. Static repository policy can say `isAdmin()` is checked at some server actions, but it cannot establish that a deployed database verifies the same person or a separately approved request.

| Threat case | Existing executable evidence | Production Admin contract result |
|---|---|---|
| Regular user / direct DML | Phase 1C isolated PostgreSQL asserts unprivileged table DML denied | Deployed grants and Admin gateway not verified |
| Issuer/executor separation, inherited roles, self-issue | Phase 1C isolated PostgreSQL asserts distinct issuer/executor roles and denied role combinations | Role memberships in live DB unavailable |
| Fake JWT/custom session claims | Phase 1C RPC audit uses `session_user` and rejects spoofed custom session settings; focused Admin helper test rejects tampered HMAC cookie | No real request-to-DB identity propagation evidence |
| Agent/propose-only principal and service-role direct RPC | Phase 1C isolated SQL denies service-role RPC execution and requires database issuer/executor role | No live service-role grant/RPC inventory |
| Expired capability, approval replay, actor rebind | Phase 1C SQL tests expired capability rejection, authorized same-approval replay and cross-principal replay denial | No TDR session revocation or immutable Admin approval lookup |
| Forged nonempty approval reference | Phase 1C RPC validates nonblank text and binds it immutably to isolated approval row | It does not prove the text reference names a genuine TDR Admin approval; remains blocked |
| Expired/revoked Admin session | Helper test covers bad signature and missing signing secret | No Admin session revocation source; expired valid tokens not independently tested against deployed clock/config |

## Minimum future contract (not implemented as a writer)

An independently approved bridge must resolve the signed Admin session server-side to a stable principal, persist a separately authorized immutable approval record, and bind that record to a canonical payload/batch hash, exact operation set, distinct executor, expiry, nonce, revocation state and single-use receipt. The executor identity must derive from trusted server/DB context, never request JSON or a service-role key alone. The RPC must look up and verify the approval record, not accept a nonempty reference. Tests need actual authorization guards and DB roles with negative regular-user, propose-only, forged/fake-admin, expired/revoked, cross-actor, inherited-role, replay, direct-DML and service-role cases. Independent security review and owner approval are required before any numbered migration.

No Admin credentials, production capabilities, grant edits, or production calls were used.
