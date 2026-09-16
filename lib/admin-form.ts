/**
 * Small FormData helpers shared by the Canonical Vehicle Editor's server
 * actions. Every existing app/admin/*-actions.ts file (input-actions.ts,
 * eco-trim-actions.ts, price-actions.ts, retail-lifecycle-actions.ts,
 * trim-retail-lifecycle-actions.ts) re-implements these same half-dozen
 * lines; adding a sixth near-identical copy for vehicle-editor-actions.ts is
 * exactly the drift the task asked to avoid, so this is the one extraction.
 * The existing files are left untouched -- this only backs new code.
 */
import { randomUUID } from "node:crypto";

export function field(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value.trim() : "";
}

export function requiredField(formData: FormData, name: string, label = name): string {
  const value = field(formData, name);
  if (!value) throw new Error(`กรุณาใส่ ${label}`);
  return value;
}

export function isoDate(value: string, label: string, required = false): string | undefined {
  if (!value) {
    if (required) throw new Error(`กรุณาใส่ ${label}`);
    return undefined;
  }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || Number.isNaN(Date.parse(`${value}T00:00:00Z`))) {
    throw new Error(`${label} ต้องเป็น YYYY-MM-DD`);
  }
  return value;
}

export function safeSubmissionId(formData: FormData): string {
  const value = field(formData, "submission_id") || randomUUID();
  if (!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$/.test(value)) throw new Error("submission_id ไม่ถูกต้อง");
  return value;
}

export function submissionTimestamp(formData: FormData): string {
  const value = field(formData, "submitted_at") || new Date().toISOString();
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime()) || !/(?:Z|[+-]\d{2}:\d{2})$/.test(value)) {
    throw new Error("submission timestamp ต้องเป็น ISO-8601 พร้อม timezone");
  }
  return value;
}

export function evidenceUrl(value: string): string {
  let url: URL;
  try { url = new URL(value); } catch { throw new Error("Evidence ต้องเป็น URL ที่ถูกต้อง"); }
  if (!["http:", "https:"].includes(url.protocol)) throw new Error("Evidence ต้องเป็น HTTP(S) URL");
  return url.toString();
}
