/**
 * R6 offline-only V2 crosswalk **consumer contract fixture** (Issue #230).
 *
 * No database calls, migrations, production readers, feature flags or writes.
 * The current production v63 index only allows a canonical model to be active
 * for ONE Ice group. This design models the owner's approved MANY Ice groups
 * -> ONE canonical identity and ONE Ice group -> distinct reg_type identities.
 *
 * Read-only contract: a source registration grain is counted exactly once.
 * Any group with scoped evidence may never fall back to a group-only link.
 */
export type ScopedLinkStatus = "APPROVED" | "AUTO" | "PROPOSED" | "REJECTED" | "EXCLUDED";

export type ScopedCrosswalkLink = {
  master_version: string;
  model_group_id: string;
  /** Null/omitted represents v63 legacy group scope only. */
  reg_type?: string | null;
  canonical_model_id: string | null;
  status: ScopedLinkStatus;
  decision_ref?: string;
};

export type ScopedRegistration = {
  model_group_id: string;
  reg_type: string;
  reg_count: number;
};

export type ScopedResolution =
  | { kind: "LINKED"; canonical_model_id: string; scope: "SCOPED" | "LEGACY" }
  | { kind: "UNMAPPED" | "EXCLUDED" | "AMBIGUOUS"; canonical_model_id: null; scope: "SCOPED" | "LEGACY" | "NONE" };

type IndexedGroup = {
  legacy: ScopedCrosswalkLink[];
  scoped: Map<string, ScopedCrosswalkLink[]>;
};

export function normalizedIceRegType(value: string): string {
  const normalized = value.trim().toUpperCase();
  const known: Record<string, string> = {
    "RY1": "รย.1", "RY2": "รย.2", "RY3": "รย.3",
    "รย.1": "รย.1", "รย.2": "รย.2", "รย.3": "รย.3",
  };
  // Only normalize syntax, NEVER infer RY2 is equivalent to RY1.
  return known[normalized] ?? value.trim();
}

export function compileScopedCrosswalk(
  links: readonly ScopedCrosswalkLink[], masterVersion: string,
): (modelGroupId: string, regType: string) => ScopedResolution {
  const groups = new Map<string, IndexedGroup>();

  for (const link of links) {
    if (link.master_version !== masterVersion) continue;
    if (!link.model_group_id.trim()) throw new Error("empty Ice model_group_id");
    let group = groups.get(link.model_group_id);
    if (!group) {
      group = { legacy: [], scoped: new Map<string, ScopedCrosswalkLink[]>() };
      groups.set(link.model_group_id, group);
    }
    if (link.reg_type == null) {
      group.legacy.push(link);
    } else {
      const type = normalizedIceRegType(link.reg_type);
      if (!type) throw new Error("empty scoped registration type");
      const current = group.scoped.get(type) ?? [];
      current.push(link);
      group.scoped.set(type, current);
    }
  }

  function decide(
    rows: readonly ScopedCrosswalkLink[], scope: "SCOPED" | "LEGACY" | "NONE",
  ): ScopedResolution {
    if (rows.length === 0) return { kind: "UNMAPPED", canonical_model_id: null, scope };
    // An owner exclusion is a source-grain action, not a destructive deletion.
    if (rows.some((link) => link.status === "EXCLUDED")) {
      if (rows.some((link) => link.status === "APPROVED" || link.status === "AUTO")) {
        return { kind: "AMBIGUOUS", canonical_model_id: null, scope };
      }
      return { kind: "EXCLUDED", canonical_model_id: null, scope };
    }
    const active = rows.filter((link) => link.status === "APPROVED" || link.status === "AUTO");
    if (active.some((link) => !link.canonical_model_id)) {
      return { kind: "AMBIGUOUS", canonical_model_id: null, scope };
    }
    const targets = new Set(active.map((link) => link.canonical_model_id).filter(
      (id): id is string => Boolean(id),
    ));
    if (targets.size > 1) {
      // Refuse a fanout from one Ice registration grain into multiple models.
      return { kind: "AMBIGUOUS", canonical_model_id: null, scope };
    }
    const target = [...targets][0];
    if (!target) return { kind: "UNMAPPED", canonical_model_id: null, scope };
    return { kind: "LINKED", canonical_model_id: target, scope: scope === "NONE" ? "LEGACY" : scope };
  }

  return (modelGroupId: string, regType: string): ScopedResolution => {
    const group = groups.get(modelGroupId);
    if (!group) return { kind: "UNMAPPED", canonical_model_id: null, scope: "NONE" };
    if (group.scoped.size > 0) {
      // Scoped coverage is strict. Missing RY3 must never inherit RY1 or
      // the old group-only canonical target (even if it looks plausible).
      return decide(group.scoped.get(normalizedIceRegType(regType)) ?? [], "SCOPED");
    }
    return decide(group.legacy, "LEGACY");
  };
}

export type ScopedUnitAccounting = {
  raw_units: number;
  linked_units: number;
  unresolved_units: number;
  excluded_units: number;
  ambiguous_units: number;
  /** Each linked row contributes to EXACTLY one canonical total. */
  units_by_canonical: Record<string, number>;
};

export function aggregateScopedRegistrations(
  rows: readonly ScopedRegistration[],
  resolve: ReturnType<typeof compileScopedCrosswalk>,
): ScopedUnitAccounting {
  const accounting: ScopedUnitAccounting = {
    raw_units: 0, linked_units: 0, unresolved_units: 0,
    excluded_units: 0, ambiguous_units: 0, units_by_canonical: {},
  };
  for (const row of rows) {
    const units = row.reg_count;
    if (!Number.isSafeInteger(units) || units < 0) {
      throw new Error("invalid registration count");
    }
    const resolution = resolve(row.model_group_id, row.reg_type);
    accounting.raw_units += units;
    if (resolution.kind === "LINKED") {
      accounting.linked_units += units;
      accounting.units_by_canonical[resolution.canonical_model_id] =
        (accounting.units_by_canonical[resolution.canonical_model_id] ?? 0) + units;
    } else if (resolution.kind === "EXCLUDED") {
      accounting.excluded_units += units;
    } else if (resolution.kind === "AMBIGUOUS") {
      accounting.ambiguous_units += units;
    } else {
      accounting.unresolved_units += units;
    }
  }
  if (accounting.raw_units !== accounting.linked_units + accounting.unresolved_units +
      accounting.excluded_units + accounting.ambiguous_units) {
    throw new Error("Ice registration units lost or duplicated");
  }
  return accounting;
}
