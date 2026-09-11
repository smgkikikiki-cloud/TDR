import reviewState from "@/automotive/vehicle_master/vehreg/data/2026/market/retail_lifecycle/trim_review.json";

export type TrimRetailLifecycleStatus = "CURRENT" | "HISTORICAL";
export type TrimRetailLifecycleDecision = {
  trimId: string;
  status: TrimRetailLifecycleStatus;
  reviewer: string;
  reviewedAt: string;
  sourceRef: string;
  notes: string;
};

export function trimRetailLifecycleDecisions(): Map<string, TrimRetailLifecycleDecision> {
  const rows = Array.isArray((reviewState as any)?.decisions) ? (reviewState as any).decisions : [];
  const out = new Map<string, TrimRetailLifecycleDecision>();
  for (const row of rows) {
    const trimId = String(row?.trim_id || "").trim();
    const status = String(row?.status || "").trim().toUpperCase();
    if (!trimId || (status !== "CURRENT" && status !== "HISTORICAL")) continue;
    out.set(trimId, {
      trimId,
      status: status as TrimRetailLifecycleStatus,
      reviewer: String(row?.reviewer || ""),
      reviewedAt: String(row?.reviewed_at || ""),
      sourceRef: String(row?.source_ref || ""),
      notes: String(row?.notes || ""),
    });
  }
  return out;
}

export function trimRetailLifecycleDecision(trimId: string) {
  return trimRetailLifecycleDecisions().get(trimId) || null;
}
