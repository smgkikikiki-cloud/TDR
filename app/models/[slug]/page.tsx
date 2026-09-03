import Link from "next/link";
import { notFound } from "next/navigation";
import { getConsumerModelBundle } from "@/lib/catalog-data";
import { getRelatedEvents,getProductionProgramsByModel,getRelatedModels,getModelRegistrationSummary } from "@/lib/data";

function launch(r:any){return[r.launch_quarter,r.launch_year].filter(Boolean).join(" ")||"—"}
function baht(n:any){return n?`฿${Number(n).toLocaleString()}`:"—"}
function numberRange(values:number[], formatter:(n:number)=>string){
  if(!values.length) return null;
  const min=Math.min(...values),max=Math.max(...values);
  return min===max?formatter(min):`${formatter(min)} – ${formatter(max)}`;
}
function ptSummary(p:any){
  const b:string[]=[];
  if(p.displacement_cc)b.push(`${Number(p.displacement_cc).toLocaleString()} cc`);
  if(p.battery_capacity_kwh)b.push(`${p.battery_capacity_kwh} kWh${p.battery_chemistry?` ${p.battery_chemistry}`:""}`);
  if(p.powertrain_type)b.push(p.powertrain_type);
  if(p.horsepower_ps)b.push(`${p.horsepower_ps} PS`);
  return b.join(" · ")||p.label||"Powertrain";
}
function wheelLine(t:any){
  const bits:string[]=[];
  if(t.tire_size_front){
    bits.push(t.tire_size_rear&&t.tire_size_rear!==t.tire_size_front?`ยาง ${t.tire_size_front} / ${t.tire_size_rear}`:`ยาง ${t.tire_size_front}`);
  }
  if(t.wheel_size_front){
    bits.push(t.wheel_size_rear&&t.wheel_size_rear!==t.wheel_size_front?`ล้อ ${t.wheel_size_front} / ${t.wheel_size_rear}`:`ล้อ ${t.wheel_size_front}`);
  }
  return bits.join(" · ");
}
function officialRangeLabel(trims:any[]){
  const withRange=trims.filter(t=>Number(t.published_range_km)>0);
  if(!withRange.length) return null;
  const values=withRange.map(t=>Number(t.published_range_km));
  const cycles=[...new Set(withRange.map(t=>t.published_range_cycle).filter(Boolean))];
  return {
    range:numberRange(values,n=>`${Math.round(n).toLocaleString()} km`),
    cycle:cycles.length===1?cycles[0]:"หลายมาตรฐาน",
  };
}

