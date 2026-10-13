/**
 * Deterministic FAKE sources for the playbook tests. "Acme" is not a real maker and none of these pages exist:
 * nothing here is evidence about any real brand (those fixtures belong to PR 3, captured from real pages).
 */
import type { Playbook, ResolvedSource, SourceSpec } from "../../lib/price-refresh/playbook.ts";

export const MODEL = "acme.roadster";
export const TODAY = "2026-10-12";
export const pad = " ".repeat(220); // pages are never a handful of characters

export const MODEL_PAGE_WITH_PRICES = `ACME Roadster\nรุ่นย่อย\nSmart\nราคาเริ่มต้น 599,000 บาท\nSport\nราคาเริ่มต้น 569,000 บาท\nPremium\nราคาเริ่มต้น 679,000 บาท\n${pad}`.replace(/\n/g, "\n");
export const MODEL_PAGE_NO_PRICES = `ACME Roadster\nเลือกรุ่นที่ใช่\nSmart\nSport\nPremium\nจองรถ ทดลองขับ\n${pad}`;
export const MODEL_PAGE_PARTIAL = `ACME Roadster\nSmart\nราคาเริ่มต้น 599,000 บาท\n${pad}`; // maker sells more grades than this page shows
export const PRICE_LIST_HTML = `<html><body><h1>ราคารถ ACME มีผล 23/09/2569</h1><table>
<tr><td>Smart</td><td>599,000 บาท</td></tr>
<tr><td>Sport</td><td>569,000 บาท</td></tr>
<tr><td>Premium</td><td>679,000 บาท</td></tr>
<tr><td>Ghost</td><td>ผ่อน 7,990 บาท/เดือน</td></tr></table><p>${pad}</p></body></html>`;
export const PRICE_LIST_PDF_TEXT = `ACME Thailand - Recommended retail price list - effective 2026-09-23\nModel      Grade            Price (THB)\nRoadster   Smart            599,000\nRoadster   Sport            569,000\nRoadster   Premium          679,000\nRoadster   Premium Edition  699,000 (special price 649,000)\n${pad}`;
export const PROMO_ONLY_PAGE = `ACME Roadster\nSport\nราคาพิเศษ 539,000 บาท\nแคมเปญเดือนตุลาคม\n${pad}`;
export const MSRP_AND_FROM_PAGE = `ACME Roadster\nSport\nFROM 539,000.-\nMSRP : 569,000.-\n${pad}`;
export const SOURCE_ROW = String.raw`^(?<name>[^|]+?)\s*\|\s*(?<price>[\d,]{7,})`;
export const PDF_ROW = String.raw`^Roadster\s+(?<name>\S.*?)\s{2,}(?<price>[\d,]{7,})(?:\s*\(special price (?<promo>[\d,]+)\))?`;

export const trimRow = (id: string, name: string) => ({ canonical_id: `acme.roadster.g1.trim.${id}`, model_id: MODEL, generation_id: "g1", revision: 1, name, status: "CURRENT", catalog_payload: {}, payload: {} });
export const ledgerRow = (n: number, trim: string, amount: number) => ({ record_id: `r${n}`, trim_id: `acme.roadster.g1.trim.${trim}`, amount_thb: amount, price_type: "LIST_PRICE",
  effective_from: "2026-01-01", observed_at: "2026-01-01", source: "seed", source_ref: "", source_document_id: "", notes: "", campaign_id: null, option_id: null,
  reference_price_thb: null, effective_to: null, retracted_at: null, retraction_reason: "", reviewed_by: "" });
export const tid = (s: string) => `acme.roadster.g1.trim.${s}`;

export const source = (over: Partial<SourceSpec> & { id: string }): ResolvedSource => ({
  url: `https://acme.example/${over.id}`, role: "MODEL_PAGE", models: [MODEL], fetch: { kind: "BROWSER" }, priority: 1,
  authority: { prices: true, existence: true }, extraction: { mode: "ANCHORED" }, required: true,
  brand: "acme", playbook_version: "fixture", playbook_status: "VERIFIED", ...over,
});

export const playbook = (sources: SourceSpec[], over: Partial<Playbook> = {}): Playbook => ({
  schema_version: 1, brand: "acme", playbook_version: "fixture-1", status: "VERIFIED",
  evidence: [{ url: "https://acme.example/fixture", captured_on: "2026-10-12", note: "FAKE test fixture, not a real maker" }], sources, ...over,
});

export const VERIFIED_COMPLETE = { lineup_complete: true, lineup_verification: { verified_on: "2026-10-01", verified_by: "fixture", evidence_ref: "fake" } } as const;
