// Dev/test bridge: builds a canonical batch payload with the exact same
// lib/canonical-command-builder.ts#buildTrimEditBatch() the Vehicle Editor's
// app/admin/vehicle-editor-actions.ts#prepareTrimEdit uses, and prints
// it to stdout as JSON.
//
// automotive/vehicle_master/tests/test_admin_editor_sibling_preservation.py
// invokes this via subprocess so its regression test feeds the REAL,
// production TypeScript builder output into the REAL Python canonical
// writer -- not a hand-written JSON fixture that only resembles what the
// editor produces.
//
// Usage: node --experimental-strip-types scripts/print-market-trim-edit-command.ts < args.json
// where args.json is a MarketTrimEditArgs object (see canonical-command-builder.ts).
import { buildTrimEditBatch, type TrimEditArgs } from "../lib/canonical-command-builder.ts";

let raw = "";
process.stdin.setEncoding("utf8");
for await (const chunk of process.stdin) raw += chunk;

const args = JSON.parse(raw) as TrimEditArgs;
const { payload } = buildTrimEditBatch(args);
process.stdout.write(JSON.stringify(payload));
