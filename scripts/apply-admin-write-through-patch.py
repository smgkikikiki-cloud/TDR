from pathlib import Path


def replace_once(path: str, old: str, new: str):
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"anchor not found in {path}: {old[:120]!r}")
    p.write_text(text.replace(old, new, 1))


actions = "app/admin/vehicle-editor-actions.ts"
replace_once(
    actions,
    '  findDuplicateMarketTrim, isStaleRelease, applySourceRefEdits,\n',
    '  findDuplicateMarketTrim, applySourceRefEdits,\n',
)
replace_once(
    actions,
    'import { loadVehicleWorkspace, liveModelReleaseId } from "@/lib/canonical-editor";\n',
    'import { loadVehicleWorkspace } from "@/lib/canonical-editor";\n',
)
replace_once(
    actions,
    '''Both build a canonical batch and write it: the editor owns this data, so
 * Save is the decision, not a request for one. The only thing standing
 * between the form and the write is integrity -- the release the page was
 * rendered from must still be the live one, so a save cannot silently
 * overwrite an edit that landed while the form sat open -- and
 * enqueueCanonicalInputBatch's (batch_key, payload-hash) idempotency, so a
 * retry after a transient failure resolves to the same batch instead of
 * losing the edit or writing it twice.
''',
    '''Both build a canonical batch and write it: the editor owns this data, so
 * Save is the decision, not a request for one. Saves are compiled against the
 * latest workspace at submit time and inserted durably into canonical_input_batches
 * immediately; the editor reads those pending writes through while GitHub/release
 * publication finishes in the background. Batch-key/payload-hash idempotency keeps
 * retries from losing an edit or writing it twice.
''',
)
replace_once(
    actions,
    '''function assertNotStale(pageReleaseId: string, liveReleaseId: string) {
  if (isStaleRelease(pageReleaseId, liveReleaseId)) {
    throw new Error(
      "มี canonical release ใหม่ออกมาระหว่างที่เปิดหน้านี้ ข้อมูลบนหน้าจอจึงอาจไม่ตรงกับของจริงแล้ว "
      + "กรุณากด refresh หน้านี้แล้วแก้ไขใหม่อีกครั้ง (กันการเขียนทับข้อมูลที่เพิ่งอัปเดตไป)",
    );
  }
}

''',
    '',
)
replace_once(
    actions,
    '''  const modelId = requiredField(formData, "model_id", "canonical model");
  const pageReleaseId = requiredField(formData, "page_release_id", "release fingerprint");
  const workspace = await loadWorkspaceOrThrow(modelId);
  assertNotStale(pageReleaseId, workspace.releaseId);
''',
    '''  const modelId = requiredField(formData, "model_id", "canonical model");
  const workspace = await loadWorkspaceOrThrow(modelId);
''',
)
replace_once(
    actions,
    '''  const modelId = requiredField(formData, "model_id", "canonical model");
  const pageReleaseId = requiredField(formData, "page_release_id", "release fingerprint");
  const workspace = await loadWorkspaceOrThrow(modelId);
  if (!workspace.generation) throw new Error("รุ่นนี้ไม่มี active generation ให้เพิ่ม/แก้ MarketTrim");

  // A release activating under an open form is an ordinary race, not a bug:
  // the admin needs to see it on the page they are typing in.
  if (isStaleRelease(pageReleaseId, workspace.releaseId)) {
    return {
      fieldErrors: {},
      formError: "มี canonical release ใหม่ออกมาระหว่างที่เปิดหน้านี้ ข้อมูลบนหน้าจอจึงอาจไม่ตรงกับของจริงแล้ว "
        + "กรุณา refresh หน้านี้แล้วแก้ไขใหม่อีกครั้ง",
    };
  }
''',
    '''  const modelId = requiredField(formData, "model_id", "canonical model");
  const workspace = await loadWorkspaceOrThrow(modelId);
  if (!workspace.generation) throw new Error("รุ่นนี้ไม่มี active generation ให้เพิ่ม/แก้ MarketTrim");
''',
)

