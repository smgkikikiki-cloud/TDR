/** Test double only. Never a file-backed or production Vehicle Master. */
import { canonicalScopedLinkKey, structuralHash, type Entity, type Row, type Proposal, type Revision, type Snapshot,
  type Transaction, type TransactionalIdentityStore, type Result } from "../../lib/vehicle-engine/structural-writer.ts";

type State = Snapshot & { audit: Revision[]; observations: Row[]; inbox: Proposal[]; receipts: Record<string, { hash: string; result: Result }> };
export class MemoryIdentityStore implements TransactionalIdentityStore {
  state: State;
  failOnWrite: number | null = null;
  private tail: Promise<unknown> = Promise.resolve();
  constructor(snapshot: Snapshot) { this.state = { ...structuredClone(snapshot), audit: [], observations: [], inbox: [], receipts: {} }; }
  async transaction<T>(work: (tx: Transaction) => T): Promise<T> {
    const run = this.tail.then(() => {
      const next = structuredClone(this.state);
      let writes = 0;
      const tx: Transaction = {
        snapshot: () => structuredClone(next),
        write: (entity: Entity, id: string, row: Row) => {
          if (++writes === this.failOnWrite) throw new Error("INJECTED_TRANSACTION_FAILURE");
          const list: Row[] = next[entity];
          const wanted = entity === "ice_model_crosswalk_scoped" ? canonicalScopedLinkKey(row.model_group_id, row.reg_type_scope).key : null;
          const matches = list.map((r, index) => ({ r, index })).filter(({ r }) => entity === "ice_model_crosswalk_scoped" ?
            canonicalScopedLinkKey(r.model_group_id, r.reg_type_scope).key === wanted : r.canonical_id === id);
          if (entity === "ice_model_crosswalk_scoped" && matches.length > 1) {
            throw new Error("DUPLICATE_SCOPED_LINK_KEY:" + wanted);
          }
          const index = matches[0]?.index ?? -1;
          if (index < 0) list.push(structuredClone(row)); else list[index] = structuredClone(row);
        },
        appendRevision: revision => {
          if (next.audit.some(r => r.id === revision.id || (revision.reverts_id && r.reverts_id === revision.reverts_id))) throw new Error("DUPLICATE_REVISION_OR_REVERT");
          next.audit.push(structuredClone(revision));
        },
        revisions: batch => structuredClone(next.audit.filter(r => r.batch_id === batch)),
        isReverted: id => next.audit.some(r => r.reverts_id === id),
        appendObservation: observation => {
          if (next.observations.some(o => o.id === observation.id)) throw new Error("DUPLICATE_OBSERVATION");
          next.observations.push(structuredClone(observation));
        },
        propose: proposal => {
          const open = next.inbox.find(p => p.dedupe_key === proposal.dedupe_key && p.status === "OPEN");
          if (open) { Object.assign(open, structuredClone(proposal), { id: open.id, seen_count: open.seen_count + 1 }); return structuredClone(open); }
          const decided = next.inbox.find(p => p.dedupe_key === proposal.dedupe_key && p.status !== "OPEN" && p.source_hash === proposal.source_hash);
          if (decided) return structuredClone(decided);
          next.inbox.push(structuredClone(proposal)); return structuredClone(proposal);
        },
        proposal: id => structuredClone(next.inbox.find(p => p.id === id)),
        approveProposal: id => { const p = next.inbox.find(p => p.id === id)!; p.status = "APPROVED"; },
        receipt: key => structuredClone(next.receipts[key]),
        saveReceipt: (key, hash, result) => { next.receipts[key] = { hash, result: structuredClone(result) }; },
      };
      const result = work(tx); this.state = next; return result;
    });
    this.tail = run.catch(() => {});
    return run;
  }
}
