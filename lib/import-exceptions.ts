/**
 * The work an import could not do by itself.
 *
 * Everything an importer could place deterministically is already written;
 * what is here is the remainder, one durable row per unresolved thing.
 * `import_run_exceptions` has no cap on its own -- the JSON array it
 * replaced was capped at 500, so a file with 900 unplaceable rows
 * silently lost 400 of them -- but a reader that loads only the first
 * 1000 rows and calls that everything reintroduces the same silent loss
 * one layer up. Two rules follow from that:
 *
 *   - the work list pages with a stable (created_at, id) keyset, so a
 *     total count is exact and no row is skipped or repeated as new ones
 *     arrive between page loads;
 *   - a registration label is grouped across every OPEN row that carries
 *     it, in the database (public.import_run_registration_gaps,
 *     migration_v43), never over one page of rows read into memory --
 *     resolving a label is one decision that has to close every month
 *     waiting on it, not just the months that happened to fit on screen.
 */

import { adminDb } from "@/lib/supabase";

export type OpenException = {
  id: string;
  runId: string;
  runLabel: string;
  sourceKind: string;
  kind: string;
  reason: string;
  identity: Record<string, any>;
  createdAt: string;
};

export type ExceptionPage = {
  rows: OpenException[];
  /** Exact count of every OPEN row matching the same filter, not just this page. */
  total: number;
  /** Opaque; pass back as `cursor` to fetch the next page. Null on the last page. */
  nextCursor: string | null;
};

/** One unresolved registration label, and every month waiting on it. */
export type RegistrationGap = {
  ids: string[];
  brandRaw: string;
  modelRaw: string;
  registrationType: string;
  /** MODEL unless the source itself published the grade. Never inferred. */
  grain: "MODEL" | "TRIM";
  units: number;
  months: number;
  latestPeriod: string;
  reason: string;
};

export const REGISTRATION_KIND = "REGISTRATION_IDENTITY";

export const DEFAULT_PAGE_SIZE = 200;
const MAX_PAGE_SIZE = 500;

function encodeCursor(createdAt: string, id: string): string {
  return Buffer.from(`${createdAt}|${id}`, "utf8").toString("base64url");
}

function decodeCursor(cursor: string): { createdAt: string; id: string } | null {
  try {
    const [createdAt, id] = Buffer.from(cursor, "base64url").toString("utf8").split("|");
    return createdAt && id ? { createdAt, id } : null;
  } catch {
    return null;
  }
}

async function runLabelsFor(db: NonNullable<ReturnType<typeof adminDb>>,
                            rows: { run_id: unknown }[]): Promise<Map<string, string>> {
  const runIds = [...new Set(rows.map((row) => String(row.run_id)))];
  const labels = new Map<string, string>();
  if (!runIds.length) return labels;
  const { data: runs } = await db.from("import_runs")
    .select("id,original_name").in("id", runIds);
  for (const run of runs || []) labels.set(String(run.id), String(run.original_name || run.id));
  return labels;
}

function toException(row: any, labels: Map<string, string>): OpenException {
  return {
    id: String(row.id),
    runId: String(row.run_id),
    runLabel: labels.get(String(row.run_id)) || String(row.run_id),
    sourceKind: String(row.source_kind || ""),
    kind: String(row.kind || "UNKNOWN"),
    reason: String(row.reason || ""),
    identity: (row.source_identity && typeof row.source_identity === "object"
      ? row.source_identity : {}) as Record<string, any>,
    createdAt: String(row.created_at || ""),
  };
}

/** One page of the OPEN work list, keyset-paginated by (created_at, id)
 *  descending -- the same ordering the row's own `created_at desc` index
 *  (migration_v41) already serves, so a page is a single indexed range
 *  scan, not a sort over the whole table.
 *
 *  `excludeKind` leaves out rows of one kind -- used to page the "every
 *  OTHER exception" list separately from registration gaps, which have
 *  their own grouped, ungapped view. */
export async function listOpenExceptionsPage(args: {
  cursor?: string | null;
  pageSize?: number;
  excludeKind?: string;
} = {}): Promise<ExceptionPage> {
  const db = adminDb();
  if (!db) return { rows: [], total: 0, nextCursor: null };
  const pageSize = Math.max(1, Math.min(args.pageSize ?? DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE));

  let countQuery = db.from("import_run_exceptions")
    .select("id", { count: "exact", head: true }).eq("status", "OPEN");
  if (args.excludeKind) countQuery = countQuery.neq("kind", args.excludeKind);
  const { count, error: countError } = await countQuery;
  if (countError) return { rows: [], total: 0, nextCursor: null };

  let query = db.from("import_run_exceptions")
    .select("id,run_id,source_kind,kind,reason,source_identity,created_at")
    .eq("status", "OPEN")
    .order("created_at", { ascending: false })
    .order("id", { ascending: false })
    // One extra row: its presence is how "is there a next page" is
    // known without a second round trip.
    .limit(pageSize + 1);
  if (args.excludeKind) query = query.neq("kind", args.excludeKind);

  const cursor = args.cursor ? decodeCursor(args.cursor) : null;
  if (cursor) {
    // Keyset, not OFFSET: strictly older than the last row already
    // shown, by the same (created_at, id) ordering the query sorts on.
    // An OFFSET page shifts under concurrent inserts and can skip or
    // repeat a row; this cannot.
    query = query.or(
      `created_at.lt.${cursor.createdAt},and(created_at.eq.${cursor.createdAt},id.lt.${cursor.id})`,
    );
  }

  const { data, error } = await query;
  if (error) return { rows: [], total: count ?? 0, nextCursor: null };
  const fetched = data || [];
  const hasMore = fetched.length > pageSize;
  const page = hasMore ? fetched.slice(0, pageSize) : fetched;

  const labels = await runLabelsFor(db, page);
  const nextCursor = hasMore
    ? encodeCursor(String(page[page.length - 1].created_at), String(page[page.length - 1].id))
    : null;

  return { rows: page.map((row) => toException(row, labels)), total: count ?? 0, nextCursor };
}

/** Every OPEN registration label, grouped server-side over the WHOLE
 *  table (public.import_run_registration_gaps, migration_v43) -- never
 *  from one page of rows read into memory, which could only ever see the
 *  months that happened to land on that page and would report a label
 *  "resolved" while other months of it stayed silently open. */
export async function listRegistrationGaps(): Promise<RegistrationGap[]> {
  const db = adminDb();
  if (!db) return [];
  const { data, error } = await db.from("import_run_registration_gaps")
    .select("registration_type,brand_name_raw,model_name_raw,grain,exception_ids,"
           + "total_units,months,latest_period,reason")
    .order("total_units", { ascending: false })
    .limit(5000);
  if (error) return [];
  return (data || [])
    .filter((row: any) => row.brand_name_raw && row.model_name_raw)
    .map((row: any) => ({
      ids: (row.exception_ids || []).map((id: unknown) => String(id)),
      brandRaw: String(row.brand_name_raw),
      modelRaw: String(row.model_name_raw),
      registrationType: String(row.registration_type || "*"),
      grain: String(row.grain || "MODEL") === "TRIM" ? "TRIM" : "MODEL",
      units: Number(row.total_units || 0),
      months: Number(row.months || 0),
      latestPeriod: String(row.latest_period || ""),
      reason: String(row.reason || ""),
    }));
}
