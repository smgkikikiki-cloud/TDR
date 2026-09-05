import { Fragment } from "react";
import Link from "next/link";
import { getBrands, getModels } from "@/lib/data";
import { FilterDisclosure } from "@/components/FilterDisclosure";
import { BODY_LABEL, bodyLabel } from "@/lib/body-labels";

type Sp = Record<string, string | undefined>;
type Opt = { value: string; label: string; group?: string };

const opts = (values: string[]): Opt[] => values.map((v) => ({ value: v, label: v }));

/** Body type is the entry point Thai buyers actually use, so it leads the rail,
 *  carries Thai labels and is grouped by family. The stored values are the
 *  unchanged body_type strings — only the labels and the order are new. */
const BODY_OPTIONS: Opt[] = [
  { value: "Sedan", label: "ซีดาน", group: "รถเก๋ง" },
  { value: "Hatchback", label: "แฮทช์แบ็ก", group: "รถเก๋ง" },
  { value: "Coupe", label: "คูเป้", group: "รถเก๋ง" },
  { value: "Crossover", label: "ครอสโอเวอร์", group: "SUV" },
  { value: "SUV (Monocoque)", label: "SUV โมโนค็อก", group: "SUV" },
  { value: "SUV (Ladder frame)", label: "SUV โครงกระบะ (PPV)", group: "SUV" },
  { value: "Pickup truck", label: "กระบะ", group: "กระบะ · รถตู้ · MPV" },
  { value: "MPV", label: "MPV", group: "กระบะ · รถตู้ · MPV" },
  { value: "Van", label: "รถตู้", group: "กระบะ · รถตู้ · MPV" },
];

/** The quick row: every body type, ordered by how often it is what a Thai
 *  buyer came here for. Each chip sets the same single body value the rail
 *  sets — nothing here filters across several values. */
const BODY_QUICK = ["Pickup truck", "SUV (Ladder frame)", "Crossover", "SUV (Monocoque)", "Sedan", "Hatchback", "MPV", "Van", "Coupe"];

const FACETS: { key: string; label: string; note?: string; options: Opt[] }[] = [
  { key: "body", label: "ประเภทตัวถัง", options: BODY_OPTIONS },
  { key: "powertrain", label: "ระบบขับเคลื่อน", options: opts(["ICE", "HEV", "PHEV", "REEV", "BEV"]) },
  { key: "segment", label: "ขนาดรถ (เก๋ง / SUV)", note: "สเกล A–E ใช้กับรถนั่ง กระบะและรถตู้ไม่มีค่านี้", options: opts(["A", "B", "C", "D", "E"]) },
  { key: "position", label: "ตำแหน่งตลาด", options: opts(["Mass", "Premium", "Luxury"]) },
  { key: "production", label: "แหล่งผลิต", options: opts(["CBU", "CKD", "SKD"]) },
];

const FILTER_LABEL: Record<string, string> = { brand: "แบรนด์", body: "ตัวถัง", powertrain: "ขับเคลื่อน", segment: "ขนาดรถ", position: "ตำแหน่ง", production: "แหล่งผลิต" };

function valueLabel(key: string, value: string) {
  return key === "body" ? BODY_LABEL[value] || value : value;
}

/** The catalog filter predicate. `skip` leaves one facet out so its option counts
 *  can be read against every OTHER active filter. Same comparisons as before. */
function matches(r: any, sp: Sp, skip?: string) {
  return (skip === "brand" || !sp.brand || r.brands?.slug === sp.brand)
    && (skip === "segment" || !sp.segment || r.segment === sp.segment)
    && (skip === "body" || !sp.body || r.body_type === sp.body)
    && (skip === "position" || !sp.position || r.market_position === sp.position)
    && (skip === "powertrain" || !sp.powertrain || (r.powertrains || []).includes(sp.powertrain))
    && (skip === "production" || !sp.production || r.production_type === sp.production);
}

function facetHit(r: any, key: string, value: string) {
  if (key === "body") return r.body_type === value;
  if (key === "powertrain") return (r.powertrains || []).includes(value);
  if (key === "segment") return r.segment === value;
  if (key === "position") return r.market_position === value;
  if (key === "production") return r.production_type === value;
  return false;
}

