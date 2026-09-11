import Link from "next/link";
import { getCanonicalBrands, getCanonicalModels } from "@/lib/canonical-data";
import { displayName } from "@/lib/display-name";
import { byRelevance } from "@/lib/relevance";
import { BODY_LABEL, bodyLabel } from "@/lib/body-labels";
import { isCatalogVisible, isVerifiedCurrent } from "@/lib/public-retail-lifecycle";
import { CatalogResults } from "./CatalogResults";
import { CatalogSort } from "./CatalogSort";
import styles from "./catalog.module.css";

type Sp = Record<string, string | undefined>;

const QUICK_BODIES = [
  { value: "SEDAN", label: "Sedan" },
  { value: "HATCHBACK", label: "Hatchback" },
  { value: "CROSSOVER", label: "SUV / Crossover" },
  { value: "PPV", label: "PPV" },
  { value: "PICKUP", label: "Pickup" },
  { value: "MPV", label: "MPV" },
  { value: "VAN", label: "Van" },
];

const FILTER_LABEL: Record<string, string> = {
  brand: "แบรนด์",
  body: "ตัวถัง",
  powertrain: "Powertrain",
  segment: "Segment",
  position: "ตำแหน่งตลาด",
  production: "แหล่งผลิต",
};

function matches(r: any, sp: Sp) {
  return (!sp.brand || r.brands?.slug === sp.brand)
    && (!sp.segment || r.segment === sp.segment)
    && (!sp.body || r.body_type === sp.body)
    && (!sp.position || r.market_position === sp.position)
    && (!sp.powertrain || (r.powertrains || []).includes(sp.powertrain))
    && (!sp.production || r.production_type === sp.production);
}

function matchesSearch(r: any, query: string) {
  const term = query.trim().toLocaleLowerCase();
  if (!term) return true;
  return [
    r.name_en,
    r.name_th,
    r.slug,
    r.brands?.name_en,
    r.brands?.name_th,
    r.brands?.slug,
  ].some((value) => String(value || "").toLocaleLowerCase().includes(term));
}

function href(sp: Sp, key: string, value: string | null) {
  const next = new URLSearchParams();
  for (const [k, v] of Object.entries(sp)) if (v && k !== key) next.set(k, v);
  if (value) next.set(key, value);
  const query = next.toString();
  return query ? `/models?${query}` : "/models";
}

function clearFiltersHref(sp: Sp) {
  const next = new URLSearchParams();
  if (sp.q) next.set("q", sp.q);
  if (sp.sort) next.set("sort", sp.sort);
  const query = next.toString();
  return query ? `/models?${query}` : "/models";
}

function valueLabel(key: string, value: string, brands: any[]) {
  if (key === "brand") return displayName(brands.find((brand: any) => brand.slug === value), value);
  if (key === "body") return BODY_LABEL[value] || value;
  return value;
}

function priceLabel(r: any) {
  if (!isVerifiedCurrent(r.retail_lifecycle)) return null;
  const min = Number(r.retail_price_min || 0);
  const max = Number(r.retail_price_max || 0);
  const f = (value: number) => value.toLocaleString("th-TH");
  if (!min && !max) return null;
  if (min && max && min !== max) return `฿${f(min)} – ${f(max)}`;
  return `฿${f(min || max)}`;
}

function sortModels(rows: any[], mode: string) {
  if (mode === "new") {
    return [...rows].sort((a, b) => {
      const ay = Number(a.launch_year || 0), by = Number(b.launch_year || 0);
      const am = Number(a.launch_month || 0), bm = Number(b.launch_month || 0);
      return by - ay || bm - am || displayName(a).localeCompare(displayName(b));
    });
  }
  if (mode === "price-asc" || mode === "price-desc") {
    const price = (row: any) => {
      const value = Number(row.retail_price_min || row.retail_price_max || 0);
      return value > 0 ? value : Number.POSITIVE_INFINITY;
    };
    return [...rows].sort((a, b) => {
      const av = price(a), bv = price(b);
      if (av === bv) return displayName(a).localeCompare(displayName(b));
      if (!Number.isFinite(av)) return 1;
      if (!Number.isFinite(bv)) return -1;
      return mode === "price-asc" ? av - bv : bv - av;
    });
  }
  if (mode === "az") return [...rows].sort((a, b) => displayName(a).localeCompare(displayName(b)));
  return byRelevance(rows, new Map());
}