editor = "lib/canonical-editor.ts"
replace_once(
    editor,
    'import { normalizeTrimForEditor, type NormalizedTrim } from "@/lib/trim-editor-state";\n',
    'import { normalizeTrimForEditor, type NormalizedTrim } from "@/lib/trim-editor-state";\nimport { applyPendingCanonicalBatches } from "@/lib/canonical-pending-overlay";\n',
)
replace_once(
    editor,
    '''  code: string;
  segment: string | null;
  launched: string | null;
''',
    '''  code: string;
  segment: string | null;
  seats: number | null;
  launched: string | null;
''',
)
replace_once(
    editor,
    '      ? db.from("current_vehicle_generations").select("canonical_id,model_id,code,segment,launched,ended").eq("canonical_id", model.generation_id).maybeSingle()\n',
    '      ? db.from("current_vehicle_generations").select("canonical_id,model_id,code,segment,launched,ended,payload").eq("canonical_id", model.generation_id).maybeSingle()\n',
)
replace_once(
    editor,
    '    db.from("canonical_vehicle_releases").select("release_id,as_of,payload").eq("release_id", model.release_id).maybeSingle(),\n',
    '    db.from("canonical_vehicle_releases").select("release_id,as_of,created_at,payload").eq("release_id", model.release_id).maybeSingle(),\n',
)
replace_once(
    editor,
    '''  }));

  // canonical_input_batches carries no model FK; a batch is "related" when its
''',
    '''  }));

  // The queue insert is the Admin save. Read it through immediately so a
  // redirect/refresh shows the value the owner just entered while canonical
  // publication catches up asynchronously. Failed writes never overlay, and a
  // published write disappears once the active release represents it.
  applyPendingCanonicalBatches({
    modelId,
    activeReleaseCreatedAt: (release as any)?.created_at || null,
    model,
    generation: generation as any,
    trims: trimRows,
    fields,
    batches: (batches || []) as any[],
  });

  // canonical_input_batches carries no model FK; a batch is "related" when its
''',
)
replace_once(
    editor,
    '''      canonicalId: generation.canonical_id, modelId: generation.model_id, code: generation.code,
      segment: generation.segment, launched: generation.launched, ended: generation.ended,
''',
    '''      canonicalId: generation.canonical_id, modelId: generation.model_id, code: generation.code,
      segment: generation.segment,
      seats: Number.isFinite(Number((generation as any).seats ?? (generation as any).payload?.seats))
        ? Number((generation as any).seats ?? (generation as any).payload?.seats) : null,
      launched: generation.launched, ended: generation.ended,
''',
)

page = "app/admin/(secure)/vehicles/[modelId]/page.tsx"
replace_once(
    page,
    '      บันทึก {KIND_LABEL[saved] || "canonical"} แล้ว — ระบบกำลังเขียนและ publish ให้อัตโนมัติ ใช้เวลาสักครู่แล้วรีเฟรช\n',
    '      บันทึก {KIND_LABEL[saved] || "canonical"} แล้ว — ค่าที่แก้แสดงทันที ส่วน canonical/GitHub publish ทำงานต่อเบื้องหลัง\n',
)
replace_once(
    page,
    '      <label className="adminField"><span>Seats (ปัจจุบัน: {(generation as any)?.seats || "—"})</span><input name="seats" type="number" min="1" step="1" /></label>\n',
    '      <label className="adminField"><span>Seats (ปัจจุบัน: {generation?.seats || "—"})</span><input name="seats" type="number" min="1" step="1" /></label>\n',
)

