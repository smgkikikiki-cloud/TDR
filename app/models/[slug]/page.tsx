import Link from "next/link";
import { notFound } from "next/navigation";
import { getConsumerModelBundle } from "@/lib/catalog-data";
import { getRelatedEvents, getProductionProgramsByModel, getRelatedModels, getModelRegistrationSummary } from "@/lib/data";
import { bodyLabel } from "@/lib/body-labels";

function launch(r: any) { return [r.launch_quarter, r.launch_year].filter(Boolean).join(" ") || null }
function baht(n: any) { return n ? `฿${Number(n).toLocaleString()}` : null }
/** A price range carries one ฿, not one per end. */
function bahtRange(values: number[]) {
  if (!values.length) return null;
  const min = Math.min(...values), max = Math.max(...values);
  return min === max ? `฿${min.toLocaleString()}` : `฿${min.toLocaleString()} – ${max.toLocaleString()}`;
}
function numberRange(values: number[], formatter: (n: number) => string) {
  if (!values.length) return null;
  const min = Math.min(...values), max = Math.max(...values);
  return min === max ? formatter(min) : `${formatter(min)} – ${formatter(max)}`;
}
function ptSummary(p: any) {
  const b: string[] = [];
  if (p.displacement_cc) b.push(`${Number(p.displacement_cc).toLocaleString()} cc`);
  if (p.battery_capacity_kwh) b.push(`${p.battery_capacity_kwh} kWh${p.battery_chemistry ? ` ${p.battery_chemistry}` : ""}`);
  if (p.powertrain_type) b.push(p.powertrain_type);
  if (p.horsepower_ps) b.push(`${p.horsepower_ps} PS`);
  return b.join(" · ") || p.label || "Powertrain";
}
function wheelLine(t: any) {
  const bits: string[] = [];
  if (t.tire_size_front) {
    bits.push(t.tire_size_rear && t.tire_size_rear !== t.tire_size_front ? `ยาง ${t.tire_size_front} / ${t.tire_size_rear}` : `ยาง ${t.tire_size_front}`);
  }
  if (t.wheel_size_front) {
    bits.push(t.wheel_size_rear && t.wheel_size_rear !== t.wheel_size_front ? `ล้อ ${t.wheel_size_front} / ${t.wheel_size_rear}` : `ล้อ ${t.wheel_size_front}`);
  }
  return bits.join(" · ");
}
function officialRangeLabel(trims: any[]) {
  const withRange = trims.filter((t) => Number(t.published_range_km) > 0);
  if (!withRange.length) return null;
  const values = withRange.map((t) => Number(t.published_range_km));
  const cycles = [...new Set(withRange.map((t) => t.published_range_cycle).filter(Boolean))];
  return {
    range: numberRange(values, (n) => `${Math.round(n).toLocaleString()} km`),
    cycle: cycles.length === 1 ? cycles[0] : "หลายมาตรฐาน",
  };
}

/** One trim row. Shared by the current and the discontinued list. */
function TrimRow({ t, ptById, muted }: { t: any; ptById: Map<any, any>; muted?: boolean }) {
  const linked = (t.trim_powertrains || []).map((x: any) => ptById.get(x.powertrain_id)).filter(Boolean);
  const wheel = wheelLine(t);
  const price = baht(t.price_baht);
  return (
    <details className={muted ? "sfTrimRow sfDiscontinued" : "sfTrimRow"}>
      <summary>
        <div>
          <h3>{t.name}</h3>
          <span>{linked.map((p: any) => ptSummary(p)).join(" / ") || (muted ? "เลิกจำหน่ายแล้ว" : "")}</span>
        </div>
        <div className="sfTrimNums">
          {t.published_range_km ? <span>{Number(t.published_range_km).toLocaleString()} km {t.published_range_cycle || ""}</span> : null}
          {price ? <strong>{price}</strong> : <span className="sfMissing">ไม่ระบุราคา</span>}
        </div>
      </summary>
      <div className="sfTrimBody">
        <div className="sfSpecGrid">
          {linked.map((p: any) => <div key={p.id}><small>Powertrain</small><b>{ptSummary(p)}</b></div>)}
          {t.published_range_km ? <div><small>Range ที่ผู้ผลิตประกาศ</small><b>{Number(t.published_range_km).toLocaleString()} km {t.published_range_cycle || ""}</b></div> : null}
          {t.standardized_wltp_km ? <div><small>TDR standardized</small><b>~{Number(t.standardized_wltp_km).toLocaleString()} km WLTP-equivalent</b></div> : null}
          {t.standardized_epa_km ? <div><small>EPA / equivalent</small><b>~{Number(t.standardized_epa_km).toLocaleString()} km</b></div> : null}
          {wheel ? <div><small>ยาง / ล้อ</small><b>{wheel}</b></div> : null}
          {(t.seats_override || t.payload_capacity_kg_override) ? <div><small>ความจุ</small><b>{[t.seats_override ? `${t.seats_override} ที่นั่ง` : null, t.payload_capacity_kg_override ? `Payload ${t.payload_capacity_kg_override} kg` : null].filter(Boolean).join(" · ")}</b></div> : null}
        </div>
        {t.description ? <p>{t.description}</p> : <p className="sfMissing">ยังไม่มีรายละเอียดอุปกรณ์ของ Trim นี้</p>}
        {t.range_source_url ? <a className="sfSourceLink" href={t.range_source_url} target="_blank" rel="noreferrer">แหล่งข้อมูล Range ↗</a> : null}
      </div>
    </details>
  );
}

