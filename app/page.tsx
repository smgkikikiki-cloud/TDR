import { Suspense } from "react";
import "./home.css";
import { AboutStrip } from "@/components/home/AboutStrip";
import { AnalysisSection } from "@/components/home/AnalysisSection";
import { CompareSection, CompareSkeleton } from "@/components/home/CompareSection";
import { DatabaseSection, DatabaseSkeleton } from "@/components/home/DatabaseSection";
import { EntryCards } from "@/components/home/EntryCards";
import { HomeHero } from "@/components/home/HomeHero";
import { InfoSample } from "@/components/home/InfoSample";
import { IntelligenceBand } from "@/components/home/IntelligenceBand";
import { PlansSection } from "@/components/home/PlansSection";

export const dynamic = "force-dynamic";

/** Home (PAGES P01, design/reference/home_v7.html), migrated to the design system.
 *  Blocker 11: the market analysis engine is being replaced, so nothing here reads market figures through the old
 *  engine; the market-dependent blocks are pending blocks (components/home/states.tsx). The catalogue blocks are live. */
export default function Home() {
  return (
    <div className="designPage tdr-home">
      <div className="tdr-wrap">
        <HomeHero />
        <EntryCards />
      </div>
      <IntelligenceBand />
      <InfoSample />
      <Suspense fallback={<DatabaseSkeleton />}><DatabaseSection /></Suspense>
      <Suspense fallback={<CompareSkeleton />}><CompareSection /></Suspense>
      <AnalysisSection />
      <PlansSection />
      <AboutStrip />
    </div>
  );
}
