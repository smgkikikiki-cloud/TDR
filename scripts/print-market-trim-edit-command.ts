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
// where args.json is a TrimEditArgs object minus `fields` (see
// canonical-command-builder.ts). The field catalog is resolved here from the
// real comparable-spec registry, exactly as the editor page resolves it, so
// the caller cannot accidentally test against an invented field list.
import { buildTrimEditBatch, type TrimEditArgs } from "../lib/canonical-command-builder.ts";
import { loadSpecFieldRegistry } from "../lib/spec-field-registry.ts";
import { resolveTrimEditorFields, fieldAppliesTo } from "../lib/trim-editor-fields.ts";

let raw = "";
process.stdin.setEncoding("utf8");
for await (const chunk of process.stdin) raw += chunk;

const args = JSON.parse(raw) as Omit<TrimEditArgs, "fields">;
const fields = resolveTrimEditorFields(loadSpecFieldRegistry(args.year))
  .filter((field) => fieldAppliesTo(field, args.identity.powertrain));
const { payload } = buildTrimEditBatch({ ...args, fields });
process.stdout.write(JSON.stringify(payload));