function href(sp: Sp, key: string, value: string | null) {
  const next = new URLSearchParams();
  for (const [k, v] of Object.entries(sp)) if (v && k !== key) next.set(k, v);
  if (value) next.set(key, value);
  const q = next.toString();
  return q ? `/models?${q}` : "/models";
}

function baht(min: any, max: any) {
  const f = (n: number) => Number(n).toLocaleString();
  if (!min && !max) return null;
  return min && max && min !== max ? `฿${f(min)}–${f(max)}` : `฿${f(min || max)}`;
}

function Card({ r }: { r: any }) {
  const brand = r.brands?.name_th || "";
  const meta = [bodyLabel(r.body_type), (r.powertrains || []).join(" / "), r.seats ? `${r.seats} ที่นั่ง` : null].filter(Boolean).join(" · ");
  const price = baht(r.retail_price_min, r.retail_price_max);
  const local = r.production_type === "CKD" || r.production_type === "SKD";
  return (
    <Link className="sfCard" href={`/models/${r.slug}`}>
      <div className="sfSlot">
        {r.image_url ? <img src={r.image_url} alt={r.name_th} /> : <><small>{(brand || "TDR").toUpperCase()}</small><b>{r.name_th}</b></>}
      </div>
      <div className="sfCardBody">
        <div className="sfEyebrow">{brand || " "}</div>
        <h3>{r.name_th}</h3>
        {meta ? <p className="sfCardMeta">{meta}</p> : <p className="sfCardMeta sfMissing">ยังไม่มีข้อมูลสเปกพื้นฐาน</p>}
        <div className="sfCardFoot">
          {price ? <span className="sfPrice">{price}</span> : <span className="sfMissing">ยังไม่ประกาศราคา</span>}
          {local ? <span className="sfLocal">ประกอบไทย</span> : r.production_type === "CBU" ? <span className="sfImported">นำเข้า CBU</span> : null}
        </div>
      </div>
    </Link>
  );
}