export default async function ModelsPage({ searchParams }: { searchParams: Promise<Sp> }) {
  const sp = await searchParams;
  const [brands, all] = await Promise.all([getCanonicalBrands(150), getCanonicalModels(600)]);
  const catalog = (all as any[]).filter((row) => isCatalogVisible(row.retail_lifecycle));
  const q = sp.q || "";
  const sort = ["new", "price-asc", "price-desc", "az"].includes(sp.sort || "") ? sp.sort! : "recommended";
  const filtered = catalog.filter((row) => matches(row, sp) && matchesSearch(row, q));
  const models = sortModels(filtered, sort);
  const activeFilters = Object.entries(sp).filter(([key, value]) => Boolean(value) && Boolean(FILTER_LABEL[key]));
  const filterCount = activeFilters.length;
  const currentQuery = new URLSearchParams(Object.entries(sp).filter(([, value]) => Boolean(value)) as [string, string][]).toString();

  const clientModels = models.map((row: any) => ({
    id: row.id,
    slug: row.slug,
    brand: displayName(row.brands),
    name: displayName(row),
    imageUrl: row.image_url || null,
    bodyLabel: bodyLabel(row.body_type) || null,
    powertrainLabel: (row.powertrains || []).join(" / ") || null,
    seats: row.seats || null,
    productionType: row.production_type || null,
    verifiedCurrent: isVerifiedCurrent(row.retail_lifecycle),
    priceLabel: priceLabel(row),
  }));

  return <div className={styles.page}>
    <section className={styles.hero}>
      <div className={styles.eyebrow}>VEHICLE CATALOG</div>
      <h1>แคทตาล็อกรถยนต์</h1>
      <p>ค้นหารุ่นรถ เปรียบเทียบสเปก และสำรวจรถในตลาดไทยจาก Vehicle Master ชุดเดียวกับเครื่องมือวิเคราะห์ของ TDR</p>
    </section>

    <div className={styles.searchRow}>
      <form className={styles.searchForm} method="get">
        <span className={styles.searchIcon}>⌕</span>
        <input name="q" defaultValue={q} placeholder="ค้นหาแบรนด์หรือรุ่นรถ — เช่น Camry, BYD Sealion 6, Honda, BMW..." aria-label="ค้นหาแบรนด์หรือรุ่นรถ" />
        {Object.entries(sp).filter(([key, value]) => key !== "q" && Boolean(value)).map(([key, value]) => <input key={key} type="hidden" name={key} value={value} />)}
        <button type="submit">ค้นหา</button>
      </form>
      <div className={styles.examples}>
        <span>ตัวอย่าง</span>
        {["Toyota", "Yaris Cross", "BYD", "HR-V"].map((term) => <Link key={term} href={href(sp, "q", term)}>{term}</Link>)}
      </div>
    </div>

    <nav className={styles.quickRow} aria-label="เลือกประเภทรถ">
      <Link className={`${styles.quick} ${!sp.body ? styles.quickOn : ""}`} href={href(sp, "body", null)}>ทั้งหมด</Link>
      {QUICK_BODIES.map((item) => <Link key={item.value} className={`${styles.quick} ${sp.body === item.value ? styles.quickOn : ""}`} href={href(sp, "body", sp.body === item.value ? null : item.value)}>{item.label}</Link>)}
    </nav>

    <div className={styles.toolRow}>
      <div className={styles.toolLeft}>
        <details className={styles.filterDisclosure}>
          <summary>⌁ ตัวกรอง{filterCount ? ` · ${filterCount}` : ""}</summary>
          <form className={styles.filterPanel} method="get">
            {q ? <input type="hidden" name="q" value={q} /> : null}
            {sort !== "recommended" ? <input type="hidden" name="sort" value={sort} /> : null}
            <div className={styles.filterGrid}>
              <label>แบรนด์<select name="brand" defaultValue={sp.brand || ""}><option value="">ทุกแบรนด์</option>{brands.map((brand: any) => <option key={brand.id} value={brand.slug}>{displayName(brand)}</option>)}</select></label>
              <label>ประเภทตัวถัง<select name="body" defaultValue={sp.body || ""}><option value="">ทุกประเภท</option>{["SEDAN","HATCHBACK","COUPE","CROSSOVER","PPV","OFFROAD","PICKUP","MPV","WAGON","VAN","TRUCK"].map((value) => <option key={value} value={value}>{BODY_LABEL[value] || value}</option>)}</select></label>
              <label>Powertrain<select name="powertrain" defaultValue={sp.powertrain || ""}><option value="">ทุกระบบ</option>{["ICE","HEV","PHEV","REEV","BEV"].map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
              <label>Segment<select name="segment" defaultValue={sp.segment || ""}><option value="">ทุก Segment</option>{["A","B","C","D","E"].map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
              <label>ตำแหน่งตลาด<select name="position" defaultValue={sp.position || ""}><option value="">ทั้งหมด</option>{["Mass","Premium","Luxury"].map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
              <label>แหล่งผลิต<select name="production" defaultValue={sp.production || ""}><option value="">ทั้งหมด</option>{["CBU","CKD","SKD"].map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
            </div>
            <div className={styles.filterActions}><Link href={clearFiltersHref(sp)}>ล้างตัวกรอง</Link><button type="submit">ใช้ตัวกรอง</button></div>
          </form>
        </details>

        {(q || activeFilters.length) ? <div className={styles.chipRow}>
          {q ? <Link className={styles.chip} href={href(sp, "q", null)}>ค้นหา · {q} ×</Link> : null}
          {activeFilters.map(([key, value]) => <Link className={styles.chip} key={key} href={href(sp, key, null)}>{FILTER_LABEL[key]} · {valueLabel(key, value as string, brands)} ×</Link>)}
          <Link className={styles.clear} href="/models">ล้างทั้งหมด</Link>
        </div> : null}
      </div>

      <div className={styles.resultTools}>
        <span className={styles.resultCount}><b>{models.length.toLocaleString("th-TH")}</b> รุ่น</span>
        <CatalogSort value={sort} query={currentQuery} />
      </div>
    </div>

    {models.length
      ? <CatalogResults models={clientModels} />
      : <div className={styles.empty}><b>ไม่พบรถที่ตรงกับเงื่อนไขนี้</b><span>ลองเอาตัวกรองบางรายการออก หรือ <Link href="/models">ล้างทั้งหมด</Link></span></div>}
  </div>;
}
