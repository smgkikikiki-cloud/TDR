import { Skeleton } from "@/components/design";

/** Model page loading state: breadcrumb, hero (16:9 picture + copy) and trim rows at their final size. */
export default function Loading() {
  return (
    <div className="tdr-wrap tdr-models-detail" aria-busy="true">
      <div className="tdr-models-crumbs"><Skeleton height={18} width={260} /></div>
      <div className="tdr-models-hero">
        <div className="tdr-models-hero__img"><Skeleton height={360} /></div>
        <div className="tdr-models-hero__copy"><Skeleton height={16} width={140} /><Skeleton height={44} width="70%" /><Skeleton height={36} width="60%" radius="pill" /><Skeleton height={96} /></div>
      </div>
      <div className="tdr-models-trims">{Array.from({ length: 4 }, (_, i) => <Skeleton key={i} height={64} />)}</div>
    </div>
  );
}
