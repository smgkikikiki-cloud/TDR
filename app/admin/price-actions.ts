"use server";

import { adminDb } from "@/lib/supabase";
import { enqueueVehicleInput } from "./input-actions";

const PRICE_TYPES = new Set([
  "LIST_PRICE",
  "INTRODUCTORY_PRICE",
  "CAMPAIGN_PRICE",
  "FINANCE_PRICE",
  "ESTIMATED_PRICE",
  "DEALER_PRICE",
  "ECO_STICKER_PRICE",
]);

function field(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value.trim() : "";
}

function required(formData: FormData, name: string, label = name): string {
  const value = field(formData, name);
  if (!value) throw new Error(`กรุณาใส่ ${label}`);
  return value;
}

function isoDate(value: string, label: string, requiredValue = false): string | undefined {
  if (!value) {
    if (requiredValue) throw new Error(`กรุณาใส่ ${label}`);
    return undefined;
  }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || Number.isNaN(Date.parse(`${value}T00:00:00Z`))) {
    throw new Error(`${label} ต้องเป็น YYYY-MM-DD`);
  }
  return value;
}

function safeToken(value: string, label: string): string {
  if (!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(value)) throw new Error(`${label} ไม่ถูกต้อง`);
  return value;
}

async function canonicalYearForTrim(trimId: string): Promise<number> {
  const db = adminDb();
  if (!db) throw new Error("ยังไม่ได้ตั้งค่า Supabase server credential");
  const { data: trim, error } = await db.from("current_market_trims")
    .select("canonical_id,release_id")
    .eq("canonical_id", trimId)
    .maybeSingle();
  if (error) throw error;
  if (!trim?.release_id) throw new Error("ไม่พบ MarketTrim นี้ใน active canonical release");
  const { data: release, error: releaseError } = await db.from("canonical_vehicle_releases")
    .select("payload,as_of")
    .eq("release_id", trim.release_id)
    .maybeSingle();
  if (releaseError) throw releaseError;
  const payload = release?.payload && typeof release.payload === "object"
    ? release.payload as Record<string, unknown> : {};
  const year = Number(payload.year || String(release?.as_of || "").slice(0, 4));
  if (!Number.isInteger(year) || year < 2000 || year > 2100) throw new Error("หา catalog year ไม่ได้");
  return year;
}

async function canonicalYearForBrand(brandId: string): Promise<number> {
  const db = adminDb();
  if (!db) throw new Error("ยังไม่ได้ตั้งค่า Supabase server credential");
  const { data: brand, error } = await db.from("current_vehicle_brands")
    .select("canonical_id,release_id")
    .eq("canonical_id", brandId)
    .maybeSingle();
  if (error) throw error;
  if (!brand?.release_id) throw new Error("ไม่พบ Brand นี้ใน active canonical release");
  const { data: release, error: releaseError } = await db.from("canonical_vehicle_releases")
    .select("payload,as_of")
    .eq("release_id", brand.release_id)
    .maybeSingle();
  if (releaseError) throw releaseError;
  const payload = release?.payload && typeof release.payload === "object"
    ? release.payload as Record<string, unknown> : {};
  const year = Number(payload.year || String(release?.as_of || "").slice(0, 4));
  if (!Number.isInteger(year) || year < 2000 || year > 2100) throw new Error("หา catalog year ไม่ได้");
  return year;
}

async function queue(payload: Record<string, unknown>, submittedAt: string) {
  const wrapper = new FormData();
  wrapper.set("payload", JSON.stringify(payload));
  wrapper.set("submitted_at", submittedAt);
  return enqueueVehicleInput(wrapper);
}

function scopedPriceFields(formData: FormData) {
  const priceType = required(formData, "price_type", "ประเภทราคา").toUpperCase();
  if (!PRICE_TYPES.has(priceType)) throw new Error("ประเภทราคาไม่รองรับ");
  const campaignId = field(formData, "campaign_id") || undefined;
  const optionId = field(formData, "option_id") || undefined;
  if (["CAMPAIGN_PRICE", "FINANCE_PRICE"].includes(priceType) && (!campaignId || !optionId)) {
    throw new Error("Campaign/Finance price ต้องระบุ campaign_id และ option_id");
  }
  return { priceType, campaignId, optionId };
}

