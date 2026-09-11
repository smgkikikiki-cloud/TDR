import { getCanonicalCompareSpecFacts, getCanonicalCompareTrims } from "@/lib/canonical-data";
import type { FreeCompareTrim } from "@/lib/free-compare";
import type { CompareSpecFact } from "@/lib/compare-workspace";
import { CompareWorkspace } from "./CompareWorkspace";

type SearchParams = Record<string, string | string[] | undefined>;

function selectedValues(value: string | string[] | undefined) {
  const raw = Array.isArray(value) ? value : value ? [value] : [];
  return [...new Set(raw.filter(Boolean))].slice(0, 4);
}

function firstValue(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value;
}

export default async function ComparePage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const sp = await searchParams;
  const all = await getCanonicalCompareTrims(600) as FreeCompareTrim[];
  const requestedTrims = selectedValues(sp.trims);
  const requestedModels = selectedValues(sp.models);
  const byId = new Map(all.map((trim) => [trim.id, trim]));
  const validTrimIds = requestedTrims.filter((id) => byId.has(id));
  const validModelIds = new Set(all.map((trim) => trim.model_id).filter(Boolean));
  const facts = await getCanonicalCompareSpecFacts(validTrimIds) as CompareSpecFact[];

  return <div className="comparePage comparePageV2">
    <CompareWorkspace
      allTrims={all}
      initialTrimIds={validTrimIds}
      initialModelIds={requestedModels}
      facts={facts}
      initialDiffOnly={firstValue(sp.diff) === "1"}
      missingTrimSelection={validTrimIds.length !== requestedTrims.length}
      missingModelSelection={requestedModels.some((id) => !validModelIds.has(id))}
    />
  </div>;
}