export default async function ModelsPage({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const sp = await searchParams;
  const [brands, all] = await Promise.all([getBrands(150), getModels(600)]);
  const current = (all as any[]).filter((r) => r.status !== "discontinued");
  const models = current.filter((r) => matches(r, sp));

  const brandCount = new Set(current.map((r) => r.brands?.slug).filter(Boolean)).size;
  const assembled = current.filter((r) => r.production_type === "CKD" || r.production_type === "SKD").length;
  const imported = current.filter((r) => r.production_type === "CBU").length;
  const activeBrand = brands.find((b: any) => b.slug === sp.brand);
  const activeFilters = Object.entries(sp).filter(([k, v]) => v && FILTER_LABEL[k]);
  const bodyPool = current.filter((r) => matches(r, sp, "body"));

  return <>
    <div className="sfStrip sfBleed">
      <div className="sfStripItem"><b className="sfNum">{current.length.toLocaleString()}</b><span>รุ่นในแคตตาล็อก</span></div>
      <div className="sfStripItem"><b className="sfNum">{brandCount.toLocaleString()}</b><span>แบรนด์</span></div>
      <div className="sfStripItem"><b className="sfNum">{assembled.toLocaleString()}</b><span>ประกอบในไทย (CKD/SKD)</span></div>
      <div className="sfStripItem"><b className="sfNum">{imported.toLocaleString()}</b><span>นำเข้าทั้งคัน (CBU)</span></div>
      <div className="sfStripNote">นับจากรุ่นที่ยังจำหน่ายอยู่ในฐานข้อมูล TDR รุ่นที่เลิกจำหน่ายแล้วไม่ถูกนับ</div>
    </div>

    <section className="sfPageHead">
      <div>
        <div className="sfEyebrow">VEHICLE CATALOG</div>
        <h1>รถที่จำหน่ายในประเทศไทย</h1>
        <p>รถเก๋ง SUV MPV Pickup และ light commercial รุ่นปัจจุบัน พร้อมรุ่นย่อย ราคา Powertrain ที่มา และลิงก์เข้าสู่ข้อมูลอุตสาหกรรมสำหรับรถที่ผลิตในไทย</p>
      </div>
      <div className="sfPageHeadAside">
        <div className="sfEyebrow ink">ตรงกับตัวกรอง</div>
        <b className="sfNum">{models.length.toLocaleString()}</b>
        <span>จาก {current.length.toLocaleString()} รุ่น</span>
      </div>
    </section>

    <div className="sfTypeRow">
      <Link className={sp.body ? undefined : "on"} href={href(sp, "body", null)}>
        <b>ทุกประเภท</b><em className="sfNum">{bodyPool.length.toLocaleString()}</em>
      </Link>
      {BODY_QUICK.map((value) => {
        const n = bodyPool.filter((r) => r.body_type === value).length;
        const on = sp.body === value;
        return (
          <Link key={value} className={[on ? "on" : null, !on && n === 0 ? "off" : null].filter(Boolean).join(" ") || undefined} href={href(sp, "body", on ? null : value)}>
            <b>{BODY_LABEL[value]}</b><em className="sfNum">{n.toLocaleString()}</em>
          </Link>
        );
      })}
    </div>

    <div className="sfBrandRail">
      <Link className={sp.brand ? undefined : "on"} href={href(sp, "brand", null)}><span>ทั้งหมด</span>ทุกแบรนด์</Link>
      {brands.map((b: any) => (
        <Link key={b.id} className={sp.brand === b.slug ? "on" : undefined} href={href(sp, "brand", b.slug)}>
          {b.logo_url ? <img src={b.logo_url} alt="" /> : <span>{b.name_th.slice(0, 2).toUpperCase()}</span>}
          {b.name_th}
        </Link>
      ))}
    </div>

    <div className="sfCatalog sfBleed">
      <div className="sfLayout">
        <FilterDisclosure label={`ตัวกรอง${activeFilters.length ? ` · ${activeFilters.length}` : ""}`}>
          <div className="sfRail">
            <div className="sfRailHead">
              <b>กรองรุ่นรถ</b>
              {activeFilters.length ? <Link href="/models">ล้างทั้งหมด</Link> : null}
            </div>
            {FACETS.map((f) => {
              const pool = current.filter((r) => matches(r, sp, f.key));
              return (
                <div className="sfGroup" key={f.key}>
                  <h3>{f.label}</h3>
                  {f.note ? <p className="sfGroupNote">{f.note}</p> : null}
                  {f.options.map((opt, i) => {
                    const on = sp[f.key] === opt.value;
                    const n = pool.filter((r) => facetHit(r, f.key, opt.value)).length;
                    const cls = ["sfOpt", on ? "on" : null, !on && n === 0 ? "off" : null].filter(Boolean).join(" ");
                    const newGroup = opt.group && opt.group !== f.options[i - 1]?.group;
                    return (
                      <Fragment key={opt.value}>
                        {newGroup ? <div className="sfOptGroup">{opt.group}</div> : null}
                        <Link className={cls} href={href(sp, f.key, on ? null : opt.value)}>
                          <span className="sfOptLabel"><i className="sfOptBox" />{opt.label}</span>
                          <em>{n.toLocaleString()}</em>
                        </Link>
                      </Fragment>
                    );
                  })}
                </div>
              );
            })}
          </div>
        </FilterDisclosure>

        <div>
          <div className="sfResultBar">
            <h2>{activeBrand ? activeBrand.name_th : "รถทั้งหมด"} <span className="sfNum">{models.length.toLocaleString()} รุ่น</span></h2>
            <Link className="sfChipClear" href="/brands">ดูตามแบรนด์ →</Link>
          </div>

          {activeFilters.length ? (
            <div className="sfChips">
              {activeFilters.map(([k, v]) => (
                <Link className="sfChip" key={k} href={href(sp, k, null)}>
                  {FILTER_LABEL[k]} · {k === "brand" ? activeBrand?.name_th || v : valueLabel(k, v as string)}
                  <svg width="11" height="11" viewBox="0 0 12 12" stroke="currentColor" strokeWidth="1.6" fill="none"><path d="M2 2l8 8M10 2l-8 8" /></svg>
                </Link>
              ))}
              <Link className="sfChipClear" href="/models">ล้างทั้งหมด</Link>
            </div>
          ) : null}

          {models.length ? (
            <div className="sfGrid">{models.map((r: any) => <Card key={r.id} r={r} />)}</div>
          ) : (
            <div className="sfEmpty">
              <b>ไม่มีรุ่นที่ตรงกับตัวกรองนี้</b>
              <span>ลองเอาตัวกรองบางอันออก หรือ<Link href="/models"> ล้างทั้งหมด</Link></span>
            </div>
          )}
        </div>
      </div>
    </div>
  </>;
}
