import { Skeleton } from "@/components/design";

/** /market loading state: head, KPI trio and the first chart row at their final size (no spinner). */
export default function MarketLoading() {
  return (
    <div className="designPage tdr-market" aria-busy="true">
      <div className="tdr-wrap">
        <div className="tdr-market-sk-head"><Skeleton height={18} width={140} /><Skeleton height={44} width="55%" /><Skeleton height={20} width="70%" /></div>
        <div className="tdr-kpis tdr-market-kpis"><Skeleton height={112} /><Skeleton height={112} /><Skeleton height={112} /></div>
        <div className="tdr-market-grid"><Skeleton height={300} /><Skeleton height={300} /><Skeleton height={260} /><Skeleton height={260} /></div>
      </div>
    </div>
  );
}
