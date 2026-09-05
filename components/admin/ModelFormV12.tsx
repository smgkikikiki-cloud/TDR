"use client";

import { useMemo, useState, type ReactNode } from "react";
import { saveModelV12 } from "@/app/admin/catalog-actions";
import { legacyOption } from "@/components/admin/Fields";

const segments = ["A","B","C","D","E"];
const bodies = ["Sedan","Hatchback","Coupe","Crossover","SUV (Monocoque)","SUV (Ladder frame)","MPV","Pickup truck","Van"];
const positions = ["Mass","Premium","Luxury"];
const productionTypes = ["CBU","CKD","SKD"];
const countries = ["Thailand","Indonesia","Malaysia","Japan","China","South Korea","Germany","United Kingdom","United States","Mexico","India","Vietnam","Philippines","Austria","Hungary","Czech Republic","Slovakia","Spain","Sweden","South Africa","Italy","France","Turkey","Belgium","Netherlands","Poland","Romania","Serbia","Brazil","Argentina","Canada","Portugal"];
const ptTypes = ["ICE","HEV","PHEV","REEV","BEV"];
const qtrs = ["Q1","Q2","Q3","Q4"];
const rangeCycles = ["WLTP","EPA","NEDC","CLTC","Manufacturer","Other"];

type Row = Record<string, any>;
type PT = {
  id?: string;
  clientKey: string;
  label: string;
  powertrainType: string;
  engineCode: string;
  displacementCc: string;
  batteryCapacityKwh: string;
  batteryChemistry: string;
  motorOutputKw: string;
  horsepowerPs: string;
  torqueNm: string;
  transmission: string;
  drivetrain: string;
  notes: string;
  unconfirmedFields: string[];
};
type Trim = {
  id?: string;
  clientKey: string;
  name: string;
  priceBaht: string;
  status: string;
  description: string;
  seatsOverride: string;
  payloadCapacityKgOverride: string;
  powertrainKeys: string[];
  tireSizeFront: string;
  tireSizeRear: string;
  wheelSizeFront: string;
  wheelSizeRear: string;
  publishedRangeKm: string;
  publishedRangeCycle: string;
  standardizedWltpKm: string;
  standardizedEpaKm: string;
  rangeSourceUrl: string;
  sortOrder: number;
  unconfirmedFields: string[];
};

const makeKey = (prefix:string) => `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2,8)}`;
const str = (v:any) => v === null || v === undefined ? "" : String(v);
const toNum = (v:string) => v.trim() === "" ? null : Number(v);

function initialPT(r:Row):PT {
  return {
    id:r.id,
    clientKey:r.id||makeKey("pt"),
    label:r.label||"",
    powertrainType:r.powertrain_type||"",
    engineCode:r.engine_code||"",
    displacementCc:str(r.displacement_cc),
    batteryCapacityKwh:str(r.battery_capacity_kwh),
    batteryChemistry:r.battery_chemistry||"",
    motorOutputKw:str(r.motor_output_kw),
    horsepowerPs:str(r.horsepower_ps??r.system_output_ps),
    torqueNm:str(r.torque_nm),
    transmission:r.transmission||"",
    drivetrain:r.drivetrain||"",
    notes:r.notes||"",
    unconfirmedFields:r.unconfirmed_fields||[]
  };
}

function initialTrim(r:Row):Trim {
  return {
    id:r.id,
    clientKey:r.id||makeKey("trim"),
    name:r.name||"",
    priceBaht:str(r.price_baht),
    status:r.status||"current",
    description:r.description||"",
    seatsOverride:str(r.seats_override),
    payloadCapacityKgOverride:str(r.payload_capacity_kg_override),
    powertrainKeys:(r.trim_powertrains||[]).map((x:any)=>x.powertrain_id),
    tireSizeFront:r.tire_size_front||"",
    tireSizeRear:r.tire_size_rear||"",
    wheelSizeFront:r.wheel_size_front||"",
    wheelSizeRear:r.wheel_size_rear||"",
    publishedRangeKm:str(r.published_range_km),
    publishedRangeCycle:r.published_range_cycle||"",
    standardizedWltpKm:str(r.standardized_wltp_km),
    standardizedEpaKm:str(r.standardized_epa_km),
    rangeSourceUrl:r.range_source_url||"",
    sortOrder:r.sort_order||0,
    unconfirmedFields:r.unconfirmed_fields||[]
  };
}

