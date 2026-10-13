import "server-only";
import { currentEditor } from "../admin-auth.ts";
import { StructuralIdentityWriter, type TransactionalIdentityStore } from "./structural-writer.ts";

/** Server session boundary; not a route or database adapter. Nothing calls it
 * in production. A future adapter must additionally enforce this in its RPC.
 * R6 remains denied until separate governance adoption; request JSON cannot
 * enable it or assert actor_kind/approval. */
export function adminStructuralWriter(store: TransactionalIdentityStore): StructuralIdentityWriter {
  return new StructuralIdentityWriter(store, async () => {
    const editor = await currentEditor();
    if (!editor) throw new Error("STRUCTURAL_ADMIN_SESSION_REQUIRED");
    return { actor_id: editor.name, actor_kind: "ADMIN", can_propose: true, can_apply_structure: true, r6_allowed: false };
  });
}