check = "scripts/check-trim-editor.ts"
replace_once(
    check,
    '''const {
  buildTrimEditBatch, diffTrimEdit, describeValue, composeReason,
  findDuplicateMarketTrim, isStaleRelease, applySourceRefEdits, normalizedTrimName,
} = await import("../lib/canonical-command-builder.ts");
''',
    '''const {
  buildTrimEditBatch, diffTrimEdit, describeValue, composeReason,
  findDuplicateMarketTrim, isStaleRelease, applySourceRefEdits, normalizedTrimName,
} = await import("../lib/canonical-command-builder.ts");
const { applyPendingCanonicalBatches, batchNeedsOptimisticOverlay } =
  await import("../lib/canonical-pending-overlay.ts");
''',
)
replace_once(
    check,
    '''  ok("a stale release comes back to the form too, not as a crash",
    /isStaleRelease\(pageReleaseId, workspace\.releaseId\)\)\s*\{\s*return/.test(actions));
''',
    '''  ok("an old page release no longer blocks an Admin save",
    !/isStaleRelease\(pageReleaseId, workspace\.releaseId\)/.test(actions)
    && !/const pageReleaseId = requiredField\(formData, "page_release_id"/.test(actions));
''',
)
marker = '''// =====================================================================
console.log("\\nsource-text regression — the shape the mandate requires");
// =====================================================================
'''
p = Path(check)
text = p.read_text()
if marker not in text:
    raise SystemExit("trim-editor optimistic overlay test insertion anchor missing")
overlay_test = '''// =====================================================================
console.log("\\nTEST 11 — Admin save is read-through while canonical publication is pending");
// =====================================================================
{
  const trimId = "aion.aion_ut.gen1.trim.400_standard_range_bev";
  const trim = {
    canonicalId: trimId,
    name: "420 Standard",
    powertrain: "BEV",
    sourceRefs: {},
    editor: normalizeTrimForEditor({
      payload: { specs: { name: "420 Standard", powertrain: "BEV", battery_kwh: 50.27 } },
      fields: FIELDS, canonicalId: trimId, generationId: "aion.aion_ut.gen1",
      name: "420 Standard", powertrain: "BEV",
    }),
  };
  const model = { name_en: "Aion UT", name_th: "ไอออน ยูที", body_type: "HATCHBACK" };
  const generation = {
    code: "gen1", segment: "B", seats: 5, launched: "2025-06-24", ended: null,
    payload: { seats: 5 },
  };
  applyPendingCanonicalBatches({
    modelId: "aion.aion_ut",
    activeReleaseCreatedAt: "2026-09-26T06:39:28Z",
    model, generation, trims: [trim], fields: FIELDS,
    batches: [{
      status: "QUEUED", created_at: "2026-09-26T07:00:00Z",
      payload: { commands: [
        {
          operation: "UPSERT_MODEL_BUNDLE", canonical_id: "aion.aion_ut",
          payload: {
            model: { name_en: "Aion UT live" }, generation: { code: "gen1", seats: 5 },
            trims: [{ canonical_id: trimId, name: "420 Standard", powertrain: "BEV", battery_kwh: 51 }],
          },
        },
        {
          operation: "APPEND_SPEC", canonical_id: trimId,
          payload: {
            trim_id: trimId, field_key: "powertrain.max_power_kw", value_state: "KNOWN", value: 100,
            qualifiers: { output_scope: "MOTOR" },
          },
        },
      ] },
    }],
  });
  check("queued MarketTrim value is visible immediately", trim.editor.editableSpecs.battery_kwh.value, "51");
  check("queued spec value is visible immediately", trim.editor.editableSpecs.max_power_kw.value, "100");
  check("queued spec qualifiers survive read-through", trim.editor.editableSpecs.max_power_kw.qualifiers.output_scope, "MOTOR");
  check("queued model edit is visible immediately", model.name_en, "Aion UT live");
  ok("a queued write remains visible even if another release appeared later",
    batchNeedsOptimisticOverlay({ status: "QUEUED", created_at: "2026-09-26T06:00:00Z" }, "2026-09-26T07:00:00Z"));
  ok("failed writes never overlay",
    !batchNeedsOptimisticOverlay({ status: "FAILED", created_at: "2026-09-26T08:00:00Z" }, "2026-09-26T07:00:00Z"));
  ok("a published write already covered by the active release stops overlaying",
    !batchNeedsOptimisticOverlay({ status: "PUBLISHED", created_at: "2026-09-26T06:00:00Z" }, "2026-09-26T07:00:00Z"));
}

'''
p.write_text(text.replace(marker, overlay_test + marker, 1))
