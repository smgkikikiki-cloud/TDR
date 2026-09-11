"use server";

import { createHash, randomUUID } from "node:crypto";
import { redirect } from "next/navigation";
import { currentEditor, isAdmin } from "@/lib/admin-auth";
import { resolveOemTarget } from "@/lib/price-evidence-registry";
import { adminDb } from "@/lib/supabase";

const SOURCE_KINDS = new Set(["ADMIN", "ECO", "OEM", "MEDIA", "PRICE_HARVEST", "MIGRATION", "API"]);
const QUICK_PRICE_TYPES = new Set(["LIST_PRICE", "INTRODUCTORY_PRICE", "ESTIMATED_PRICE"]);
const SEGMENTS = new Set(["A", "B", "C", "D", "E", "F", "UNKNOWN"]);
const BODY_TYPES = new Set([
  "HATCHBACK", "SEDAN", "CROSSOVER", "PPV", "OFFROAD", "COUPE",
  "MPV", "PICKUP", "WAGON", "VAN", "TRUCK", "OTHER",
]);

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    const row = value as Record<string, unknown>;
    return `{${Object.keys(row).sort().map((key) => `${JSON.stringify(key)}:${canonical(row[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

function field(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value.trim() : "";
}

function requiredField(formData: FormData, name: string, label = name): string {
  const value = field(formData, name);
  if (!value) throw new Error(`กรุณาใส่ ${label}`);
  return value;
}

function isoDate(value: string, label: string, required = false): string | undefined {
  if (!value) {
    if (required) throw new Error(`กรุณาใส่ ${label}`);
    return undefined;
  }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || Number.isNaN(Date.parse(`${value}T00:00:00Z`))) {
    throw new Error(`${label} ต้องเป็น YYYY-MM-DD`);
  }
  return value;
}

function submissionId(formData: FormData): string {
  const value = field(formData, "submission_id") || randomUUID();
  if (!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$/.test(value)) throw new Error("submission_id ไม่ถูกต้อง");
  return value;
}

function submissionTimestamp(formData: FormData): string {
  const value = requiredField(formData, "submitted_at", "submission timestamp");
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime()) || !/(?:Z|[+-]\d{2}:\d{2})$/.test(value)) {
    throw new Error("submission timestamp ต้องเป็น ISO-8601 พร้อม timezone");
  }
  return value;
}

function sourceKind(formData: FormData): string {
  const value = (field(formData, "source_kind") || "ADMIN").toUpperCase();
  if (!SOURCE_KINDS.has(value) || value === "MIGRATION") throw new Error("source.kind ไม่รองรับใน Quick input");
  return value;
}

function priceSourceLabel(kind: string): string {
  return ({
    OEM: "official_oem",
    ECO: "ecosticker",
    MEDIA: "media",
    PRICE_HARVEST: "price_harvest",
    API: "api",
    ADMIN: "admin",
  } as Record<string, string>)[kind] || kind.toLowerCase();
}

async function releaseYear(db: any, releaseId: string): Promise<number> {
  const { data, error } = await db.from("canonical_vehicle_releases")
    .select("payload,as_of").eq("release_id", releaseId).maybeSingle();
  if (error) throw error;
  const payload = data?.payload && typeof data.payload === "object"
    ? data.payload as Record<string, unknown> : {};
  const year = Number(payload.year || String(data?.as_of || "").slice(0, 4));
  if (!Number.isInteger(year) || year < 2000 || year > 2100) {
    throw new Error("หา catalog year ของ active canonical release ไม่ได้");
  }
  return year;
}