export default async function ModelDetail({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const r: any = await getConsumerModelBundle(slug);
  if (!r) notFound();

  const [events, programs, related, regs] = await Promise.all([
    getRelatedEvents({ modelId: r.id }, 8),
    getProductionProgramsByModel(r.id),
    getRelatedModels(r, 6),
    getModelRegistrationSummary(r.id)
  ]);
  const latestReg = regs[0];
  const ptById = new Map((r.powertrains_detail || []).map((p: any) => [p.id, p]));
  const allTrims = (r.trims || []) as any[];
  const currentTrims = allTrims.filter((t) => String(t.status || "current").toLowerCase() !== "discontinued");
  const pastTrims = allTrims.filter((t) => String(t.status || "current").toLowerCase() === "discontinued");

  const trimPrices = currentTrims.map((t: any) => Number(t.price_baht)).filter((n: number) => Number.isFinite(n) && n > 0);
  const heroPrice = bahtRange(trimPrices) || (r.retail_price_min || r.retail_price_max
    ? bahtRange([r.retail_price_min, r.retail_price_max].filter((n: any) => Number(n) > 0).map(Number))
    : null);
  const heroRange = officialRangeLabel(currentTrims);
  const brand = r.brands?.name_th || "";

  const dimensions = [
    r.length_mm ? { k: "ความยาว", v: `${Number(r.length_mm).toLocaleString()} mm` } : null,
    r.width_mm ? { k: "ความกว้าง", v: `${Number(r.width_mm).toLocaleString()} mm` } : null,
    r.wheelbase_mm ? { k: "ฐานล้อ", v: `${Number(r.wheelbase_mm).toLocaleString()} mm` } : null,
    r.seats ? { k: "จำนวนที่นั่ง", v: `${r.seats} ที่นั่ง` } : null,
    r.payload_capacity_kg ? { k: "Payload", v: `${Number(r.payload_capacity_kg).toLocaleString()} kg` } : null,
  ].filter(Boolean) as { k: string; v: string }[];

  const regRows = [...regs].reverse();
  const regMax = Math.max(1, ...regRows.map((x: any) => Number(x.registrations) || 0));

  return <>
    {/* ---------- Zone A · สำหรับผู้ซื้อ ---------- */}
    <section className="sfHero">
      <div className="sfHeroSlot">
        {r.image_url ? <img src={r.image_url} alt={r.name_th} /> : <><small>{(brand || "TDR").toUpperCase()}</small><b>{r.name_th}</b></>}
      </div>
      <div className="sfHeroCopy">
        <div className="sfEyebrow">{[brand, bodyLabel(r.body_type)].filter(Boolean).join(" · ") || "MODEL"}</div>
        <h1>{r.name_th}</h1>
        {r.generation ? <p className="sfGeneration">{r.generation}</p> : null}
        <div className="sfBadges">
          {[r.segment, r.market_position, ...(r.powertrains || []), r.production_type, r.production_country, r.seats ? `${r.seats} ที่นั่ง` : null].filter(Boolean).map((x: string) => <span key={x}>{x}</span>)}
        </div>
        <div className="sfKeyBlock">
          <div>
            <small>ราคาปัจจุบัน</small>
            {heroPrice ? <strong>{heroPrice}</strong> : <strong className="sfMissing">ยังไม่ประกาศราคา</strong>}
            <em>{trimPrices.length ? "คำนวณจาก Trim ที่จำหน่ายอยู่" : "ยังไม่มีราคา Trim ในฐานข้อมูล"}</em>
          </div>
          <div className={heroRange ? "mark" : undefined}>
            <small>ระยะทางที่ผู้ผลิตประกาศ</small>
            {heroRange ? <strong>{heroRange.range}</strong> : <strong className="sfMissing">ยังไม่มีข้อมูล</strong>}
            <em>{heroRange ? heroRange.cycle : "ผู้ผลิตยังไม่ประกาศ หรือยังไม่ได้บันทึก"}</em>
          </div>
        </div>
      </div>
    </section>

    {r.consumer_description ? (
      <section className="sfBlock">
        <div className="sfEyebrow ink">TDR MODEL CONTEXT</div>
        <p className="sfContext" style={{ marginTop: 12 }}>{r.consumer_description}</p>
      </section>
    ) : null}

    <section className="sfBlock">
      <div className="sfZoneHead">
        <div><div className="sfEyebrow">TRIMS &amp; PRICE</div><h2>รุ่นย่อยที่จำหน่าย</h2></div>
        <span>{currentTrims.length} Trim</span>
      </div>
      {currentTrims.length
        ? <div>{currentTrims.map((t: any) => <TrimRow key={t.id} t={t} ptById={ptById} />)}</div>
        : <div className="sfEmpty"><b>ยังไม่ได้กรอกรุ่นย่อย</b><span>ข้อมูล Trim ของรุ่นนี้ยังไม่อยู่ในฐานข้อมูล</span></div>}
      {pastTrims.length ? (
        <details style={{ marginTop: 18 }}>
          <summary className="sfEyebrow ink" style={{ cursor: "pointer", padding: "10px 0" }}>รุ่นย่อยที่เลิกจำหน่ายแล้ว ({pastTrims.length})</summary>
          <div>{pastTrims.map((t: any) => <TrimRow key={t.id} t={t} ptById={ptById} muted />)}</div>
        </details>
      ) : null}
    </section>

    {/* ---------- Zone B · ข้อมูลทางเทคนิค ---------- */}
    <section className="sfTechZone sfBleed">
      <div className="sfZoneHead">
        <div><div className="sfEyebrow ink">TECHNICAL</div><h2>ข้อมูลทางเทคนิค</h2></div>
      </div>
      <div className="sfIndGrid">
        <div>
          <h3 style={{ margin: "0 0 4px", fontSize: 16, fontWeight: 800 }}>ขนาดและความจุ</h3>
          <div className="sfRows">
            {dimensions.length
              ? dimensions.map((d) => <div className="sfRow" key={d.k}><span>{d.k}</span><b>{d.v}</b></div>)
              : <div className="sfRow"><span>ขนาดตัวถัง</span><b className="sfMissing">ยังไม่มีข้อมูล</b></div>}
            <div className="sfRow"><span>เปิดตัวไทย</span>{launch(r) ? <b>{launch(r)}</b> : <b className="sfMissing">ไม่ระบุ</b>}</div>
            <div className="sfRow"><span>ประเทศที่ผลิต</span>{r.production_country ? <b>{r.production_country}</b> : <b className="sfMissing">ไม่ระบุ</b>}</div>
            <div className="sfRow"><span>รูปแบบการนำเข้า/ประกอบ</span>{r.production_type ? <b>{r.production_type}</b> : <b className="sfMissing">ไม่ระบุ</b>}</div>
          </div>
        </div>
        <div>
          <h3 style={{ margin: "0 0 12px", fontSize: 16, fontWeight: 800 }}>ระบบขับเคลื่อน</h3>
          {(r.powertrains_detail || []).length
            ? (r.powertrains_detail as any[]).map((p: any) => (
              <details className="sfPtCard" key={p.id}>
                <summary><b>{p.label || ptSummary(p)}</b><span>{ptSummary(p)}</span></summary>
                <dl>
                  <div><dt>ประเภท</dt><dd>{p.powertrain_type || "—"}</dd></div>
                  {p.engine_code ? <div><dt>Engine code</dt><dd>{p.engine_code}</dd></div> : null}
                  {p.motor_output_kw ? <div><dt>Motor output</dt><dd>{p.motor_output_kw} kW</dd></div> : null}
                  {p.torque_nm ? <div><dt>แรงบิด</dt><dd>{p.torque_nm} Nm</dd></div> : null}
                  {p.transmission ? <div><dt>Transmission</dt><dd>{p.transmission}</dd></div> : null}
                  {p.drivetrain ? <div><dt>Drivetrain</dt><dd>{p.drivetrain}</dd></div> : null}
                </dl>
              </details>
            ))
            : <div className="sfEmpty"><b>ยังไม่มีรายละเอียดระบบขับเคลื่อน</b><span>ยังไม่ได้บันทึกสเปกเครื่องยนต์หรือมอเตอร์ของรุ่นนี้</span></div>}
        </div>
      </div>
    </section>

    {/* ---------- Zone C · อุตสาหกรรม ---------- */}
    <section className="sfIndZone sfBleed">
      <div className="sfZoneHead">
        <div><div className="sfEyebrow">INDUSTRY LAYER</div><h2 style={{ color: "#fff" }}>รุ่นนี้ในฐานะสินค้าอุตสาหกรรม</h2></div>
      </div>
      <div className="sfIndGrid">
        <p>
          ยอดจดทะเบียนคือจำนวนคันที่จดทะเบียนใหม่ตามที่บันทึกไว้ในฐานข้อมูล TDR ไม่ใช่ยอดขายของผู้จำหน่าย
          และไม่ได้ปรับด้วยค่าประมาณใด ๆ
        </p>
        <div>
          {regRows.length ? <>
            <div className="sfBars">
              {regRows.map((x: any) => (
                <div className="sfBarRow" key={x.period}>
                  <span>{x.period}</span>
                  <span className="sfBarTrack"><span className="sfBarFill" style={{ width: `${Math.max(2, Math.round((Number(x.registrations) || 0) / regMax * 100))}%` }} /></span>
                  <em>{Number(x.registrations || 0).toLocaleString()}</em>
                </div>
              ))}
            </div>
            <div className="sfSrcNote">ล่าสุด {latestReg?.period} · {Number(latestReg?.registrations || 0).toLocaleString()} คัน · ที่มา: ตารางยอดจดทะเบียนของ TDR</div>
          </> : (
            <div>
              <p className="sfMissing" style={{ fontSize: 15 }}>ยังไม่มีข้อมูลยอดจดทะเบียนของรุ่นนี้ในฐานข้อมูล</p>
              <div className="sfSrcNote">เมื่อมีการนำเข้าข้อมูลจดทะเบียน กราฟรายเดือนจะขึ้นตรงนี้</div>
            </div>
          )}
        </div>
      </div>
      {programs.length ? (
        <Link href={`/production/${r.slug}`} className="sfBridge">
          <div>
            <div className="sfEyebrow">THAILAND PRODUCTION</div>
            <h3>รุ่นนี้มีข้อมูลการผลิตในประเทศไทย</h3>
            <p>ดูโรงงาน Platform ปริมาณผลิต Local Content และ MiT ของรถรุ่นนี้</p>
          </div>
          <span>ดูข้อมูลการผลิต →</span>
        </Link>
      ) : null}
    </section>

    <section className="sfBlock">
      <div className="sfZoneHead">
        <div><div className="sfEyebrow ink">LATEST</div><h2>ข่าวและอัปเดต</h2></div>
        <Link href="/news">ข่าวทั้งหมด →</Link>
      </div>
      {events.length
        ? <div className="sfNewsList">{events.map((e: any) => <article key={e.id}><time>{e.event_date}</time><div><b>{e.title_th}</b>{e.summary_th || e.source_name ? <p>{e.summary_th || e.source_name}</p> : null}</div></article>)}</div>
        : <div className="sfEmpty"><b>ยังไม่มีข่าวที่เชื่อมกับรุ่นนี้</b><span>ข่าวที่ระบุรุ่นนี้ไว้จะแสดงที่นี่</span></div>}
    </section>

    {related.length ? (
      <section className="sfBlock">
        <div className="sfZoneHead">
          <div><div className="sfEyebrow ink">SAME BRAND</div><h2>รถรุ่นอื่นจาก {brand || "แบรนด์เดียวกัน"}</h2></div>
          {r.brands?.slug ? <Link href={`/brands/${r.brands.slug}`}>ดูทั้งแบรนด์ →</Link> : null}
        </div>
        <div className="sfGrid">
          {related.map((m: any) => {
            const meta = [bodyLabel(m.body_type), (m.powertrains || []).join(" / ")].filter(Boolean).join(" · ");
            const price = bahtRange([m.retail_price_min, m.retail_price_max].filter((n: any) => Number(n) > 0).map(Number));
            return (
              <Link className="sfCard" href={`/models/${m.slug}`} key={m.id}>
                <div className="sfSlot">{m.image_url ? <img src={m.image_url} alt="" /> : <><small>{(brand || "TDR").toUpperCase()}</small><b>{m.name_th}</b></>}</div>
                <div className="sfCardBody">
                  <h3>{m.name_th}</h3>
                  {meta ? <p className="sfCardMeta">{meta}</p> : null}
                  <div className="sfCardFoot">{price ? <span className="sfPrice">{price}</span> : <span className="sfMissing">ยังไม่ประกาศราคา</span>}</div>
                </div>
              </Link>
            );
          })}
        </div>
      </section>
    ) : null}
  </>;
}