export async function enqueueCorrectPrice(formData: FormData) {
  const trimId = safeToken(required(formData, "trim_id", "MarketTrim"), "MarketTrim");
  const { priceType, campaignId, optionId } = scopedPriceFields(formData);
  const amount = Number(required(formData, "amount_thb", "ราคาใหม่"));
  if (!Number.isSafeInteger(amount) || amount <= 0) throw new Error("ราคาใหม่ต้องเป็นจำนวนเต็มบาทที่มากกว่า 0");
  const mode = required(formData, "mode", "โหมดแก้ราคา").toLowerCase();
  if (!new Set(["supersede", "retract"]).has(mode)) throw new Error("โหมดแก้ราคาไม่รองรับ");
  const effectiveFrom = isoDate(required(formData, "effective_from", "วันที่ราคาใหม่มีผล"), "วันที่ราคาใหม่มีผล", true)!;
  const asOf = isoDate(field(formData, "as_of"), "วันที่อ้างอิง");
  const source = field(formData, "source");
  const sourceRef = field(formData, "source_ref");
  const reason = required(formData, "reason", "เหตุผลการแก้");
  const submissionId = safeToken(required(formData, "submission_id", "submission id"), "submission id");
  const submittedAt = required(formData, "submitted_at", "submission timestamp");
  const year = await canonicalYearForTrim(trimId);

  const commandPayload: Record<string, unknown> = {
    price_type: priceType,
    amount_thb: amount,
    mode,
    effective_from: effectiveFrom,
  };
  if (asOf) commandPayload.as_of = asOf;
  if (campaignId) commandPayload.campaign_id = campaignId;
  if (optionId) commandPayload.option_id = optionId;
  if (source) commandPayload.source = source;
  if (sourceRef) commandPayload.source_ref = sourceRef;

  return queue({
    schema_version: 1,
    batch_id: `admin-price-correct-${submissionId}`,
    year,
    submitted_at: submittedAt,
    source: { kind: "ADMIN", ref: sourceRef || undefined },
    reason,
    commands: [{ operation: "CORRECT_PRICE", canonical_id: trimId, payload: commandPayload }],
  }, submittedAt);
}

export async function enqueueClosePrice(formData: FormData) {
  const trimId = safeToken(required(formData, "trim_id", "MarketTrim"), "MarketTrim");
  const { priceType, campaignId, optionId } = scopedPriceFields(formData);
  const ends = isoDate(required(formData, "ends", "วันสิ้นสุดราคา"), "วันสิ้นสุดราคา", true)!;
  const asOf = isoDate(field(formData, "as_of"), "วันที่อ้างอิง");
  const reason = required(formData, "reason", "เหตุผลการปิดราคา");
  const submissionId = safeToken(required(formData, "submission_id", "submission id"), "submission id");
  const submittedAt = required(formData, "submitted_at", "submission timestamp");
  const year = await canonicalYearForTrim(trimId);

  const commandPayload: Record<string, unknown> = { price_type: priceType, ends };
  if (asOf) commandPayload.as_of = asOf;
  if (campaignId) commandPayload.campaign_id = campaignId;
  if (optionId) commandPayload.option_id = optionId;

  return queue({
    schema_version: 1,
    batch_id: `admin-price-close-${submissionId}`,
    year,
    submitted_at: submittedAt,
    source: { kind: "ADMIN" },
    reason,
    commands: [{ operation: "CLOSE_PRICE", canonical_id: trimId, payload: commandPayload }],
  }, submittedAt);
}

export async function enqueueCampaignUpsert(formData: FormData) {
  const raw = required(formData, "campaign_json", "campaign JSON");
  let campaign: Record<string, unknown>;
  try { campaign = JSON.parse(raw); } catch { throw new Error("campaign JSON ไม่ถูกต้อง"); }
  const campaignId = safeToken(String(campaign.id || "").trim(), "campaign id");
  const brandId = safeToken(String(campaign.brand_id || "").trim(), "brand id");
  if (!campaignId || !brandId) throw new Error("campaign ต้องมี id และ brand_id");
  const reason = required(formData, "reason", "เหตุผลการแก้ campaign");
  const submissionId = safeToken(required(formData, "submission_id", "submission id"), "submission id");
  const submittedAt = required(formData, "submitted_at", "submission timestamp");
  const year = await canonicalYearForBrand(brandId);

  return queue({
    schema_version: 1,
    batch_id: `admin-campaign-${submissionId}`,
    year,
    submitted_at: submittedAt,
    source: { kind: "ADMIN", ref: typeof campaign.source_ref === "string" ? campaign.source_ref : undefined },
    reason,
    commands: [{ operation: "UPSERT_CAMPAIGN", canonical_id: campaignId, payload: campaign }],
  }, submittedAt);
}