async function enqueuePayload(payload: Record<string, unknown>, resultKind: string) {
  if (!(await isAdmin())) redirect("/admin/login");
  if (payload.schema_version !== 1) throw new Error("รองรับเฉพาะ schema_version 1");
  const batchKey = typeof payload.batch_id === "string" ? payload.batch_id.trim() : "";
  if (!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(batchKey)) throw new Error("batch_id ไม่ถูกต้อง");
  const commands = Array.isArray(payload.commands) ? payload.commands : [];
  if (!commands.length || commands.length > 500) throw new Error("commands ต้องมี 1–500 รายการ");
  const source = payload.source && typeof payload.source === "object"
    ? payload.source as Record<string, unknown> : {};
  const kind = String(source.kind || "ADMIN").toUpperCase();
  if (["DLT", "REGISTRATION"].includes(kind)) {
    throw new Error("ข้อมูลจดทะเบียนใช้ registration ingest แยกจาก Vehicle Master");
  }
  if (!SOURCE_KINDS.has(kind)) throw new Error("source.kind ไม่รองรับ");

  const editor = await currentEditor();
  const actor = editor?.name || "tdr-admin";
  const submittedAt = typeof payload.submitted_at === "string" && payload.submitted_at.trim()
    ? payload.submitted_at.trim()
    : new Date().toISOString();
  const normalized = {
    ...payload,
    source: { ...source, kind },
    actor,
    submitted_at: submittedAt,
    commands: commands.map((command) => command && typeof command === "object"
      ? { ...(command as Record<string, unknown>), actor, submitted_at: submittedAt }
      : command),
  };
  const payloadSha256 = createHash("sha256").update(canonical(normalized)).digest("hex");
  const db = adminDb();
  if (!db) throw new Error("ยังไม่ได้ตั้งค่า Supabase server credential");
  const row = {
    domain: "VEHICLE_MARKET",
    batch_key: batchKey,
    source_kind: kind,
    source_ref: typeof source.ref === "string" ? source.ref : null,
    payload: normalized,
    payload_sha256: payloadSha256,
    item_count: commands.length,
    actor,
    status: "QUEUED",
  };
  const { error } = await db.from("canonical_input_batches").insert(row);
  if (error?.code === "23505") {
    const { data: existing } = await db.from("canonical_input_batches")
      .select("payload_sha256").eq("batch_key", batchKey).maybeSingle();
    if (existing?.payload_sha256 !== payloadSha256) {
      throw new Error("batch_id นี้เคยใช้กับข้อมูลคนละชุดแล้ว");
    }
    redirect(`/admin/vehicle-input?queued=duplicate&kind=${encodeURIComponent(resultKind)}`);
  }
  if (error) throw error;
  redirect(`/admin/vehicle-input?queued=1&kind=${encodeURIComponent(resultKind)}`);
}

export async function enqueueVehicleInput(formData: FormData) {
  const raw = formData.get("payload");
  if (typeof raw !== "string" || !raw.trim()) throw new Error("กรุณาใส่ input batch JSON");
  let payload: Record<string, unknown>;
  try { payload = JSON.parse(raw); } catch { throw new Error("input batch ต้องเป็น JSON ที่ถูกต้อง"); }
  if (!payload.submitted_at && field(formData, "submitted_at")) {
    payload.submitted_at = submissionTimestamp(formData);
  }
  return enqueuePayload(payload, "advanced");
}

export async function enqueuePriceInput(formData: FormData) {
  if (!(await isAdmin())) redirect("/admin/login");
  const trimId = requiredField(formData, "trim_id", "MarketTrim");
  const amount = Number(requiredField(formData, "amount_thb", "ราคา"));
  if (!Number.isSafeInteger(amount) || amount <= 0) throw new Error("ราคาต้องเป็นจำนวนเต็มบาทที่มากกว่า 0");
  const priceType = requiredField(formData, "price_type", "ประเภทราคา").toUpperCase();
  if (!QUICK_PRICE_TYPES.has(priceType)) throw new Error("Quick price รองรับ List / Introductory / Estimated เท่านั้น");
  const observedAt = isoDate(requiredField(formData, "observed_at", "วันที่ตรวจพบ"), "วันที่ตรวจพบ", true)!;
  const effectiveFrom = isoDate(field(formData, "effective_from"), "วันที่มีผล");
  const targetId = field(formData, "target_id");
  let kind = sourceKind(formData);
  let sourceRef = field(formData, "source_ref");
  let sourceLabel = priceSourceLabel(kind);
  const reason = requiredField(formData, "reason", "เหตุผล/หลักฐานย่อ");
  const submittedAt = submissionTimestamp(formData);

  const db = adminDb();
  if (!db) throw new Error("ยังไม่ได้ตั้งค่า Supabase server credential");
  const { data: trim, error } = await db.from("current_market_trims")
    .select("canonical_id,release_id,model_id").eq("canonical_id", trimId).maybeSingle();
  if (error) throw error;
  if (!trim?.release_id || !trim.model_id) throw new Error("ไม่พบ MarketTrim นี้ใน active canonical release");

  if (targetId) {
    const target = resolveOemTarget(targetId, String(trim.model_id));
    if (!target) {
      throw new Error("OEM target นี้ไม่อยู่ใน registry หรือไม่ตรง canonical model ของ MarketTrim");
    }
    kind = "OEM";
    sourceRef = target.url;
    sourceLabel = target.sourceId;
  }
  if (priceType === "LIST_PRICE" && !sourceRef) {
    throw new Error("LIST_PRICE ใน Quick input ต้องมี source ref หรือ registered OEM target");
  }

  const year = await releaseYear(db, trim.release_id);
  const pricePayload: Record<string, unknown> = {
    amount_thb: amount,
    price_type: priceType,
    observed_at: observedAt,
    source: sourceLabel,
    source_ref: sourceRef || undefined,
    notes: reason,
  };
  if (effectiveFrom) pricePayload.effective_from = effectiveFrom;

  return enqueuePayload({
    schema_version: 1,
    batch_id: `admin-price-${submissionId(formData)}`,
    year,
    submitted_at: submittedAt,
    source: { kind, ref: sourceRef || undefined },
    reason,
    commands: [{ operation: "APPEND_PRICE", canonical_id: trimId, payload: pricePayload }],
  }, "price");
}

