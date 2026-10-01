import { Skeleton } from "@/components/design";

/** Loading state of /models: the page's own layout at its final dimensions, no spinner (PAGES §0). Decorative:
 *  aria-busy on the wrapper, blocks hidden from assistive tech. Used as the Suspense fallback inside the page (a
 *  route-level loading.tsx at /models stalls same-page filter navigation in this Next build, so it is not used). */
export function ListSkeleton() {
  return (
    <div className="tdr-wrap" aria-busy="true" aria-live="polite">
      <div className="tdr-models-sk-head"><Skeleton height={18} width={140} /><Skeleton height={48} width="60%" /><Skeleton height={20} width="80%" /></div>
      <div className="tdr-models-kpis">{Array.from({ length: 5 }, (_, i) => <Skeleton key={i} height={84} />)}</div>
      <div className="tdr-models-tiles">{Array.from({ length: 7 }, (_, i) => <Skeleton key={i} height={92} />)}</div>
      <div className="tdr-models-layout">
        <div className="tdr-models-sk-rail"><Skeleton height={520} /></div>
        <div className="tdr-models-grid">{Array.from({ length: 6 }, (_, i) => <Skeleton key={i} height={300} />)}</div>
      </div>
    </div>
  );
}