export default async function ModelDetail({params}:{params:Promise<{slug:string}>}){
  const{slug}=await params;
  const r:any=await getConsumerModelBundle(slug);
  if(!r)notFound();

  const[events,programs,related,regs]=await Promise.all([
    getRelatedEvents({modelId:r.id},8),
    getProductionProgramsByModel(r.id),
    getRelatedModels(r,6),
    getModelRegistrationSummary(r.id)
  ]);
  const latestReg=regs[0];
  const ptById=new Map((r.powertrains_detail||[]).map((p:any)=>[p.id,p]));
  const currentTrims=(r.trims||[]).filter((t:any)=>String(t.status||"current").toLowerCase()!=="discontinued");

  const trimPrices=currentTrims.map((t:any)=>Number(t.price_baht)).filter((n:number)=>Number.isFinite(n)&&n>0);
  const heroPrice=numberRange(trimPrices,n=>baht(n)) || (r.retail_price_min||r.retail_price_max
    ? (r.retail_price_min!==r.retail_price_max?`${baht(r.retail_price_min)} – ${baht(r.retail_price_max)}`:baht(r.retail_price_min||r.retail_price_max))
    : null);
  const heroRange=officialRangeLabel(currentTrims);
  const hasDimensions=r.length_mm||r.width_mm||r.wheelbase_mm;

  return <main className="consumerModelPage">
    <section className="consumerHero">
      <div className="consumerImage">{r.image_url?<img src={r.image_url} alt={r.name_th}/>:<div className="consumerImagePlaceholder"><span>{r.brands?.name_th||"TDR"}</span><b>{r.name_th}</b></div>}</div>
      <div className="consumerHeroCopy">
        <small>{r.brands?.name_th||"MODEL"}</small>
        <h1>{r.name_th}</h1>
        <p className="generationLine">{r.generation||""}</p>
        <div className="consumerBadges">{[r.segment,r.body_type,r.market_position,...(r.powertrains||[]),r.production_type,r.production_country,r.seats?`${r.seats} ที่นั่ง`:null].filter(Boolean).map((x:string)=><span key={x}>{x}</span>)}</div>
        <div className="consumerHeroMetrics">
          <div className="consumerPrice"><small>ราคาปัจจุบัน</small><strong>{heroPrice||"ดูรุ่นย่อยด้านล่าง"}</strong><em>คำนวณจาก Trim ที่จำหน่ายอยู่</em></div>
          {heroRange?<div className="consumerRangeHero"><small>ระยะทางที่ผู้ผลิตประกาศ</small><strong>{heroRange.range}</strong><em>{heroRange.cycle}</em></div>:null}
        </div>
      </div>
    </section>

    {r.consumer_description?<section className="consumerContext"><small>TDR MODEL CONTEXT</small><p>{r.consumer_description}</p></section>:null}

    <section className="consumerFacts">
      <div><small>เปิดตัวไทย</small><b>{launch(r)}</b></div>
      <div><small>แหล่งผลิต</small><b>{r.production_country||"—"}</b></div>
      <div><small>รูปแบบ</small><b>{r.production_type||"—"}</b></div>
      <div><small>ยอดจดทะเบียนล่าสุด</small><b>{latestReg?latestReg.registrations.toLocaleString():"—"}</b>{latestReg?<em>{latestReg.period}</em>:null}</div>
      {r.payload_capacity_kg?<div><small>Payload</small><b>{Number(r.payload_capacity_kg).toLocaleString()} kg</b></div>:null}
    </section>

    {hasDimensions?<section className="consumerSection dimensionSection">
      <div className="consumerSectionHead"><div><small>DIMENSIONS</small><h2>ขนาดตัวถัง</h2></div></div>
      <div className="dimensionGrid">
        {r.length_mm?<div><small>ความยาว</small><b>{Number(r.length_mm).toLocaleString()} mm</b></div>:null}
        {r.width_mm?<div><small>ความกว้าง</small><b>{Number(r.width_mm).toLocaleString()} mm</b></div>:null}
        {r.wheelbase_mm?<div><small>ฐานล้อ</small><b>{Number(r.wheelbase_mm).toLocaleString()} mm</b></div>:null}
      </div>
    </section>:null}

    <section className="consumerSection trimSection">
      <div className="consumerSectionHead"><div><small>TRIMS & PRICE</small><h2>รุ่นย่อยที่จำหน่าย</h2></div><span>{currentTrims.length} Trim</span></div>
      {currentTrims.length?<div className="trimPublicList">{currentTrims.map((t:any)=>{
        const linked=(t.trim_powertrains||[]).map((x:any)=>ptById.get(x.powertrain_id)).filter(Boolean);
        const wheel=wheelLine(t);
        return <details key={t.id} className="trimPublicCard">
          <summary>
            <div><b>{t.name}</b><span>{linked.map((p:any)=>ptSummary(p)).join(" / ")||""}</span></div>
            <div className="trimSummaryNumbers">
              {t.published_range_km?<span>{Number(t.published_range_km).toLocaleString()} km {t.published_range_cycle||""}</span>:null}
              <strong>{baht(t.price_baht)}</strong>
            </div>
          </summary>
          <div className="trimPublicBody">
            <div className="trimSpecGrid">
              {linked.map((p:any)=><div key={p.id}><small>Powertrain</small><b>{ptSummary(p)}</b></div>)}
              {t.published_range_km?<div><small>Range ที่ผู้ผลิตประกาศ</small><b>{Number(t.published_range_km).toLocaleString()} km {t.published_range_cycle||""}</b></div>:null}
              {t.standardized_wltp_km?<div><small>TDR standardized</small><b>~{Number(t.standardized_wltp_km).toLocaleString()} km WLTP-equivalent</b></div>:null}
              {t.standardized_epa_km?<div><small>EPA / equivalent</small><b>~{Number(t.standardized_epa_km).toLocaleString()} km</b></div>:null}
              {wheel?<div><small>ยาง / ล้อ</small><b>{wheel}</b></div>:null}
              {(t.seats_override||t.payload_capacity_kg_override)?<div><small>ความจุ</small><b>{[t.seats_override?`${t.seats_override} ที่นั่ง`:null,t.payload_capacity_kg_override?`Payload ${t.payload_capacity_kg_override} kg`:null].filter(Boolean).join(" · ")}</b></div>:null}
            </div>
            {t.description?<p>{t.description}</p>:<p className="mutedPublic">ยังไม่มีรายละเอียดอุปกรณ์ของ Trim นี้</p>}
            {t.range_source_url?<a className="trimSourceLink" href={t.range_source_url} target="_blank" rel="noreferrer">แหล่งข้อมูล Range ↗</a>:null}
          </div>
        </details>
      })}</div>:<p className="publicEmpty">ยังไม่ได้กรอก Trim</p>}
    </section>

    {(r.powertrains_detail||[]).length?<section className="consumerSection">
      <div className="consumerSectionHead"><div><small>POWERTRAIN DETAILS</small><h2>รายละเอียดระบบขับเคลื่อน</h2></div></div>
      <div className="consumerPowertrainList">{r.powertrains_detail.map((p:any)=><details key={p.id}><summary><b>{p.label||ptSummary(p)}</b><span>{ptSummary(p)}</span></summary><dl><dt>ประเภท</dt><dd>{p.powertrain_type||"—"}</dd>{p.engine_code?<><dt>Engine code</dt><dd>{p.engine_code}</dd></>:null}{p.motor_output_kw?<><dt>Motor output</dt><dd>{p.motor_output_kw} kW</dd></>:null}{p.torque_nm?<><dt>แรงบิด</dt><dd>{p.torque_nm} Nm</dd></>:null}{p.transmission?<><dt>Transmission</dt><dd>{p.transmission}</dd></>:null}{p.drivetrain?<><dt>Drivetrain</dt><dd>{p.drivetrain}</dd></>:null}</dl></details>)}</div>
    </section>:null}

    {programs.length?<Link href={`/production/${r.slug}`} className="productionBridge"><div><small>THAILAND PRODUCTION</small><h2>รุ่นนี้มีข้อมูลการผลิตในประเทศไทย</h2><p>ดูโรงงาน Platform ปริมาณผลิต Local Content MiT และบริบทของรถรุ่นนี้ในฐานะผลิตภัณฑ์อุตสาหกรรม</p></div><span>ดูข้อมูลการผลิต →</span></Link>:null}

    <section className="consumerSection">
      <div className="consumerSectionHead"><h2>ข่าวและอัปเดต</h2><Link href="/news">ข่าวทั้งหมด →</Link></div>
      {events.length?<div className="consumerNewsList">{events.map((e:any)=><article key={e.id}><time>{e.event_date}</time><div><b>{e.title_th}</b><p>{e.summary_th||e.source_name||""}</p></div></article>)}</div>:<p className="publicEmpty">ยังไม่มีข่าวที่เชื่อมกับรุ่นนี้</p>}
    </section>

    {related.length?<section className="consumerSection">
      <div className="consumerSectionHead"><h2>รถรุ่นอื่นจาก {r.brands?.name_th||"แบรนด์เดียวกัน"}</h2></div>
      <div className="relatedCarStrip">{related.map((m:any)=><Link href={`/models/${m.slug}`} key={m.id}><div className="relatedCarVisual">{m.image_url?<img src={m.image_url} alt=""/>:<span>{m.name_th}</span>}</div><b>{m.name_th}</b><small>{[m.body_type,(m.powertrains||[]).join("/")].filter(Boolean).join(" · ")}</small></Link>)}</div>
    </section>:null}
  </main>;
}
