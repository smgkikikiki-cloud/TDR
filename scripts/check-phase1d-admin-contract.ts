import assert from "node:assert/strict";
import { authenticate, makeAdminToken, readAdminToken } from "../lib/admin-auth.ts";

// Exercise the repository's real Admin helper implementation with ephemeral
// process-only credentials. These are not deployment credentials or identities.
process.env.ADMIN_SESSION_SECRET = "phase1d-ephemeral-session-secret-not-production";
process.env.TDR_ADMIN_USERS = "qa-editor:qa-password";
delete process.env.TDR_ADMIN_PASSWORD;
assert.equal(authenticate("qa-editor", "qa-password"), "qa-editor");
assert.equal(authenticate("qa-editor", "wrong-password"), null);
assert.equal(authenticate("unknown-editor", "qa-password"), null);

const token = makeAdminToken("qa-editor");
assert.deepEqual(readAdminToken(token), { name: "qa-editor" });
const tampered = `${token.slice(0, -1)}${token.endsWith("0") ? "1" : "0"}`;
assert.equal(readAdminToken(tampered), null);
assert.equal(readAdminToken("not-an-admin-session"), null);

// Structural approval is available only when deployment config binds a named
// editor to a unique immutable principal UUID. Names and shared-password labels
// are never promoted to identities by inference.
process.env.TDR_ADMIN_PRINCIPAL_IDS = JSON.stringify({ "qa-editor": "a4bd30f6-3e6f-4c71-8ec8-5ec6820fe542" });
const structuralToken = makeAdminToken("qa-editor");
assert.deepEqual(readAdminToken(structuralToken), {
  name: "qa-editor", principal_id: "a4bd30f6-3e6f-4c71-8ec8-5ec6820fe542",
});
process.env.TDR_ADMIN_PRINCIPAL_IDS = JSON.stringify({ "qa-editor": "baf7fbe9-37b0-4c54-a96c-0472116942a3" });
assert.equal(readAdminToken(structuralToken), null, "principal remapping revokes existing structural sessions");
process.env.TDR_ADMIN_PRINCIPAL_IDS = JSON.stringify({ "qa-editor": "not-a-uuid" });
assert.deepEqual(readAdminToken(makeAdminToken("qa-editor")), { name: "qa-editor" });

// The deployed fallback accepts a caller-selected display label when one
// shared password is used. This is a verified behavior and a reason the
// display name cannot serve as immutable issuer identity.
delete process.env.TDR_ADMIN_USERS;
process.env.TDR_ADMIN_PASSWORD = "shared-test-password";
process.env.TDR_ADMIN_PRINCIPAL_IDS = JSON.stringify({ "invented-editor-label": "a4bd30f6-3e6f-4c71-8ec8-5ec6820fe542" });
assert.equal(authenticate("invented-editor-label", "shared-test-password"), "invented-editor-label");
assert.equal(authenticate("invented-editor-label", "not-the-password"), null);
assert.deepEqual(readAdminToken(makeAdminToken("invented-editor-label")), { name: "invented-editor-label" },
  "shared password mode cannot mint a structural principal claim");

delete process.env.ADMIN_SESSION_SECRET;
assert.equal(readAdminToken(token), null);
assert.throws(() => makeAdminToken("qa-editor"), /ADMIN_SESSION_SECRET is not set/);

console.log("PASS real lib/admin-auth.ts helper checks: named credentials, HMAC tamper rejection, stable UUID principal claim, remapping revocation, shared-password exclusion, and missing-secret fail-closed");
console.log("BLOCKED: this helper-only isolated test does not verify deployed Admin identity, approval records, DB issuer mapping, or live ACLs");
