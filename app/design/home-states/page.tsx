import type { Metadata } from "next";
import { notFound } from "next/navigation";
import "../components/gallery.css";
import { CompareBlock } from "@/components/home/CompareSection";
import { DatabaseBlock } from "@/components/home/DatabaseSection";
import { summarizeCatalog, type HomeBrand, type HomeModel, type HomeTrim } from "@/lib/home/catalog-logic";

export const metadata: Metadata = { title: "Home block states", robots: { index: false, follow: false } };

const model = (id: string, brand: string, body: string, extra: Partial<HomeModel> = {}): HomeModel => ({
  id, slug: id, name_en: id.toUpperCase(), body_type: body, brands: { slug: brand, name_en: brand.toUpperCase() }, powertrains: ["ICE"], market_position: "Mass", ...extra,
});
const models: HomeModel[] = [
  model("model-a", "brand-one", "SEDAN", { retail_price_min: 700000 }), model("model-b", "brand-two", "CROSSOVER", { retail_price_min: 900000 }),
  model("model-c", "brand-three", "PICKUP"), model("model-d", "brand-one", "MPV"), model("model-e", "brand-four", "HATCHBACK"), model("model-f", "brand-five", "VAN"),
];
const trims: HomeTrim[] = [
  { model_id: "model-a", price_baht: 700000 }, { model_id: "model-a", price_baht: 760000 }, { model_id: "model-b", price_baht: 900000 }, { model_id: "model-b", price_baht: 990000 },
];
const brands: HomeBrand[] = [1, 2, 3, 4, 5].map((n) => ({ slug: `brand-${["one", "two", "three", "four", "five"][n - 1]}`, name_en: `Brand ${n}` }));
const catalog = summarizeCatalog(models, brands, trims);

/** Preview-only: the loading / empty / error / loaded states of Home's data blocks, with dummy fixtures (never real
 *  figures). Hidden on the production deployment. The locked and pending (blocker 11) blocks are static and always visible on Home. */
export default function HomeStates() {
  if (process.env.VERCEL_ENV === "production") notFound();
  const examples = catalog.compare;
  return (
    <div className="designPage">
      <div className="tdr-wrap tdr-gallery">
        <h2>Vehicle Database · loading</h2><DatabaseBlock state={{ kind: "loading" }} />
        <h2>Vehicle Database · empty</h2><DatabaseBlock state={{ kind: "empty" }} />
        <h2>Vehicle Database · error</h2><DatabaseBlock state={{ kind: "error" }} />
        <h2>Vehicle Database · loaded (dummy fixture)</h2><DatabaseBlock state={{ kind: "ok", catalog }} />
        <h2>Compare · loading</h2><CompareBlock state={{ kind: "loading" }} />
        <h2>Compare · empty</h2><CompareBlock state={{ kind: "empty" }} />
        <h2>Compare · error</h2><CompareBlock state={{ kind: "error" }} />
        <h2>Compare · loaded (dummy fixture)</h2>
        {examples.length >= 2 ? <CompareBlock state={{ kind: "ok", examples: [examples[0], examples[1]] }} /> : null}
      </div>
    </div>
  );
}