export async function enqueueModelTaxonomyInput(formData: FormData) {
  if (!(await isAdmin())) redirect("/admin/login");
  const modelId = requiredField(formData, "model_id", "รุ่นรถ");
  const bodyType = field(formData, "body_type").toUpperCase();
  const segment = field(formData, "segment").toUpperCase();
  if (bodyType && !BODY_TYPES.has(bodyType)) throw new Error("Body type ไม่อยู่ใน canonical taxonomy");
  if (segment && !SEGMENTS.has(segment)) throw new Error("Segment ไม่อยู่ใน canonical taxonomy");
  const nameEn = field(formData, "name_en");
  const nameTh = field(formData, "name_th");
  if (!bodyType && !segment && !nameEn && !nameTh) throw new Error("เลือกอย่างน้อย 1 field ที่ต้องการแก้");
  const reason = requiredField(formData, "reason", "เหตุผลการแก้");
  const submittedAt = submissionTimestamp(formData);

  const db = adminDb();
  if (!db) throw new Error("ยังไม่ได้ตั้งค่า Supabase server credential");
  const { data: model, error: modelError } = await db.from("current_vehicle_models")
    .select("canonical_id,release_id,brand_id,generation_id,name_en,name_th,body_type,segment")
    .eq("canonical_id", modelId).maybeSingle();
  if (modelError) throw modelError;
  if (!model?.brand_id || !model.generation_id || !model.release_id) throw new Error("รุ่นนี้ไม่มี active brand/generation ที่แก้ผ่าน Quick mode ได้");
  const [{ data: brand, error: brandError }, { data: generation, error: generationError }] = await Promise.all([
    db.from("current_vehicle_brands").select("canonical_id,name_en,name_th").eq("canonical_id", model.brand_id).maybeSingle(),
    db.from("current_vehicle_generations").select("canonical_id,code,segment").eq("canonical_id", model.generation_id).maybeSingle(),
  ]);
  if (brandError) throw brandError;
  if (generationError) throw generationError;
  if (!brand || !generation?.code) throw new Error("หา canonical brand/generation ของรุ่นนี้ไม่ครบ");
  const year = await releaseYear(db, model.release_id);

  const modelPatch: Record<string, unknown> = {};
  if (nameEn) modelPatch.name_en = nameEn;
  if (nameTh) modelPatch.name_th = nameTh;
  if (bodyType) modelPatch.body_type = bodyType;
  const generationPatch: Record<string, unknown> = { code: generation.code };
  if (segment) generationPatch.segment = segment;

  return enqueuePayload({
    schema_version: 1,
    batch_id: `admin-model-${submissionId(formData)}`,
    year,
    submitted_at: submittedAt,
    source: { kind: "ADMIN" },
    reason,
    commands: [{
      operation: "UPSERT_MODEL_BUNDLE",
      canonical_id: modelId,
      payload: {
        brand: { id: model.brand_id, name_en: brand.name_en || model.brand_id, ...(brand.name_th ? { name_th: brand.name_th } : {}) },
        model: modelPatch,
        generation: generationPatch,
      },
    }],
  }, "model");
}

export async function enqueueWithdrawModel(formData: FormData) {
  if (!(await isAdmin())) redirect("/admin/login");
  const modelId = requiredField(formData, "model_id", "รุ่นรถ");
  const ended = isoDate(field(formData, "ended"), "วันที่ยุติขาย");
  const reason = requiredField(formData, "reason", "เหตุผลการถอนรุ่น");
  const submittedAt = submissionTimestamp(formData);
  const db = adminDb();
  if (!db) throw new Error("ยังไม่ได้ตั้งค่า Supabase server credential");
  const { data: model, error } = await db.from("current_vehicle_models")
    .select("canonical_id,release_id").eq("canonical_id", modelId).maybeSingle();
  if (error) throw error;
  if (!model?.release_id) throw new Error("ไม่พบรุ่นนี้ใน active canonical release");
  const year = await releaseYear(db, model.release_id);

  return enqueuePayload({
    schema_version: 1,
    batch_id: `admin-withdraw-${submissionId(formData)}`,
    year,
    submitted_at: submittedAt,
    source: { kind: "ADMIN" },
    reason,
    commands: [{ operation: "WITHDRAW_MODEL", canonical_id: modelId, payload: ended ? { ended } : {} }],
  }, "withdraw");
}
