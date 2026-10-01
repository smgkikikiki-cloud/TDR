import { Skeleton } from "@/components/design";

/** Brand index loading state: head, filter and the first table rows at their final size (no spinner). */
export function BrandIndexSkeleton() {
  return (
    <div className="tdr-wrap" aria-busy="true">
      <div className="tdr-models-sk-head"><Skeleton height={18} width={120} /><Skeleton height={48} width="50%" /><Skeleton height={20} width="70%" /></div>
      <Skeleton height={44} width={360} />
      <div className="tdr-brands-sk-rows">{Array.from({ length: 10 }, (_, i) => <Skeleton key={i} height={48} />)}</div>
    </div>
  );
}
