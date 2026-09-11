import coverageReview from "@/automotive/vehicle_master/vehreg/data/2026/market/pricefeed/review/coverage.json";

export type PriceCoverageReason =
  | "AWAITING_FINAL_LIST_PRICE"
  | "OFFICIAL_EVIDENCE_CONFLICT"
  | "NO_RELIABLE_EVIDENCE";

export type PriceCoverageDisposition = {
  trimId: string;
  action: "defer";
  reasonCode: PriceCoverageReason;
  reviewer: string;
  reviewedAt: string;
  sourceRef: string;
  notes: string;
};

const REASONS = new Set<PriceCoverageReason>([
  "AWAITING_FINAL_LIST_PRICE",
  "OFFICIAL_EVIDENCE_CONFLICT",
  "NO_RELIABLE_EVIDENCE",
]);

function rows(): any[] {
  return Array.isArray((coverageReview as any)?.decisions)
    ? (coverageReview as any).decisions
    : [];
}

export function priceCoverageDecisions(): Map<string, PriceCoverageDisposition> {
  const out = new Map<string, PriceCoverageDisposition>();
  for (const row of rows()) {
    const trimId = String(row?.trim_id || "").trim();
    const action = String(row?.action || "").trim().toLowerCase();
    const reasonCode = String(row?.reason_code || "").trim().toUpperCase() as PriceCoverageReason;
    const reviewer = String(row?.reviewer || "").trim();
    const reviewedAt = String(row?.reviewed_at || "").trim();
    const sourceRef = String(row?.source_ref || "").trim();
    if (!trimId || action !== "defer" || !REASONS.has(reasonCode) || !reviewer || !reviewedAt || !sourceRef) continue;
    out.set(trimId, {
      trimId,
      action: "defer",
      reasonCode,
      reviewer,
      reviewedAt,
      sourceRef,
      notes: String(row?.notes || "").trim(),
    });
  }
  return out;
}

export function priceCoverageDecision(trimId: string): PriceCoverageDisposition | null {
  return priceCoverageDecisions().get(String(trimId || "").trim()) || null;
}
