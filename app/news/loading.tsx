import { Skeleton } from "@/components/design";

/** News list loading state: head and rows at their final size, no spinner. */
export default function Loading() {
  return (
    <div className="tdr-wrap tdr-news" aria-busy="true">
      <Skeleton height={16} width={80} />
      <Skeleton height={44} width={160} />
      <div className="tdr-news__list">
        {Array.from({ length: 4 }, (_, i) => (
          <div key={i} className="tdr-news__item"><Skeleton height={135} /><div><Skeleton height={16} width={120} /><Skeleton height={30} width="80%" /><Skeleton height={44} /></div></div>
        ))}
      </div>
    </div>
  );
}