function Input({label,name,defaultValue,type="text",placeholder,required=false}:{label:string;name:string;defaultValue?:any;type?:string;placeholder?:string;required?:boolean}) {
  return <label className="adminField"><span>{label}</span><input name={name} type={type} defaultValue={defaultValue??""} placeholder={placeholder} required={required}/></label>;
}
function Select({label,name,defaultValue,children}:{label:string;name:string;defaultValue?:any;children:ReactNode}) {
  return <label className="adminField"><span>{label}</span><select name={name} defaultValue={defaultValue??""}>{legacyOption(defaultValue, children)}{children}</select></label>;
}
function Confidence({field,current}:{field:string;current:Set<string>}) {
  return <label className="adminUnconfirmed compact"><input type="checkbox" name="unconfirmed_fields" value={field} defaultChecked={current.has(field)}/><span>Unconfirmed</span></label>;
}
function Structured({field,current,children}:{field:string;current:Set<string>;children:ReactNode}) {
  return <div className="adminConfidenceField">{children}<Confidence field={field} current={current}/></div>;
}
function EmptyOption(){ return <option value="">— ว่าง —</option>; }

function PTEditor({pt,onChange,onRemove}:{pt:PT;onChange:(next:PT)=>void;onRemove:()=>void}) {
  const set=(field:keyof PT,value:any)=>onChange({...pt,[field]:value});
  const toggleUn=(field:string)=>set("unconfirmedFields",pt.unconfirmedFields.includes(field)?pt.unconfirmedFields.filter(x=>x!==field):[...pt.unconfirmedFields,field]);
  const combustion=["ICE","HEV","PHEV","REEV"].includes(pt.powertrainType);
  const battery=["PHEV","REEV","BEV"].includes(pt.powertrainType);
  const motor=["HEV","PHEV","REEV","BEV"].includes(pt.powertrainType);
  const fields=["powertrain_type",...(combustion?["displacement_cc","engine_code"]:[]),...(battery?["battery"]:[]),...(motor?["motor_output_kw"]:[]),"horsepower_ps","torque_nm"];
  return <article className="dynamicAdminCard">
    <div className="dynamicCardHead"><div><small>POWERTRAIN</small><b>{pt.label || (pt.powertrainType ? `${pt.powertrainType} configuration` : "Powertrain ใหม่")}</b></div><button type="button" className="adminDangerText" onClick={onRemove}>ลบ</button></div>
    <div className="adminEmbeddedGrid">
      <label className="adminField"><span>ประเภท</span><select value={pt.powertrainType} onChange={e=>set("powertrainType",e.target.value)}><option value="">— เลือก —</option>{ptTypes.map(x=><option key={x}>{x}</option>)}</select></label>
      <label className="adminField"><span>ชื่อย่อในหลังบ้าน</span><input value={pt.label} onChange={e=>set("label",e.target.value)} placeholder={pt.powertrainType==="BEV"?"เช่น 82.5 kWh BEV":"เช่น 1.8 HEV"}/></label>
      {combustion?<><label className="adminField"><span>ความจุเครื่องยนต์ (cc)</span><input type="number" value={pt.displacementCc} onChange={e=>set("displacementCc",e.target.value)}/></label><label className="adminField"><span>Engine code</span><input value={pt.engineCode} onChange={e=>set("engineCode",e.target.value)} placeholder="เช่น 2ZR-FXE"/></label></>:null}
      {battery?<><label className="adminField"><span>Battery capacity (kWh)</span><input type="number" step="0.1" value={pt.batteryCapacityKwh} onChange={e=>set("batteryCapacityKwh",e.target.value)}/></label><label className="adminField"><span>Battery chemistry</span><input value={pt.batteryChemistry} onChange={e=>set("batteryChemistry",e.target.value)} placeholder="LFP / NMC"/></label></>:null}
      {motor?<label className="adminField"><span>Motor output (kW)</span><input type="number" step="0.1" value={pt.motorOutputKw} onChange={e=>set("motorOutputKw",e.target.value)}/></label>:null}
      <label className="adminField"><span>กำลัง (PS / hp)</span><input type="number" step="0.1" value={pt.horsepowerPs} onChange={e=>set("horsepowerPs",e.target.value)}/></label>
      <label className="adminField"><span>แรงบิด (Nm)</span><input type="number" step="0.1" value={pt.torqueNm} onChange={e=>set("torqueNm",e.target.value)}/></label>
      <label className="adminField"><span>Transmission (optional)</span><input value={pt.transmission} onChange={e=>set("transmission",e.target.value)}/></label>
      <label className="adminField"><span>Drivetrain (optional)</span><input value={pt.drivetrain} onChange={e=>set("drivetrain",e.target.value)}/></label>
      <label className="adminField adminFieldWide"><span>หมายเหตุ</span><textarea rows={3} value={pt.notes} onChange={e=>set("notes",e.target.value)}/></label>
    </div>
    <div className="uncertainStrip"><span>Unconfirmed:</span>{fields.map(f=><label key={f}><input type="checkbox" checked={pt.unconfirmedFields.includes(f)} onChange={()=>toggleUn(f)}/>{f}</label>)}</div>
  </article>;
}

