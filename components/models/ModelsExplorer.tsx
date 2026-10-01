import Link from "next/link";
import { Chip } from "@/components/design";
import { BodyTypeTile } from "@/components/models/BodyTypeTile";
import { FilterRail } from "@/components/models/FilterRail";
import { ModelCard } from "@/components/models/ModelCard";
import { SortSelect } from "@/components/models/SortSelect";
import { BlockEmpty } from "@/components/models/states";
import { BODY_LABEL } from "@/lib/body-labels";
import { BODY_FAMILIES, bodyParam, familyForSelection, familyParam, parseBodyParam, toggleBodyValue } from "@/lib/body-families";
import { displayName } from "@/lib/display-name";
import { formatNumber } from "@/lib/design/format";
import {
  POWERTRAIN_OPTION_LABEL, PRODUCTION_LABEL, facetHit, matchesFilters, modelsHref, pageWindow, parsePage, parseSort, sortModels,
  visibleOption, type FilterKey, type ModelListRow, type ModelsParams,
} from "@/lib/models/list";

type Opt = { value: string; label: string };
const opts = (values: string[], labels: Record<string, string> = {}): Opt[] => values.map((v) => ({ value: v, label: labels[v] || v }));

/** Individual body values for the rail (a family chip above sets several at once; these tick one at a time). */
const BODY_OPTIONS: Opt[] = [...BODY_FAMILIES.flatMap((f) => f.values), "TRUCK"]
  .map((v) => ({ value: v, label: BODY_LABEL[v] || v }));

const FACETS: { key: Exclude<FilterKey, "brand">; label: string; note?: string; options: Opt[] }[] = [
  { key: "body", label: "ประเภทตัวถัง", options: BODY_OPTIONS },
  { key: "powertrain", label: "ระบบขับเคลื่อน", options: opts(["ICE", "BEV", "HEV", "PHEV", "REEV"], POWERTRAIN_OPTION_LABEL) },
  { key: "segment", label: "ขนาดรถ (เก๋ง / SUV)", note: "สเกล A–E ใช้กับรถนั่ง กระบะและรถตู้ไม่มีค่านี้", options: opts(["A", "B", "C", "D", "E"]) },
  { key: "position", label: "ตำแหน่งตลาด", options: opts(["Mass", "Premium", "Luxury"]) },
  { key: "production", label: "แหล่งผลิต", options: opts(["CKD", "SKD", "CBU"], PRODUCTION_LABEL) },
];
export const FILTER_LABEL: Record<FilterKey, string> = { brand: "แบรนด์", body: "ตัวถัง", powertrain: "ขับเคลื่อน", segment: "ขนาดรถ", position: "ตำแหน่ง", production: "แหล่งผลิต" };
const BRAND_RAIL_LIMIT = 10;


export type ExplorerModel = ModelListRow & { status?: unknown; id: string };

/** The catalogue explorer shared by /models (P02) and a brand page (P06): body-family tiles, filter rail (bottom sheet at
 *  <=1023px), sort, active chips, ModelCard grid and the 12-at-a-time load step. All state is in the URL (`body,
 *  powertrain, segment, position, production, brand, sort, page`).
 *
 *  `current` is the set of models in scope (the whole catalogue, or one brand's). With `fixedBrand` the brand filter is a
 *  preset: it is applied silently, is not offered in the rail, is not an active chip, and never appears in a URL. All links
 *  are built on `basePath`. */
