import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import { gunzipSync } from "node:zlib";

export const ECO_TRIM_SNAPSHOT_DATE = "2026-09-08";
const SNAPSHOT_ROOT = path.join(
  process.cwd(),
  "automotive/vehicle_master/vehreg/data/2026/ingest/ecosticker/snapshots",
  ECO_TRIM_SNAPSHOT_DATE,
);

export type EcoTrimCandidateGroup = {
  key: string;
  snapshotDate: string;
  modelId: string;
  generationId: string;
  powertrain: string;
  rawLabel: string;
  sourceIds: string[];
  sourceCount: number;
  ecoPriceMinThb: number | null;
  ecoPriceMaxThb: number | null;
};

type EcoRow = Record<string, any>;

let cache: { manifestHash: string; groups: EcoTrimCandidateGroup[]; byKey: Map<string, EcoTrimCandidateGroup> } | null = null;

function normalizedLabel(value: unknown): string {
  return String(value || "")
    .normalize("NFKC")
    .toLocaleLowerCase("en-US")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim()
    .replace(/\s+/g, " ");
}

function numberOrNull(value: unknown): number | null {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function groupKey(modelId: string, generationId: string, powertrain: string, rawLabel: string): string {
  return createHash("sha256")
    .update([modelId, generationId, powertrain, normalizedLabel(rawLabel)].join("\u001f"))
    .digest("hex")
    .slice(0, 24);
}

function loadSnapshot() {
  if (cache) return cache;
  const manifestPath = path.join(SNAPSHOT_ROOT, "manifest.json");
  const normalizedPath = path.join(SNAPSHOT_ROOT, "normalized.jsonl.gz");
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  if (String(manifest.snapshot_date || "") !== ECO_TRIM_SNAPSHOT_DATE) {
    throw new Error("ECO trim snapshot date does not match manifest");
  }
  const raw = gunzipSync(readFileSync(normalizedPath));
  const hash = createHash("sha256").update(raw).digest("hex");
  if (!manifest.normalized_sha256 || hash !== String(manifest.normalized_sha256)) {
    throw new Error("ECO trim snapshot hash does not match manifest");
  }

  const grouped = new Map<string, {
    modelId: string;
    generationId: string;
    powertrain: string;
    rawLabel: string;
    sourceIds: Set<string>;
    prices: number[];
  }>();
  for (const line of raw.toString("utf8").split(/\r?\n/)) {
    if (!line.trim()) continue;
    const row = JSON.parse(line) as EcoRow;
    if (row.review_status !== "ready_for_review") continue;
    const modelId = String(row.matched_model_id || "").trim();
    const generationId = String(row.matched_generation_id || "").trim();
    const powertrain = String(row.powertrain_candidate || "").trim().toUpperCase();
    const sourceId = String(row.source_id || "").trim().toLowerCase();
    const rawLabel = String(row?.trim_candidate?.name_raw || row.model_raw || "").trim();
    if (!modelId || !generationId || !powertrain || !sourceId || !rawLabel) continue;
    const key = groupKey(modelId, generationId, powertrain, rawLabel);
    const current = grouped.get(key) || {
      modelId,
      generationId,
      powertrain,
      rawLabel,
      sourceIds: new Set<string>(),
      prices: [],
    };
    current.sourceIds.add(sourceId);
    const price = numberOrNull(row.price_thb);
    if (price != null) current.prices.push(price);
    grouped.set(key, current);
  }

  const groups = [...grouped.entries()].map(([key, value]): EcoTrimCandidateGroup => ({
    key,
    snapshotDate: ECO_TRIM_SNAPSHOT_DATE,
    modelId: value.modelId,
    generationId: value.generationId,
    powertrain: value.powertrain,
    rawLabel: value.rawLabel,
    sourceIds: [...value.sourceIds].sort(),
    sourceCount: value.sourceIds.size,
    ecoPriceMinThb: value.prices.length ? Math.min(...value.prices) : null,
    ecoPriceMaxThb: value.prices.length ? Math.max(...value.prices) : null,
  })).sort((a, b) => a.modelId.localeCompare(b.modelId) || a.rawLabel.localeCompare(b.rawLabel));
  const byKey = new Map(groups.map((group) => [group.key, group]));
  cache = { manifestHash: hash, groups, byKey };
  return cache;
}

export function getEcoTrimSnapshotHash(): string {
  return loadSnapshot().manifestHash;
}

export function getEcoTrimCandidateGroups(): EcoTrimCandidateGroup[] {
  return loadSnapshot().groups;
}

export function getEcoTrimCandidateGroup(key: string): EcoTrimCandidateGroup | null {
  return loadSnapshot().byKey.get(String(key || "")) || null;
}

export function exactCandidateSignature(group: EcoTrimCandidateGroup): string {
  return `${group.modelId}|${group.generationId}|${group.powertrain}|${normalizedLabel(group.rawLabel)}`;
}