function ptSummary(pt:PT){
  const bits:string[]=[];
  if(pt.displacementCc) bits.push(`${Number(pt.displacementCc).toLocaleString()} cc`);
  if(pt.batteryCapacityKwh) bits.push(`${pt.batteryCapacityKwh} kWh`);
  bits.push(pt.powertrainType||"Powertrain");
  if(pt.horsepowerPs) bits.push(`${pt.horsepowerPs} PS`);
  return bits.filter(Boolean).join(" · ");
}

function TrimEditor({trim,powertrains,onChange,onRemove}:{trim:Trim;powertrains:PT[];onChange:(next:Trim)=>void;onRemove:()=>void}) {
  const set=(field:keyof Trim,value:any)=>onChange({...trim,[field]:value});
  const togglePt=(k:string)=>set("powertrainKeys",trim.powertrainKeys.includes(k)?trim.powertrainKeys.filter(x=>x!==k):[...trim.powertrainKeys,k]);
  const toggleUn=(f:string)=>set("unconfirmedFields",trim.unconfirmedFields.includes(f)?trim.unconfirmedFields.filter(x=>x!==f):[...trim.unconfirmedFields,f]);
  const linkedTypes = powertrains.filter(p=>trim.powertrainKeys.includes(p.clientKey)||!!(p.id&&trim.powertrainKeys.includes(p.id))).map(p=>p.powertrainType);
  const rangeRelevant = linkedTypes.some(t=>["BEV","PHEV","REEV"].includes(t)) || !!trim.publishedRangeKm || !!trim.standardizedWltpKm || !!trim.standardizedEpaKm;
  return <article className="dynamicAdminCard trimEditorCard">
    <div className="dynamicCardHead"><div><small>TRIM</small><b>{trim.name||"รุ่นย่อยใหม่"}</b></div><button type="button" className="adminDangerText" onClick={onRemove}>ลบ</button></div>
    <div className="adminEmbeddedGrid">
      <label className="adminField"><span>ชื่อ Trim</span><input value={trim.name} onChange={e=>set("name",e.target.value)} placeholder="เช่น HEV Premium"/></label>
      <label className="adminField"><span>ราคาปัจจุบัน (บาท)</span><input type="number" value={trim.priceBaht} onChange={e=>set("priceBaht",e.target.value)}/></label>
      <label className="adminField"><span>สถานะ</span><select value={trim.status} onChange={e=>set("status",e.target.value)}><option value="current">Current</option><option value="discontinued">Discontinued</option></select></label>
      <label className="adminField"><span>Seats override (ถ้าต่างจากรุ่นหลัก)</span><input type="number" value={trim.seatsOverride} onChange={e=>set("seatsOverride",e.target.value)}/></label>
      <label className="adminField"><span>Payload override (kg)</span><input type="number" step="0.1" value={trim.payloadCapacityKgOverride} onChange={e=>set("payloadCapacityKgOverride",e.target.value)}/></label>

      <fieldset className="adminCheckGroup adminFieldWide"><legend>Powertrain ที่ Trim นี้ใช้</legend><div className="trimPtChoices">{powertrains.length?powertrains.map(pt=><label key={pt.clientKey} className="adminCheckItem"><input type="checkbox" checked={trim.powertrainKeys.includes(pt.clientKey)||!!(pt.id&&trim.powertrainKeys.includes(pt.id))} onChange={()=>togglePt(pt.clientKey)}/><span><b>{pt.label||pt.powertrainType||"Powertrain"}</b><small>{ptSummary(pt)}</small></span></label>):<span className="mutedAdmin">เพิ่ม Powertrain ด้านบนก่อน</span>}</div></fieldset>

      <div className="adminField adminFieldWide adminSubGrid">
        <span>ยาง / ล้อ</span>
        <div className="adminInlineFields fourCols">
          <input value={trim.tireSizeFront} onChange={e=>set("tireSizeFront",e.target.value)} placeholder="ยางหน้า เช่น 225/55 R18"/>
          <input value={trim.tireSizeRear} onChange={e=>set("tireSizeRear",e.target.value)} placeholder="ยางหลัง (ถ้าต่าง)"/>
          <input value={trim.wheelSizeFront} onChange={e=>set("wheelSizeFront",e.target.value)} placeholder="ล้อหน้า เช่น 18 นิ้ว"/>
          <input value={trim.wheelSizeRear} onChange={e=>set("wheelSizeRear",e.target.value)} placeholder="ล้อหลัง (ถ้าต่าง)"/>
        </div>
      </div>

      {rangeRelevant?<div className="adminField adminFieldWide rangeAdminBox">
        <span>ระยะทางไฟฟ้า / EV Range</span>
        <div className="adminInlineFields rangeCols">
          <input type="number" step="0.1" value={trim.publishedRangeKm} onChange={e=>set("publishedRangeKm",e.target.value)} placeholder="Published range (km)"/>
          <select value={trim.publishedRangeCycle} onChange={e=>set("publishedRangeCycle",e.target.value)}><option value="">มาตรฐาน — ว่าง</option>{rangeCycles.map(c=><option key={c}>{c}</option>)}</select>
          <input type="number" step="0.1" value={trim.standardizedWltpKm} onChange={e=>set("standardizedWltpKm",e.target.value)} placeholder="TDR WLTP-equivalent (km)"/>
          <input type="number" step="0.1" value={trim.standardizedEpaKm} onChange={e=>set("standardizedEpaKm",e.target.value)} placeholder="EPA / EPA-equivalent (km)"/>
        </div>
        <input value={trim.rangeSourceUrl} onChange={e=>set("rangeSourceUrl",e.target.value)} placeholder="Source URL ของตัวเลข range (optional)"/>
        <small>Published = ตัวเลขที่บริษัทประกาศจริง. ค่า WLTP/EPA standardized ให้กรอกเมื่อมี reference หรือ methodology รองรับ ไม่ต้องเดา.</small>
      </div>:null}

      <label className="adminField adminFieldWide"><span>รายละเอียด Trim / อุปกรณ์ / Safety (เขียนอิสระ)</span><textarea rows={5} value={trim.description} onChange={e=>set("description",e.target.value)} placeholder="เขียนเฉพาะสิ่งที่มีประโยชน์ ไม่ต้องแตก field สีเบาะ/option จุกจิก"/></label>
    </div>
    <div className="uncertainStrip"><span>Unconfirmed:</span>{["price_baht","powertrain","seats","payload","wheel_tire","published_range","standardized_range"].map(f=><label key={f}><input type="checkbox" checked={trim.unconfirmedFields.includes(f)} onChange={()=>toggleUn(f)}/>{f}</label>)}</div>
  </article>;
}

