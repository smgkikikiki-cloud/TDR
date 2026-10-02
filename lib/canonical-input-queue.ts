export type CanonicalWorkerDispatch = {
  started: boolean;
  reason?: "legacy_write_path_closed";
};

/**
 * Vehicle DB v3 Phase 0 step 5.
 *
 * The file-backed canonical_input_batches -> vehreg/data -> release pipeline is
 * closed. Keep this exported function as a compatibility boundary for admin
 * components that still import it, but never insert a row or dispatch the old
 * worker. Phase 1 replaces this with the DB-master write layer.
 */
export async function enqueueCanonicalInputBatch(_payload: Record<string, unknown>): Promise<never> {
  throw new Error(
    "Legacy Vehicle DB write path is closed (Phase 0 step 5). Vehicle Master in Supabase is authoritative.",
  );
}
