export type CompareSpecFact = {
  fact_id?: string;
  trim_id: string;
  field_key: string;
  value_state?: "KNOWN" | "UNKNOWN" | "NOT_AVAILABLE" | "NOT_APPLICABLE" | string;
  value?: unknown;
  unit?: string | null;
  qualifiers?: Record<string, unknown> | null;
  effective_from?: string | null;
  observed_at?: string | null;
  verification_status?: string | null;
};

function stamp(fact: CompareSpecFact) {
  return fact.effective_from || fact.observed_at || "";
}

export function factsByTrim(facts: CompareSpecFact[]) {
  const map = new Map<string, Map<string, CompareSpecFact>>();
  for (const fact of facts) {
    // Keep the renderer fail-closed even though the server query already asks
    // for VERIFIED rows. Future callers must not be able to promote a missing
    // or provisional verification status into the public comparison table.
    if (fact.verification_status !== "VERIFIED") continue;
    if (!map.has(fact.trim_id)) map.set(fact.trim_id, new Map());
    const bucket = map.get(fact.trim_id)!;
    const existing = bucket.get(fact.field_key);
    // Active releases already contain facts resolved at the release `as_of` by
    // ProductMaster.detail(). The ranking only makes duplicate verified rows
    // deterministic; it is not a second temporal resolver.
    if (!existing || stamp(fact) > stamp(existing)) bucket.set(fact.field_key, fact);
  }
  return map;
}

function numberDisplay(value: unknown, unit?: string | null) {
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  const digits = Math.abs(n % 1) > 0 ? 1 : 0;
  const text = n.toLocaleString("th-TH", { maximumFractionDigits: digits });
  if (!unit) return text;
  if (unit === "in") return `${text} นิ้ว`;
  if (unit === "airbag") return `${text} ใบ`;
  if (unit === "speaker") return `${text} ลำโพง`;
  if (unit === "port") return `${text} พอร์ต`;
  if (unit === "star") return `${text} ดาว`;
  return `${text} ${unit}`;
}

export type CompareCell = { display: string | null; token: string; known: boolean };

export function specCell(fact: CompareSpecFact | undefined): CompareCell {
  if (!fact) return { display: null, token: "UNKNOWN", known: false };
  const state = fact.value_state || "UNKNOWN";
  if (state === "NOT_APPLICABLE") return { display: "ไม่เกี่ยวข้อง", token: "NOT_APPLICABLE", known: true };
  if (state !== "KNOWN") return { display: null, token: state, known: false };
  if (typeof fact.value === "boolean") {
    return { display: fact.value ? "มี" : "ไม่มี", token: `BOOLEAN:${fact.value}`, known: true };
  }
  if (typeof fact.value === "number") {
    const display = numberDisplay(fact.value, fact.unit);
    return { display, token: `NUMBER:${fact.value}:${fact.unit || ""}`, known: true };
  }
  if (Array.isArray(fact.value)) {
    const display = fact.value.map(String).join(", ");
    return { display, token: `SET:${JSON.stringify(fact.value)}`, known: true };
  }
  const display = fact.value === null || fact.value === undefined || fact.value === "" ? null : String(fact.value);
  return { display, token: display === null ? "UNKNOWN" : `TEXT:${display}`, known: display !== null };
}