export function ModelsExplorer({ sp, current, brands, trimCounts, brandCount, basePath = "/models", fixedBrand, tilesToCatalogue }: {
  sp: ModelsParams;
  current: ExplorerModel[];
  brands: any[];
  trimCounts: Map<string, number>;
  brandCount: number;
  basePath?: string;
  fixedBrand?: { slug: string; name: string };
  /** Brand pages: the body-family tiles open the catalogue with the brand preset (`/models?brand=<slug>&body=<values>`, the
   *  PR 6 encoding) instead of filtering in place. */
  tilesToCatalogue?: boolean;
}) {
  const href = (patch: Parameters<typeof modelsHref>[1]) => modelsHref(sp, patch, basePath);
  const scoped: ModelsParams = fixedBrand ? { ...sp, brand: fixedBrand.slug } : sp;
  const sort = parseSort(sp.sort);
  const page = parsePage(sp.page);
  const selectedBody = parseBodyParam(sp.body);
  const filtered = sortModels(current.filter((r) => matchesFilters(r, scoped)), sort);
  const win = pageWindow(filtered, page);
  const activeBrand = fixedBrand ? null : brands.find((b) => b.slug === sp.brand);
  const bodyPool = current.filter((r) => matchesFilters(r, scoped, "body"));
  const activeFamily = familyForSelection(selectedBody);
  const clearHref = modelsHref({ sort: sp.sort }, {}, basePath);

  const activeChips: { key: FilterKey; label: string; href: string }[] = [];
  for (const key of ["body", "powertrain", "segment", "position", "production", "brand"] as FilterKey[]) {
    const raw = sp[key];
    if (!raw || (fixedBrand && key === "brand")) continue;
    let label = raw;
    if (key === "body") label = activeFamily?.label || selectedBody.map((v) => BODY_LABEL[v] || v).join(" + ");
    else if (key === "brand") label = displayName(activeBrand, raw);
    else if (key === "powertrain") label = POWERTRAIN_OPTION_LABEL[raw] || raw;
    else if (key === "production") label = PRODUCTION_LABEL[raw] || raw;
    activeChips.push({ key, label, href: href({ [key]: null }) });
  }

  // Brand options for the rail: the biggest brands under the other filters, plus the active one so it can be undone.
  const brandPool = current.filter((r) => matchesFilters(r, scoped, "brand"));
  const perBrand = new Map<string, number>();
  for (const r of brandPool) if (r.brands?.slug) perBrand.set(r.brands.slug, (perBrand.get(r.brands.slug) || 0) + 1);
  const brandOptions = [...perBrand.entries()]
    .map(([slug, count]) => ({ slug, count, name: displayName(brands.find((b) => b.slug === slug) || { slug }) }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, "en"));
  const shownBrands = brandOptions.slice(0, BRAND_RAIL_LIMIT);
  if (sp.brand && !fixedBrand && !shownBrands.some((b) => b.slug === sp.brand)) shownBrands.push({ slug: sp.brand, count: perBrand.get(sp.brand) || 0, name: displayName(activeBrand, sp.brand) });

  const sortParams: Record<string, string> = {};
  for (const [k, v] of Object.entries(sp)) if (v && k !== "sort" && k !== "page" && !(fixedBrand && k === "brand")) sortParams[k] = v;

  const facetBlocks = FACETS.map((f) => {
    const pool = current.filter((r) => matchesFilters(r, scoped, f.key));
    const options = f.options
      .map((opt) => {
        const on = f.key === "body" ? selectedBody.includes(opt.value) : sp[f.key] === opt.value;
        const count = pool.filter((r) => facetHit(r, f.key, opt.value)).length;
        const optHref = f.key === "body"
          ? href({ body: bodyParam(toggleBodyValue(selectedBody, opt.value)) })
          : href({ [f.key]: on ? null : opt.value });
        return { ...opt, on, count, href: optHref };
      })
      .filter((o) => visibleOption(o.count, o.on));
    return { f, options };
  }).filter((b) => b.options.length > 0);

  return <>
    <nav className="tdr-models-tiles" aria-label="ประเภทตัวถัง">
      {tilesToCatalogue && fixedBrand ? (
        <>
          <BodyTypeTile href={modelsHref({ brand: fixedBrand.slug }, {})} label="ทั้งหมด" count={bodyPool.length} />
          {BODY_FAMILIES.map((family) => (
            <BodyTypeTile key={family.key} icon={family.icon} label={family.label}
              count={bodyPool.filter((r) => !!r.body_type && family.values.includes(r.body_type)).length}
              href={modelsHref({ brand: fixedBrand.slug, body: familyParam(family) }, {})} />
          ))}
        </>
      ) : (
        <>
          <BodyTypeTile href={href({ body: null })} label="ทั้งหมด" count={bodyPool.length} on={selectedBody.length === 0} />
          {BODY_FAMILIES.map((family) => {
            const on = activeFamily?.key === family.key;
            return (
              <BodyTypeTile key={family.key} icon={family.icon} label={family.label} on={on}
                count={bodyPool.filter((r) => !!r.body_type && family.values.includes(r.body_type)).length}
                href={href({ body: on ? null : familyParam(family) })} />
            );
          })}
        </>
      )}
    </nav>

    <div className="tdr-models-layout">
      <FilterRail label={`ตัวกรอง${activeChips.length ? ` · ${activeChips.length}` : ""}`} resultLabel={`ดูผลลัพธ์ ${formatNumber(filtered.length)} รุ่น`}>
        <div className="tdr-models-rail__head">
          <b>กรองรุ่นรถ</b>
          {activeChips.length ? <Link prefetch={false} href={clearHref}>ล้างทั้งหมด</Link> : null}
        </div>
        {facetBlocks.map(({ f, options }) => (
          <div className="tdr-models-fg" key={f.key}>
            <h3>{f.label}</h3>
            {f.note ? <p className="tdr-models-fg__note">{f.note}</p> : null}
            {options.map((o) => (
              <Link key={o.value} prefetch={false} href={o.href} className={o.on ? "tdr-models-fo tdr-models-fo--on" : "tdr-models-fo"} aria-current={o.on ? "true" : undefined}>
                <i aria-hidden="true">{o.on ? "✓" : ""}</i><span>{o.label}</span><em>{formatNumber(o.count)}</em>
              </Link>
            ))}
          </div>
        ))}
        {fixedBrand ? null : (
          <div className="tdr-models-fg">
            <h3>แบรนด์</h3>
            {shownBrands.map((b) => {
              const on = sp.brand === b.slug;
              return (
                <Link key={b.slug} prefetch={false} href={href({ brand: on ? null : b.slug })} className={on ? "tdr-models-fo tdr-models-fo--on" : "tdr-models-fo"} aria-current={on ? "true" : undefined}>
                  <i aria-hidden="true">{on ? "✓" : ""}</i><span>{b.name}</span><em>{formatNumber(b.count)}</em>
                </Link>
              );
            })}
            <Link className="tdr-models-more" href="/brands">ดูทั้ง {formatNumber(brandCount)} แบรนด์ →</Link>
          </div>
        )}
      </FilterRail>

      <div className="tdr-models-results">
        <div className="tdr-models-rbar">
          <h2>{fixedBrand ? `รถของ ${fixedBrand.name}` : activeBrand ? displayName(activeBrand) : "รถทั้งหมด"} <span className="tdr-models-mono">{formatNumber(filtered.length)} รุ่น</span></h2>
          <SortSelect value={sort} params={sortParams} action={basePath} />
        </div>

        {activeChips.length ? (
          <div className="tdr-chips tdr-models-active">
            {activeChips.map((c) => (
              <Chip key={c.key} prefetch={false} href={c.href} className="tdr-chip--on" aria-label={`เอาตัวกรอง ${FILTER_LABEL[c.key]} ${c.label} ออก`}>
                {FILTER_LABEL[c.key]} · {c.label} <span className="tdr-chip__x" aria-hidden="true">✕</span>
              </Chip>
            ))}
            <Link className="tdr-models-clear" prefetch={false} href={clearHref}>ล้างทั้งหมด</Link>
          </div>
        ) : null}

        {win.items.length ? (
          <>
            <div className="tdr-models-grid">
              {win.items.map((r) => <ModelCard key={r.id} r={r} trimCount={trimCounts.get(r.id)} />)}
            </div>
            <div className="tdr-models-more-row">
              {win.hasMore
                ? <Link className="tdr-btn tdr-btn--secondary" prefetch={false} href={href({ page: String(win.nextPage) })} scroll={false}>โหลดเพิ่ม · แสดง {formatNumber(win.shown)} จาก {formatNumber(win.total)}</Link>
                : <span className="tdr-models-muted">แสดงครบ {formatNumber(win.total)} รุ่น</span>}
            </div>
          </>
        ) : (
          <BlockEmpty title="ไม่มีรุ่นที่ตรงกับตัวกรองนี้" text="ลองเอาตัวกรองบางอันออก">
            <Link className="tdr-models-clear" prefetch={false} href={clearHref}>ล้างทั้งหมด</Link>
          </BlockEmpty>
        )}
        <p className="tdr-models-src-line">ราคาจาก Price Ledger ของ TDR (ราคาขายปลีกที่ประกาศ) · รุ่นที่ไม่มีราคาจะแสดง &ldquo;ยังไม่ประกาศราคา&rdquo; · สเปกจาก TDR Vehicle Master</p>
      </div>
    </div>
  </>;
}
