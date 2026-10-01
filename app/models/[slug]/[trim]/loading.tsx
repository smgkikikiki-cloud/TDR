import { Skeleton } from "@/components/design";

/** Trim page loading state: header, key facts and the first spec table at their final size. */
export default function Loading() {
  return (
    <div className="tdr-wrap tdr-models-detail" aria-busy="true">
      <div className="tdr-models-crumbs"><Skeleton height={18} width={320} /></div>
      <div className="tdr-models-trimhead"><div><Skeleton height={16} width={140} /><Skeleton height={44} width="60%" /></div><Skeleton height={96} /></div>
      <div className="tdr-models-facts">{Array.from({ length: 4 }, (_, i) => <Skeleton key={i} height={84} />)}</div>
      <Skeleton height={320} />
    </div>
  );
}
