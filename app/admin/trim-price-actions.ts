"use server";

/**
 * The price of one trim, saved from the car's own page.
 *
 * What the owner fills in is what a showroom quotes: the list price, the
 * promotion price if one is running, what comes with the car, and the dates
 * the promotion covers. Everything the ledger needs underneath -- a campaign
 * id, an option id, effective dates, observation dates, the ADMIN source --
 * is derived here, because those are bookkeeping for the history and not
 * decisions anybody should be asked to make to change a number.
 *
 * No reason, no reviewer, no approval: the owner of the data is the
 * authority on it. PriceLedger keeps the history either way, and the
 * automatic price tracker writes into the same ledger alongside this, so a
 * manual edit and a harvested price are the same kind of fact.
 */

import { redirect } from "next/navigation";
import { isAdmin } from "@/lib/admin-auth";
import { field, isoDate, safeSubmissionId, submissionTimestamp } from "@/lib/admin-form";
import { enqueueCanonicalInputBatch } from "@/lib/canonical-input-queue";
import { campaignIdFor } from "@/lib/campaign-identity";
import { adminDb } from "@/lib/supabase";

function amount(raw: string, label: string): number | null {
  if (!raw) return null;
  const value = Number(raw);
  if (!Number.isSafeInteger(value) || value <= 0) throw new Error(`${label} ต้องเป็นจำนวนเต็มบาทที่มากกว่า 0`);
  return value;
}

async function trimContext(trimId: string) {
  const db = adminDb();
  if (!db) throw new Error("ยังไม่ได้ตั้งค่า Supabase server credential");
  const { data: trim, error } = await db.from("current_market_trims")
    .select("canonical_id,model_id,release_id").eq("canonical_id", trimId).maybeSingle();
  if (error) throw error;
  if (!trim?.release_id) throw new Error("ไม่พบรุ่นย่อยนี้ใน active canonical release");
  const { data: release, error: releaseError } = await db.from("canonical_vehicle_releases")
    .select("payload,as_of").eq("release_id", trim.release_id).maybeSingle();
  if (releaseError) throw releaseError;
  const payload = release?.payload && typeof release.payload === "object"
    ? release.payload as Record<string, unknown> : {};
  const year = Number(payload.year || String(release?.as_of || "").slice(0, 4));
  if (!Number.isInteger(year) || year < 2000 || year > 2100) throw new Error("หา catalog year ไม่ได้");
  return { modelId: String(trim.model_id), brandId: String(trim.model_id).split(".", 1)[0], year };
}

/** End a promotion that was saved without an end date.
 *
 *  CLOSE_PRICE wants a reason for the ledger's own history; the owner is not
 *  asked for one, because ending your own campaign is not a decision that
 *  needs justifying to anybody. The reason is written for them. */
export async function closeTrimCampaign(formData: FormData) {
  if (!(await isAdmin())) redirect("/admin/login");
  const trimId = field(formData, "trim_id");
  const campaignId = field(formData, "campaign_id");
  const optionId = field(formData, "option_id") || "default";
  const modelIdForReturn = field(formData, "model_id");
  if (!trimId || !campaignId) throw new Error("ไม่พบแคมเปญที่จะปิด");

  const submissionId = safeSubmissionId(formData);
  const submittedAt = submissionTimestamp(formData);
  const today = submittedAt.slice(0, 10);
  const { year } = await trimContext(trimId);

  await enqueueCanonicalInputBatch({
    schema_version: 1,
    batch_id: `admin-close-campaign-${submissionId}`,
    year,
    submitted_at: submittedAt,
    source: { kind: "ADMIN" },
    reason: `campaign ended by owner on ${today}`,
    commands: [{
      operation: "CLOSE_PRICE",
      canonical_id: trimId,
      reason: `campaign ended by owner on ${today}`,
      payload: {
        trim_id: trimId, price_type: "CAMPAIGN_PRICE",
        campaign_id: campaignId, option_id: optionId, ends: today,
      },
    }],
  });
  redirect(`/admin/vehicles/${encodeURIComponent(modelIdForReturn)}?saved=PRICE`);
}

/** One save for everything a trim's price row shows. */
export async function saveTrimPrice(formData: FormData) {
  if (!(await isAdmin())) redirect("/admin/login");
  const trimId = field(formData, "trim_id");
  if (!trimId) throw new Error("ไม่พบรุ่นย่อย");
  const modelIdForReturn = field(formData, "model_id");

  const listPrice = amount(field(formData, "list_price"), "ราคาปกติ");
  const campaignPrice = amount(field(formData, "campaign_price"), "ราคาโปร");
  const gifts = field(formData, "gifts");
  const starts = isoDate(field(formData, "starts"), "วันเริ่ม");
  const ends = isoDate(field(formData, "ends"), "วันสิ้นสุด");
  if (starts && ends && starts > ends) throw new Error("วันเริ่มต้องไม่หลังวันสิ้นสุด");
  if (!listPrice && !campaignPrice) throw new Error("ใส่ราคาปกติหรือราคาโปรอย่างน้อยหนึ่งช่อง");

  const submissionId = safeSubmissionId(formData);
  const submittedAt = submissionTimestamp(formData);
  const today = submittedAt.slice(0, 10);
  const { brandId, year } = await trimContext(trimId);

  const commands: Record<string, unknown>[] = [];
  if (listPrice) {
    // The campaign window is the campaign's, not the list price's. A list
    // price saved by hand carries no effective date of its own, so it is
    // recorded as observed today and nothing pretends to know when it began.
    commands.push({
      operation: "APPEND_PRICE",
      canonical_id: trimId,
      payload: {
        trim_id: trimId, amount_thb: listPrice, price_type: "LIST_PRICE",
        observed_at: today, source: "admin",
      },
    });
  }
  if (campaignPrice) {
    // The campaign exists so the ledger can key a promotion price; its shape
    // is derived from the trim and the window rather than asked for, so the
    // same promotion re-saved lands on the same campaign instead of a new one.
    // Keyed on the whole canonical trim id: a grade name like "premium" is
    // not unique across models, and two brands' campaigns colliding on one
    // id would merge two promotions into one.
    const campaignId = campaignIdFor(trimId, starts || today);
    const optionId = "default";
    commands.push({
      operation: "UPSERT_CAMPAIGN",
      canonical_id: campaignId,
      payload: {
        id: campaignId, brand_id: brandId,
        name: gifts || "แคมเปญราคาพิเศษ",
        starts: starts || today, ends,
        gifts,
        source: "admin",
        options: [{ id: optionId, label: gifts || "ราคาพิเศษ", starts: starts || today, ends }],
      },
    });
    commands.push({
      operation: "APPEND_PRICE",
      canonical_id: trimId,
      payload: {
        trim_id: trimId, amount_thb: campaignPrice, price_type: "CAMPAIGN_PRICE",
        campaign_id: campaignId, option_id: optionId,
        effective_from: starts || today, effective_to: ends,
        observed_at: today, source: "admin",
      },
    });
  }

  await enqueueCanonicalInputBatch({
    schema_version: 1,
    batch_id: `admin-trim-price-${submissionId}`,
    year,
    submitted_at: submittedAt,
    source: { kind: "ADMIN" },
    commands,
  });
  redirect(`/admin/vehicles/${encodeURIComponent(modelIdForReturn)}?saved=PRICE`);
}
