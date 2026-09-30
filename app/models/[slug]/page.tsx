import Link from "next/link";
import { notFound } from "next/navigation";
import { Card, CardHead, Chip } from "@/components/design";
import { CompareToggle } from "@/components/models/CompareTray";
import { ModelCard } from "@/components/models/ModelCard";
import { BlockEmpty } from "@/components/models/states";
import {
  getCanonicalHistoricalTrims, getCanonicalModelBundle, getCanonicalRelatedModels, getModelMarketTeasers,
} from "@/lib/canonical-data";
import { getProductionProgramsByModel } from "@/lib/data";
import { bodyLabel } from "@/lib/body-labels";
import { familyOfBody } from "@/lib/body-families";
import { displayName } from "@/lib/display-name";
import { formatNumber } from "@/lib/design/format";
import { modelRangeSummary, preferredRangeForTrim } from "@/lib/model-range-summary";
import { trimSummarySpecs } from "@/lib/model-trim-summary";
import { POWERTRAIN_LABEL, bahtRangeText, pictureCredit } from "@/lib/models/list";
import { formatThaiDate } from "@/lib/models/trim-specs";
import { loadSpecFieldRegistry } from "@/lib/spec-field-registry";
import { trimLocalId } from "@/lib/trim-editor-state";

const baht = (n: unknown) => (Number(n) > 0 ? `฿${Number(n).toLocaleString("en-US")}` : null);
const launch = (r: any) => [r.launch_quarter, r.launch_year].filter(Boolean).join(" ") || null;
/** Only http(s) links are ever rendered as links. */
const safeUrl = (value: unknown) => (/^https?:\/\//i.test(String(value ?? "")) ? String(value) : null);

function ptSummary(p: any) {
  const b: string[] = [];
  if (p.displacement_cc) b.push(`${Number(p.displacement_cc).toLocaleString("en-US")} cc`);
  if (p.battery_capacity_kwh) b.push(`${p.battery_capacity_kwh} kWh${p.battery_chemistry ? ` ${p.battery_chemistry}` : ""}`);
  if (p.powertrain_type) b.push(p.powertrain_type);
  if (p.horsepower_ps) b.push(`${p.horsepower_ps} PS`);
  return b.join(" · ") || p.label || "Powertrain";
}

/** One current trim as an accordion row: name, powertrain, declared range, list price (a promotion only adds a tag;
 *  the list price stays the primary figure). Opened, it shows six summary specs, the description, active campaigns
 *  with their conditions and source, and the link to the full spec page. */
function TrimRow({ t, ptById, specFields, slug }: { t: any; ptById: Map<any, any>; specFields: any[]; slug: string }) {
  const linked = (t.trim_powertrains || []).map((x: any) => ptById.get(x.powertrain_id)).filter(Boolean);
  const price = baht(t.price_baht);
  const offers = (t.campaign_quote?.campaign_options || []).filter((offer: any) => offer.status_as_of === "ACTIVE");
  const ends = offers.map((o: any) => String(o.valid_to || "")).filter(Boolean).sort()[0];
  const summarySpecs = trimSummarySpecs(t, specFields, 6);
  const range = preferredRangeForTrim(t);
  const rangeSource = safeUrl(t.range_source_url);
  return (
    <details className="tdr-models-trim">
      <summary>
        <span className="tdr-models-trim__name">
          <b>{t.name}</b>
          <small>{linked.map((p: any) => ptSummary(p)).join(" / ")}</small>
        </span>
        <span className="tdr-models-trim__nums">
          {range ? <span className="tdr-models-mono">{range.value.toLocaleString("en-US")} km {range.cycle}</span> : null}
          {price ? <strong className="tdr-models-mono">{price}</strong> : <span className="tdr-models-miss">ไม่ระบุราคา</span>}
          {offers.length ? <span className="tdr-models-promo">ราคาโปรโมชัน{ends ? ` · ถึง ${formatThaiDate(ends) || ends}` : ""}</span> : null}
        </span>
      </summary>
      <div className="tdr-models-trim__body">
        {summarySpecs.length ? (
          <dl className="tdr-models-specgrid">
            {summarySpecs.map((spec) => <div key={spec.key}><dt>{spec.label}</dt><dd>{spec.value}</dd></div>)}
          </dl>
        ) : null}
        {t.description ? <p>{t.description}</p> : summarySpecs.length ? null : <p className="tdr-models-miss">ยังไม่มีรายละเอียดอุปกรณ์ของรุ่นย่อยนี้</p>}
        {offers.length ? (
          <ul className="tdr-models-offers">
            {offers.map((offer: any) => {
              const src = safeUrl(offer.source_ref);
              const amount = baht(offer.amount_thb) || (baht(offer.discount_thb) ? `ลด ${baht(offer.discount_thb)}` : null);
              return (
                <li key={`${offer.campaign_id}:${offer.option_id}`}>
                  <span>
                    <b>{offer.option_label || offer.campaign_name}</b>
                    <small>{offer.conditions?.text || "โปรดตรวจสอบเงื่อนไขกับผู้จำหน่าย"}{offer.valid_to ? ` · ถึง ${formatThaiDate(offer.valid_to) || offer.valid_to}` : ""}</small>
                    {src ? <a href={src} target="_blank" rel="noreferrer">ที่มาราคาแคมเปญ ↗</a> : null}
                  </span>
                  {amount ? <b className="tdr-models-mono">{amount}</b> : null}
                </li>
              );
            })}
          </ul>
        ) : null}
        <p className="tdr-models-trim__links">
          <Link href={`/models/${slug}/${encodeURIComponent(trimLocalId(t.canonical_id || t.id))}`}>ดูสเปกทั้งหมดของรุ่นย่อยนี้ →</Link>
          {rangeSource ? <a href={rangeSource} target="_blank" rel="noreferrer">แหล่งข้อมูลระยะทาง ↗</a> : null}
        </p>
      </div>
    </details>
  );
}

export default async function ModelDetail({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const r: any = await getCanonicalModelBundle(slug);
  if (!r) notFound();

  // The three optional blocks fail open (their absence never blanks the page); the model itself throws to error.tsx.
  const [programs, related, teasers, historical] = await Promise.all([
    r.editorial_id ? getProductionProgramsByModel(r.editorial_id).catch(() => []) : [],
    getCanonicalRelatedModels(r, 6),
    getModelMarketTeasers(r.id).catch(() => null),
    getCanonicalHistoricalTrims(r.id).catch(() => []),
  ]);
  const ptById = new Map((r.powertrains_detail || []).map((p: any) => [p.id, p]));
  const specFields = loadSpecFieldRegistry(new Date().getFullYear());
  const currentTrims = (r.trims || []) as any[];

  const trimPrices = currentTrims.map((t) => Number(t.price_baht)).filter((n) => Number.isFinite(n) && n > 0);
  const heroPrice = trimPrices.length
    ? bahtRangeText(Math.min(...trimPrices), Math.max(...trimPrices))
    : bahtRangeText(r.retail_price_min, r.retail_price_max);
  const heroRange = modelRangeSummary(currentTrims);
  const brand = displayName(r.brands);
  const name = displayName(r);
  const picture = pictureCredit(r);
  const body = familyOfBody(r.body_type)?.label || bodyLabel(r.body_type);
  const chips = [
    r.segment && String(r.segment).toUpperCase() !== "UNKNOWN" ? `Segment ${r.segment}` : null,
    ...(r.powertrains || []).map((p: string) => POWERTRAIN_LABEL[p] || p),
    r.production_type && String(r.production_type).toUpperCase() !== "UNKNOWN" ? r.production_type : null,
    r.seats ? `${r.seats} ที่นั่ง` : null,
  ].filter(Boolean) as string[];

  const dimensions = [
    r.length_mm ? { k: "ความยาว", v: `${formatNumber(r.length_mm)} mm` } : null,
    r.width_mm ? { k: "ความกว้าง", v: `${formatNumber(r.width_mm)} mm` } : null,
    r.wheelbase_mm ? { k: "ฐานล้อ", v: `${formatNumber(r.wheelbase_mm)} mm` } : null,
    r.seats ? { k: "จำนวนที่นั่ง", v: `${r.seats} ที่นั่ง` } : null,
    r.payload_capacity_kg ? { k: "Payload", v: `${formatNumber(r.payload_capacity_kg)} kg` } : null,
    launch(r) ? { k: "เปิดตัวไทย", v: launch(r)! } : null,
    r.production_country ? { k: "ประเทศที่ผลิต", v: r.production_country } : null,
    r.production_type ? { k: "รูปแบบการนำเข้า/ประกอบ", v: r.production_type } : null,
  ].filter(Boolean) as { k: string; v: string }[];
  const powertrains = (r.powertrains_detail || []) as any[];
  const teaserCount = Array.isArray(teasers) ? teasers.length : 0;

  return <div className="tdr-wrap tdr-models-detail">
    <nav className="tdr-models-crumbs" aria-label="เส้นทาง">
      <ol>
        <li><Link href="/models">Vehicle Database</Link></li>
        {r.brands?.slug ? <li><Link href={`/brands/${r.brands.slug}`}>{brand}</Link></li> : brand ? <li>{brand}</li> : null}
        <li aria-current="page">{name}</li>
      </ol>
    </nav>

    <section className="tdr-models-hero" aria-labelledby="model-h1">
      <figure className="tdr-models-hero__img">
        {picture ? <img src={picture.src} alt={`${brand} ${name}`} /> : <span>{brand}<br /><b>{name}</b></span>}
        {picture ? <figcaption>ภาพ: <a href={picture.href} target="_blank" rel="noreferrer">{picture.host} ↗</a></figcaption> : null}
      </figure>
      <div className="tdr-models-hero__copy">
        <div className="tdr-eyebrow">{[brand, body].filter(Boolean).join(" · ") || "MODEL"}</div>
        <h1 id="model-h1" className="tdr-models-h1">{name}</h1>
        {chips.length ? <div className="tdr-chips">{chips.map((c) => <Chip key={c}>{c}</Chip>)}</div> : null}
        <dl className="tdr-models-keyblock">
          <div>
            <dt>ราคาปัจจุบัน</dt>
            <dd>{heroPrice ? <strong className="tdr-models-mono">{heroPrice}</strong> : <strong className="tdr-models-miss">ยังไม่ประกาศราคา</strong>}</dd>
            {trimPrices.length ? <small>คำนวณจากรุ่นย่อยที่จำหน่ายอยู่</small> : null}
          </div>
          {heroRange ? (
            <div>
              <dt>ระยะทางที่ผู้ผลิตประกาศ</dt>
              <dd><strong className="tdr-models-mono">{heroRange.range}</strong></dd>
              <small>{heroRange.cycle}</small>
            </div>
          ) : null}
        </dl>
        <div className="tdr-models-hero__cta">
          <CompareToggle variant="button" model={{ id: r.id, name, brand }} />
        </div>
      </div>
    </section>

    {r.consumer_description ? (
      <section className="tdr-models-blk" aria-label="ข้อมูลรุ่น">
        <p className="tdr-models-context">{r.consumer_description}</p>
      </section>
    ) : null}

    <section className="tdr-models-blk" aria-labelledby="model-trims">
      <div className="tdr-models-sechead">
        <div><div className="tdr-eyebrow">รุ่นย่อยและราคา</div><h2 id="model-trims">รุ่นย่อยที่จำหน่าย</h2></div>
        <span className="tdr-models-mono">{formatNumber(currentTrims.length)} Trim</span>
      </div>
      {currentTrims.length
        ? <div className="tdr-models-trims">{currentTrims.map((t) => <TrimRow key={t.id} t={t} ptById={ptById} specFields={specFields} slug={slug} />)}</div>
        : <BlockEmpty title="ยังไม่มีรุ่นย่อยในฐานข้อมูล" />}
      {historical.length ? (
        <details className="tdr-models-past">
          <summary>รุ่นย่อยที่เลิกจำหน่ายแล้ว ({formatNumber(historical.length)})</summary>
          <ul>
            {historical.map((t: any) => (
              <li key={t.id}><b>{t.name}</b>{t.powertrain ? <small>{POWERTRAIN_LABEL[t.powertrain] || t.powertrain}</small> : null}<span className="tdr-models-miss">เลิกจำหน่ายแล้ว</span></li>
            ))}
          </ul>
        </details>
      ) : null}
    </section>

    <section className="tdr-models-blk" aria-labelledby="model-tech">
      <div className="tdr-models-sechead"><div><div className="tdr-eyebrow">ข้อมูลทางเทคนิค</div><h2 id="model-tech">ข้อมูลทางเทคนิค</h2></div></div>
      <div className="tdr-models-twocol">
        <div>
          <h3>ขนาดและความจุ</h3>
          {dimensions.length
            ? <dl className="tdr-models-rows">{dimensions.map((d) => <div key={d.k}><dt>{d.k}</dt><dd className="tdr-models-mono">{d.v}</dd></div>)}</dl>
            : <BlockEmpty title="ยังไม่มีข้อมูลขนาดตัวถัง" />}
        </div>
        <div>
          <h3>ระบบขับเคลื่อน</h3>
          {powertrains.length ? powertrains.map((p) => (
            <details className="tdr-models-pt" key={p.id}>
              <summary><b>{p.label || ptSummary(p)}</b><span>{ptSummary(p)}</span></summary>
              <dl>
                {p.powertrain_type ? <div><dt>ประเภท</dt><dd>{p.powertrain_type}</dd></div> : null}
                {p.engine_code ? <div><dt>Engine code</dt><dd>{p.engine_code}</dd></div> : null}
                {p.motor_output_kw ? <div><dt>Motor output</dt><dd>{p.motor_output_kw} kW</dd></div> : null}
                {p.torque_nm ? <div><dt>แรงบิด</dt><dd>{p.torque_nm} Nm</dd></div> : null}
                {p.transmission ? <div><dt>Transmission</dt><dd>{p.transmission}</dd></div> : null}
                {p.drivetrain ? <div><dt>Drivetrain</dt><dd>{p.drivetrain}</dd></div> : null}
              </dl>
            </details>
          )) : <BlockEmpty title="ยังไม่มีรายละเอียดระบบขับเคลื่อน" />}
        </div>
      </div>
    </section>

    <section className="tdr-models-blk" aria-labelledby="model-market">
      <div className="tdr-models-sechead"><div><div className="tdr-eyebrow">ตลาด</div><h2 id="model-market">ยอดจดของรุ่นนี้</h2></div></div>
      {/* Blocker 11: the 12-month line and share come from the market engine that is being replaced, so nothing is read
          from it here. getModelMarketTeasers (a separate public teaser table) is kept for the one line below. Tier
          gating is decided client-side, so a single neutral card serves every viewer and holds no market values. */}
      <Card tone="dashed" className="tdr-models-state">
        <b className="tdr-card__title">อยู่ระหว่างปรับปรุงระบบวิเคราะห์ตลาด</b>
        <p className="tdr-models-muted">
          {teaserCount ? `มีข้อมูลตลาดสำหรับรุ่นนี้ · ครอบคลุม ${formatNumber(teaserCount)} ช่วงเวลาล่าสุด · ` : ""}
          <Link href="/market">เปิด Automotive Intelligence →</Link>
        </p>
      </Card>
    </section>

    {programs.length ? (
      <section className="tdr-models-blk" aria-labelledby="model-plant">
        <Card>
          <CardHead title={<span id="model-plant">การผลิตในไทย</span>} />
          <p className="tdr-models-muted">{programs.map((program: any) => [program.plants?.name_th || program.plants?.name_en, program.status].filter(Boolean).join(" · ")).join(" / ")}</p>
        </Card>
      </section>
    ) : null}

    {related.length ? (
      <section className="tdr-models-blk" aria-labelledby="model-related">
        <div className="tdr-models-sechead">
          <div><div className="tdr-eyebrow">แบรนด์เดียวกัน</div><h2 id="model-related">รถรุ่นอื่นจาก {brand || "แบรนด์เดียวกัน"}</h2></div>
          {r.brands?.slug ? <Link className="tdr-models-more" href={`/brands/${r.brands.slug}`}>ดูทั้งแบรนด์ →</Link> : null}
        </div>
        <div className="tdr-models-grid">
          {related.map((m: any) => <ModelCard key={m.id} r={m} />)}
        </div>
      </section>
    ) : null}
  </div>;
}
