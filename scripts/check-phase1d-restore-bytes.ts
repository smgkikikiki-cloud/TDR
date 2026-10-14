import assert from "node:assert/strict";
import { gzipSync } from "node:zlib";
import { decompressPrivateBackupJson } from "../lib/vehicle-engine/private-backup-json.ts";

const source = Buffer.from('{"decimal":405.0,"unit":1.0,"integer":405}', "utf8");
const prepared = decompressPrivateBackupJson(gzipSync(source));

assert.deepEqual(prepared, source, "restore preparation must preserve every decompressed JSON byte");
assert.equal(prepared.toString("utf8"), '{"decimal":405.0,"unit":1.0,"integer":405}');
assert.notEqual(
  JSON.stringify(JSON.parse(prepared.toString("utf8"))),
  prepared.toString("utf8"),
  "fixture must demonstrate why parse/stringify is unsafe for the restore path",
);

console.log("PASS private backup restore preparation preserves 405.0 and 1.0 JSON tokens byte-for-byte");