export function ModelFormV12({brands,model,brandName,powertrains:initialPowertrains=[],trims:initialTrims=[]}:{brands:Row[];model?:Row|null;brandName?:string|null;powertrains?:Row[];trims?:Row[]}) {
  const modelUnconfirmed=useMemo(()=>new Set<string>(model?.unconfirmed_fields||[]),[model]);
  const [powertrains,setPowertrains]=useState<PT[]>(initialPowertrains.map(initialPT));
  const [trims,setTrims]=useState<Trim[]>(initialTrims.map(initialTrim));

  const addPt=()=>setPowertrains(p=>[...p,{id:undefined,clientKey:makeKey("pt"),label:"",powertrainType:"",engineCode:"",displacementCc:"",batteryCapacityKwh:"",batteryChemistry:"",motorOutputKw:"",horsepowerPs:"",torqueNm:"",transmission:"",drivetrain:"",notes:"",unconfirmedFields:[]}]);
  const addTrim=()=>setTrims(t=>[...t,{id:undefined,clientKey:makeKey("trim"),name:"",priceBaht:"",status:"current",description:"",seatsOverride:"",payloadCapacityKgOverride:"",powertrainKeys:[],tireSizeFront:"",tireSizeRear:"",wheelSizeFront:"",wheelSizeRear:"",publishedRangeKm:"",publishedRangeCycle:"",standardizedWltpKm:"",standardizedEpaKm:"",rangeSourceUrl:"",sortOrder:t.length,unconfirmedFields:[]}]);

  const ptJson=JSON.stringify(powertrains.map(p=>({...p,displacementCc:toNum(p.displacementCc),batteryCapacityKwh:toNum(p.batteryCapacityKwh),motorOutputKw:toNum(p.motorOutputKw),horsepowerPs:toNum(p.horsepowerPs),torqueNm:toNum(p.torqueNm)})));
  const trimJson=JSON.stringify(trims.map((t,i)=>({...t,priceBaht:toNum(t.priceBaht),seatsOverride:toNum(t.seatsOverride),payloadCapacityKgOverride:toNum(t.payloadCapacityKgOverride),publishedRangeKm:toNum(t.publishedRangeKm),standardizedWltpKm:toNum(t.standardizedWltpKm),standardizedEpaKm:toNum(t.standardizedEpaKm),sortOrder:i})));

  return <form action={saveModelV12} className="adminModelMasterForm">
    {model?.id?<input type="hidden" name="id" value={model.id}/>:null}
    <input type="hidden" name="powertrains_json" value={ptJson}/>
    <input type="hidden" name="trims_json" value={trimJson}/>

    <section className="adminFormSection">
      <div className="adminFormSectionHead"><h2>ข้อมูลรุ่นรถ</h2><p>Master record ของรุ่นปัจจุบัน ใช้ร่วมกันทั้ง Consumer Catalog และ Industry layer</p></div>
      <div className="adminFormSectionGrid">
        <Structured field="brand" current={modelUnconfirmed}><label className="adminField"><span>Brand</span><input name="brand_name" list="brand-list" defaultValue={brandName||""} placeholder="เลือกหรือพิมพ์แบรนด์ใหม่" required/><datalist id="brand-list">{brands.map(b=><option key={b.id} value={b.name_th}/>)}</datalist><small>พิมพ์ชื่อใหม่ได้ ระบบจะสร้าง Brand category ให้อัตโนมัติ</small></label></Structured>
        <Structured field="name_th" current={modelUnconfirmed}><Input label="Model" name="name_th" defaultValue={model?.name_th} required placeholder="เช่น Corolla Cross"/></Structured>
        <Structured field="generation" current={modelUnconfirmed}><Input label="Generation" name="generation" defaultValue={model?.generation} placeholder="เช่น 2nd Gen"/></Structured>
        <Structured field="segment" current={modelUnconfirmed}><Select label="Segment" name="segment" defaultValue={model?.segment}><EmptyOption/>{segments.map(x=><option key={x}>{x}</option>)}</Select></Structured>
        <Structured field="body_type" current={modelUnconfirmed}><Select label="Body type" name="body_type" defaultValue={model?.body_type}><EmptyOption/>{bodies.map(x=><option key={x}>{x}</option>)}</Select></Structured>
        <Structured field="market_position" current={modelUnconfirmed}><Select label="Market positioning" name="market_position" defaultValue={model?.market_position}><EmptyOption/>{positions.map(x=><option key={x}>{x}</option>)}</Select></Structured>
        <Structured field="production_type" current={modelUnconfirmed}><Select label="การผลิต / นำเข้า" name="production_type" defaultValue={model?.production_type}><EmptyOption/>{productionTypes.map(x=><option key={x}>{x}</option>)}</Select></Structured>
        <Structured field="production_country" current={modelUnconfirmed}><Select label="ประเทศที่ผลิต" name="production_country" defaultValue={model?.production_country}><EmptyOption/>{countries.map(x=><option key={x}>{x}</option>)}</Select></Structured>
        <Structured field="launch_period" current={modelUnconfirmed}><div className="adminField"><span>เปิดตัวประเทศไทย</span><div className="adminInlineFields"><select name="launch_quarter" defaultValue={model?.launch_quarter||""}><option value="">Quarter — ว่าง</option>{qtrs.map(q=><option key={q}>{q}</option>)}</select><input name="launch_year" type="number" min="2000" max="2100" defaultValue={model?.launch_year||""} placeholder="ปี ค.ศ."/></div></div></Structured>
        <Structured field="seats" current={modelUnconfirmed}><Input label="จำนวนที่นั่ง" name="seats" type="number" defaultValue={model?.seats}/></Structured>
        <Structured field="payload_capacity_kg" current={modelUnconfirmed}><Input label="Payload capacity (kg)" name="payload_capacity_kg" type="number" defaultValue={model?.payload_capacity_kg}/></Structured>
        <Structured field="status" current={modelUnconfirmed}><Select label="สถานะ" name="status" defaultValue={model?.status||"current"}><option value="current">Current</option><option value="discontinued">Discontinued / Archive</option></Select></Structured>
        <label className="adminCheckItem simpleCheck"><input type="checkbox" name="featured" defaultChecked={!!model?.featured}/><span><b>Featured</b><small>อนุญาตให้หน้าแรกหยิบรุ่นนี้มาโชว์</small></span></label>
        <Structured field="image_url" current={modelUnconfirmed}><Input label="URL รูปหลัก" name="image_url" defaultValue={model?.image_url}/></Structured>
      </div>
    </section>

    <section className="adminFormSection">
      <div className="adminFormSectionHead"><h2>ขนาดตัวถัง</h2><p>ใช้หน่วยมิลลิเมตร และปล่อยว่างได้ถ้ายังไม่มีข้อมูล</p></div>
      <div className="adminFormSectionGrid">
        <Structured field="length_mm" current={modelUnconfirmed}><Input label="ความยาว (mm)" name="length_mm" type="number" defaultValue={model?.length_mm}/></Structured>
        <Structured field="width_mm" current={modelUnconfirmed}><Input label="ความกว้าง (mm)" name="width_mm" type="number" defaultValue={model?.width_mm}/></Structured>
        <Structured field="wheelbase_mm" current={modelUnconfirmed}><Input label="ฐานล้อ (mm)" name="wheelbase_mm" type="number" defaultValue={model?.wheelbase_mm}/></Structured>
        <Structured field="consumer_description" current={modelUnconfirmed}><label className="adminField adminFieldWide"><span>ที่มาและบริบทของรุ่น</span><textarea name="consumer_description" rows={6} defaultValue={model?.consumer_description||""} placeholder="อธิบายว่ารถรุ่นนี้มาจากไหน ผลิตฐานไหน มีบทบาทอะไรในตลาดไทย — ไม่ใช่การทวน spec"/></label></Structured>
      </div>
    </section>

    <section className="adminFormSection"><div className="adminFormSectionHead actionHead"><div><h2>Powertrain configurations</h2><p>กรอกชุดเครื่อง/แบตครั้งเดียว แล้วเอาไปผูกกับ Trim ด้านล่าง</p></div><button className="adminSecondary" type="button" onClick={addPt}>+ เพิ่ม Powertrain</button></div><div className="dynamicCardStack">{powertrains.length?powertrains.map((pt,i)=><PTEditor key={pt.clientKey} pt={pt} onChange={next=>setPowertrains(arr=>arr.map((x,j)=>j===i?next:x))} onRemove={()=>setPowertrains(arr=>arr.filter((_,j)=>j!==i))}/>):<div className="adminBlankBlock">ยังไม่มี Powertrain — กด “+ เพิ่ม Powertrain”</div>}</div></section>

    <section className="adminFormSection"><div className="adminFormSectionHead actionHead"><div><h2>Trims / ราคา / ล้อ / Range</h2><p>ราคาและ Range บนหน้า Consumer คำนวณจาก Trim ที่สถานะ Current โดยอัตโนมัติ</p></div><button className="adminSecondary" type="button" onClick={addTrim}>+ เพิ่ม Trim</button></div><div className="dynamicCardStack">{trims.length?trims.map((trim,i)=><TrimEditor key={trim.clientKey} trim={trim} powertrains={powertrains} onChange={next=>setTrims(arr=>arr.map((x,j)=>j===i?next:x))} onRemove={()=>setTrims(arr=>arr.filter((_,j)=>j!==i))}/>):<div className="adminBlankBlock">ยังไม่มี Trim — กด “+ เพิ่ม Trim”</div>}</div></section>

    <section className="adminFormSection"><div className="adminFormSectionHead"><h2>หมายเหตุภายใน</h2></div><div className="adminFormSectionGrid"><label className="adminField adminFieldWide"><span>Notes</span><textarea name="notes" rows={4} defaultValue={model?.notes||""}/></label></div></section>
    <div className="stickyAdminSave"><button className="adminPrimary" type="submit">{model?.id?"บันทึก Model + Powertrain + Trims":"สร้าง Model"}</button><span>Powertrain/Trim ที่ลบออกจาก panel จะถูกลบจริงเมื่อกดบันทึก</span></div>
  </form>;
}
