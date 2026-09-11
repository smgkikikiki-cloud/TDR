import { randomUUID } from "node:crypto";
import Link from "next/link";
import {
  enqueueModelTaxonomyInput,
  enqueuePriceInput,
  enqueueVehicleInput,
  enqueueWithdrawModel,
} from "@/app/admin/input-actions";
import { enqueuePriceCoverageDisposition } from "@/app/admin/price-coverage-actions";
import { priceCoverageDecisions } from "@/lib/price-coverage-review";
import { oemTargetsForModel } from "@/lib/price-evidence-registry";
import { adminDb } from "@/lib/supabase";

const SEGMENTS = ["A", "B", "C", "D", "E", "F", "UNKNOWN"];
const BODY_TYPES = [
  "HATCHBACK", "SEDAN", "CROSSOVER", "PPV", "OFFROAD", "COUPE",
  "MPV", "PICKUP", "WAGON", "VAN", "TRUCK", "OTHER",
];

function money(value: unknown) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? `${number.toLocaleString("th-TH")} บาท` : "ยังไม่มี List price";
}

function currentPrice(row: any) {
  return row?.current_list_price?.amount_thb ?? null;
}

function kindLabel(kind?: string) {
  return ({
    price: "ราคา",
    model: "ข้อมูลรุ่น/Taxonomy",
    withdraw: "ถอนรุ่น",
    advanced: "Advanced batch",
  } as Record<string, string>)[kind || ""] || "Canonical input";
}

export default async function VehicleInputPage({
  searchParams,
}: {
  searchParams: Promise<{ queued?: string; kind?: string; model?: string }>;
}) {
  const query = await searchParams;
  const db = adminDb();
  const submittedAt = new Date().toISOString();
  const today = submittedAt.slice(0, 10);

  const [modelsResult, trimsResult, batchesResult, coverageResult, releaseResult] = db
    ? await Promise.all([
        db.from("current_vehicle_models")
          .select("release_id,canonical_id,brand_id,name_en,name_th,generation_id,segment,body_type,status")
          .order("brand_id", { ascending: true }).order("name_en", { ascending: true }).limit(1000),
        db.from("current_market_trims")
          .select("release_id,canonical_id,model_id,name,powertrain,status,current_list_price")
          .order("model_id", { ascending: true }).order("name", { ascending: true }).limit(1000),
        db.from("canonical_input_batches")
          .select("batch_key,source_kind,item_count,status,pull_request_url,release_id,error,created_at")
          .order("created_at", { ascending: false }).limit(25),
        db.from("registration_analytics_coverage")
          .select("period,total_registrations,mapped_registrations,mapped_unit_pct")
          .order("period", { ascending: false }).limit(1),
        db.from("canonical_vehicle_releases")
          .select("release_id,canonical_revision,as_of,status,activated_at,counts")
          .order("activated_at", { ascending: false }).limit(1),
      ])
    : [{ data: [] }, { data: [] }, { data: [] }, { data: [] }, { data: [] }];

  const models = modelsResult.data || [];
  const trims = trimsResult.data || [];
  const batches = batchesResult.data || [];
  const coverage = coverageResult.data?.[0] || null;
  const release = releaseResult.data?.[0] || null;
  const modelNames = new Map(models.map((model: any) => [model.canonical_id, `${model.brand_id?.toUpperCase() || ""} ${model.name_en || model.name_th || model.canonical_id}`.trim()]));
  const pricedModels = new Set(trims.filter((trim: any) => currentPrice(trim)).map((trim: any) => trim.model_id));
  const queueCount = batches.filter((batch: any) => batch.status === "QUEUED" || batch.status === "PROCESSING").length;
  const failedCount = batches.filter((batch: any) => batch.status === "FAILED").length;
  const requestedModel = String(query.model || "").trim();
  const focusedModel = models.some((model: any) => model.canonical_id === requestedModel) ? requestedModel : "";
  const focusedModelTrims = focusedModel ? trims.filter((trim: any) => trim.model_id === focusedModel) : [];
  const missingFocusedTrims = focusedModelTrims.filter((trim: any) => !currentPrice(trim));
  const coverageReviews = priceCoverageDecisions();
  const deferredFocusedTrims = missingFocusedTrims.filter((trim: any) => coverageReviews.has(String(trim.canonical_id)));
  const actionableFocusedTrims = missingFocusedTrims.filter((trim: any) => !coverageReviews.has(String(trim.canonical_id)));
  const priceTrims = focusedModel
    ? (missingFocusedTrims.length ? actionableFocusedTrims : focusedModelTrims)
    : trims;
  const focusedTargets = focusedModel ? oemTargetsForModel(focusedModel) : [];

  const exampleTrim = trims.find((trim: any) => trim.canonical_id === "jaecoo.jaecoo_5_ev.j5.trim.max_plus_bev") || trims[0];
  const example = JSON.stringify({
    schema_version: 1,
    batch_id: `admin-advanced-${randomUUID()}`,
    year: Number(String(release?.as_of || today).slice(0, 4)),
    submitted_at: submittedAt,
    source: { kind: "OEM", ref: "https://example.com/official-price" },
    reason: "official list price",
    commands: [{
      operation: "APPEND_PRICE",
      canonical_id: exampleTrim?.canonical_id || "brand.model.generation.trim.example",
      payload: {
        amount_thb: 899000,
        price_type: "LIST_PRICE",
        effective_from: today,
        observed_at: today,
        source: "official_oem",
        source_ref: "https://example.com/official-price",
      },
    }],
  }, null, 2);

  return <div className="adminEditor">
    <div className="adminHeader">
      <div>
        <small>VEHICLE MASTER · ADMIN BENCH</small>
        <h1>แก้ข้อมูลรถจากจุดเดียว</h1>
        <p>Quick input ทุกอันเข้าคิวเดียวกับ canonical pipeline: validate → revision → PR → release. ไม่เขียน Catalog หรือ Paid analytics ตรง ๆ</p>
      </div>
      <Link className="adminPrimaryLink" href="/admin/library?table=canonical_input_batches">เปิด Input library</Link>
    </div>

    {query.queued ? <div className="adminSaved">
      {query.queued === "duplicate" ? "คำสั่งชุดเดิมอยู่ในคิวแล้ว — ไม่สร้างซ้ำ" : `รับ ${kindLabel(query.kind)} เข้าคิวแล้ว`}
    </div> : null}

    <div className="adminStatGrid">
      <div className="adminStat"><span>Canonical models</span><strong>{models.length}</strong><small>active release</small></div>
      <div className="adminStat"><span>MarketTrims</span><strong>{trims.length}</strong><small>ราคาอ้างด้วย stable trim ID</small></div>
      <div className="adminStat"><span>Models with list price</span><strong>{pricedModels.size}</strong><small>ต้อง backfill ต่อ</small></div>
      <div className="adminStat"><span>Registration mapped</span><strong>{coverage ? `${Number(coverage.mapped_unit_pct).toFixed(1)}%` : "—"}</strong><small>{coverage ? String(coverage.period).slice(0, 7) : "no data"}</small></div>
      <div className="adminStat"><span>Input queue</span><strong>{queueCount}</strong><small>{failedCount ? `${failedCount} failed ใน 25 รายการล่าสุด` : "ไม่มี failed ใน 25 รายการล่าสุด"}</small></div>
    </div>

    <div className="adminNotice">
      <b>Source of truth lock</b>
      <span>แก้รถ/รุ่น/ราคาใน Bench → Vehicle Master canonical files → active release → Free Catalog / Free Compare / Paid Market ใช้ชุดเดียวกัน. Registration facts ยังแยก ingest และไม่สร้าง MarketTrim.</span>
      <code>{release?.release_id || "no active release"} · as of {release?.as_of || "—"}</code>
    </div>

    {focusedModel ? <div className="adminNotice">
      <b>Focused LIST_PRICE backfill · {modelNames.get(focusedModel) || focusedModel}</b>
      <span>ขาด LIST_PRICE {missingFocusedTrims.length} trim · actionable {actionableFocusedTrims.length} · deferred {deferredFocusedTrims.length}. Deferred ยังบล็อก readiness เหมือนเดิม แต่ไม่ถูกโยนกลับเข้ากองงานซ้ำจนกว่าจะ Reopen.</span>
      <Link href="/admin/prices/coverage">กลับ Price Coverage Worklist ↗</Link>
    </div> : null}

    {focusedModel && focusedTargets.length ? <>
      <div className="adminHeader"><div><small>REGISTERED OEM EVIDENCE</small><h2>เปิดหลักฐานก่อนกรอกราคา</h2><p>รายการนี้เป็น target ที่ registry ผูกกับ canonical model นี้โดยตรง. อ่าน note ก่อนใช้ เพราะบาง OEM page ใช้ยืนยัน model ได้แต่ไม่มีราคาใน HTML/page content.</p></div></div>
      <div className="adminQuickGrid">{focusedTargets.map((target) => <a key={target.id} href={target.url} target="_blank" rel="noreferrer">
        <b>{target.sourceId}</b><span>{target.role} ↗</span><small>{target.notes || target.url}</small>
      </a>)}</div>
    </> : null}

    {focusedModel && deferredFocusedTrims.length ? <>
      <div className="adminHeader"><div><small>DEFERRED LIST_PRICE</small><h2>ตรวจแล้ว แต่ตลาดยังไม่มี canonical answer</h2><p>รายการนี้ไม่ถูกนับ ready. Reopen เมื่อ OEM ประกาศราคา final หรือ evidence conflict ถูกคลี่คลาย.</p></div></div>
      <div className="adminQuickGrid">{deferredFocusedTrims.map((trim: any) => {
        const decision = coverageReviews.get(String(trim.canonical_id))!;
        return <div key={trim.canonical_id}>
          <b>{trim.name} · {trim.powertrain || "?"}</b>
          <span>{decision.reasonCode}</span>
          <small>{decision.reviewedAt} · {decision.reviewer}{decision.notes ? ` · ${decision.notes}` : ""}</small>
          <a href={decision.sourceRef} target="_blank" rel="noreferrer">Evidence ↗</a>
          <form action={enqueuePriceCoverageDisposition} className="adminForm">
            <input type="hidden" name="submission_id" value={randomUUID()} />
            <input type="hidden" name="submitted_at" value={submittedAt} />
            <input type="hidden" name="trim_id" value={trim.canonical_id} />
            <input type="hidden" name="disposition" value="reopen" />
            <input type="hidden" name="notes" value={`Reopen ${decision.reasonCode}`} />
            <button>Reopen</button>
          </form>
        </div>;
      })}</div>
    </> : null}

    {focusedModel && actionableFocusedTrims.length ? <>
      <div className="adminHeader"><div><small>WORKFLOW DISPOSITION</small><h2>Defer เฉพาะกรณีที่ไม่มี LIST_PRICE ที่ publishable จริง</h2><p>ใช้เพื่อหยุดงานซ้ำ ไม่ใช่ bypass ราคา. ต้องอ้าง evidence URL ที่ทำให้ตัดสินว่า final MSRP ยังไม่มี/ขัดกัน.</p></div></div>
      <form action={enqueuePriceCoverageDisposition} className="adminForm">
        <input type="hidden" name="submission_id" value={randomUUID()} />
        <input type="hidden" name="submitted_at" value={submittedAt} />
        <input type="hidden" name="disposition" value="defer" />
        <label className="adminField adminFieldWide"><span>MarketTrim</span><select name="trim_id" required defaultValue={actionableFocusedTrims.length === 1 ? actionableFocusedTrims[0].canonical_id : ""}>
          <option value="" disabled>เลือก missing trim…</option>
          {actionableFocusedTrims.map((trim: any) => <option key={trim.canonical_id} value={trim.canonical_id}>{trim.name} · {trim.powertrain || "?"}</option>)}
        </select></label>
        <label className="adminField"><span>เหตุผล</span><select name="reason_code" defaultValue="AWAITING_FINAL_LIST_PRICE" required>
          <option value="AWAITING_FINAL_LIST_PRICE">AWAITING_FINAL_LIST_PRICE</option>
          <option value="OFFICIAL_EVIDENCE_CONFLICT">OFFICIAL_EVIDENCE_CONFLICT</option>
          <option value="NO_RELIABLE_EVIDENCE">NO_RELIABLE_EVIDENCE</option>
        </select></label>
        <label className="adminField"><span>Evidence URL</span><input name="source_ref" type="url" placeholder="https://…" required /></label>
        <label className="adminField adminFieldWide"><span>Review note</span><input name="notes" type="text" placeholder="OEM still labels this as estimated / official pages conflict…" required /></label>
        <div className="adminFormActions"><button>Defer from actionable queue</button></div>
      </form>
    </> : null}

    <div className="adminHeader"><div><small>QUICK INPUT 01</small><h2>เพิ่ม / เปลี่ยนราคาหลัก</h2><p>ใช้กับ MSRP / ราคาเปิดตัว / estimated price ที่มีหลักฐาน. Campaign ซับซ้อนยังเก็บใน Advanced เพื่อไม่บิดเงื่อนไขโปร.</p></div></div>
    {priceTrims.length ? <form action={enqueuePriceInput} className="adminForm">
      <input type="hidden" name="submission_id" value={randomUUID()} />
      <input type="hidden" name="submitted_at" value={submittedAt} />
      <label className="adminField adminFieldWide"><span>MarketTrim</span><select name="trim_id" required defaultValue={priceTrims.length === 1 ? priceTrims[0].canonical_id : ""}>
        <option value="" disabled>เลือกรุ่นย่อย…</option>
        {priceTrims.map((trim: any) => <option key={trim.canonical_id} value={trim.canonical_id}>
          {modelNames.get(trim.model_id) || trim.model_id} — {trim.name} · {trim.powertrain || "?"} · {money(currentPrice(trim))}
        </option>)}
      </select></label>
      <label className="adminField"><span>ราคา (บาท)</span><input name="amount_thb" type="number" min="1" step="1" required /></label>
      <label className="adminField"><span>ประเภทราคา</span><select name="price_type" defaultValue="LIST_PRICE">
        <option value="LIST_PRICE">LIST PRICE / MSRP</option>
        <option value="INTRODUCTORY_PRICE">INTRODUCTORY PRICE</option>
        <option value="ESTIMATED_PRICE">ESTIMATED PRICE</option>
      </select></label>
      <label className="adminField"><span>วันที่ตรวจพบ</span><input name="observed_at" type="date" defaultValue={today} required /></label>
      <label className="adminField"><span>วันที่เริ่มมีผล (ถ้ารู้)</span><input name="effective_from" type="date" /></label>
      {focusedTargets.length ? <label className="adminField adminFieldWide"><span>Registered OEM target (ถ้าหน้านี้มีราคาจริง)</span><select name="target_id" defaultValue="">
        <option value="">ไม่ใช้ registry target — ใช้ source ref ด้านล่าง</option>
        {focusedTargets.map((target) => <option key={target.id} value={target.id}>{target.sourceId} · {target.role} · {target.id}</option>)}
      </select></label> : null}
      <label className="adminField"><span>ชนิดแหล่งข้อมูล</span><select name="source_kind" defaultValue="OEM">
        <option value="OEM">OEM / official</option><option value="ECO">EcoSticker</option><option value="MEDIA">Media</option>
        <option value="PRICE_HARVEST">Price Harvester</option><option value="API">API</option><option value="ADMIN">Admin manual evidence</option>
      </select></label>
      <label className="adminField"><span>Source URL / ref</span><input name="source_ref" type="text" placeholder={focusedTargets.length ? "เว้นได้เมื่อเลือก registered OEM target" : "https://…"} /></label>
      <label className="adminField adminFieldWide"><span>เหตุผล / หลักฐานย่อ</span><input name="reason" type="text" placeholder="Official Thai page lists this trim at MSRP…" required /></label>
      <div className="adminFormActions"><button className="adminPrimary">Validate + enqueue price</button></div>
    </form> : focusedModel && missingFocusedTrims.length ? <div className="adminNotice"><span>ไม่มี actionable missing trim ในรุ่นนี้ตอนนี้ — missing ทั้งหมดถูก defer ไว้. Reopen ด้านบนเมื่อ evidence เปลี่ยน.</span></div> : <div className="adminNotice"><span>ไม่มี MarketTrim ให้เพิ่มราคาใน scope นี้.</span></div>}

    <div className="adminHeader"><div><small>QUICK INPUT 02</small><h2>แก้ Model / Taxonomy</h2><p>ช่องว่าง = ไม่แก้. Quick mode จำกัดเฉพาะ field ที่ Vehicle Master เป็นเจ้าของจริง; variant/powertrain และรายละเอียดลึกใช้ Advanced.</p></div></div>
    <form action={enqueueModelTaxonomyInput} className="adminForm">
      <input type="hidden" name="submission_id" value={randomUUID()} />
      <input type="hidden" name="submitted_at" value={submittedAt} />
      <label className="adminField adminFieldWide"><span>Canonical model</span><select name="model_id" required defaultValue="">
        <option value="" disabled>เลือกรุ่น…</option>
        {models.map((model: any) => <option key={model.canonical_id} value={model.canonical_id}>
          {modelNames.get(model.canonical_id)} · currently {model.segment || "?"} / {model.body_type || "?"}
        </option>)}
      </select></label>
      <label className="adminField"><span>Name EN (ว่าง = ไม่แก้)</span><input name="name_en" type="text" /></label>
      <label className="adminField"><span>Name TH (ว่าง = ไม่แก้)</span><input name="name_th" type="text" /></label>
      <label className="adminField"><span>Segment (ว่าง = ไม่แก้)</span><select name="segment" defaultValue=""><option value="">ไม่แก้</option>{SEGMENTS.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
      <label className="adminField"><span>Body type (ว่าง = ไม่แก้)</span><select name="body_type" defaultValue=""><option value="">ไม่แก้</option>{BODY_TYPES.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
      <label className="adminField adminFieldWide"><span>เหตุผลการแก้</span><input name="reason" type="text" placeholder="Correct DLT market taxonomy / official model naming…" required /></label>
      <div className="adminFormActions"><button className="adminPrimary">Validate + enqueue model change</button></div>
    </form>

    <div className="adminHeader"><div><small>QUICK INPUT 03</small><h2>ถอนรุ่นออกจาก Current catalog</h2><p>ไม่ลบ identity และไม่ลบ history — worker จะ mark เป็น HISTORICAL และปิด generation ตามวันที่ที่ให้.</p></div></div>
    <form action={enqueueWithdrawModel} className="adminForm">
      <input type="hidden" name="submission_id" value={randomUUID()} />
      <input type="hidden" name="submitted_at" value={submittedAt} />
      <label className="adminField adminFieldWide"><span>Canonical model</span><select name="model_id" required defaultValue=""><option value="" disabled>เลือกรุ่น…</option>{models.map((model: any) => <option key={model.canonical_id} value={model.canonical_id}>{modelNames.get(model.canonical_id)}</option>)}</select></label>
      <label className="adminField"><span>วันที่ยุติขาย / generation ended</span><input name="ended" type="date" /></label>
      <label className="adminField"><span>เหตุผล</span><input name="reason" type="text" placeholder="Discontinued / replaced by new generation…" required /></label>
      <div className="adminFormActions"><button className="adminPrimary">Validate + enqueue withdrawal</button></div>
    </form>

    <details className="adminNotice">
      <summary><b>Advanced · Canonical batch JSON</b> — variant / powertrain / spec / multi-command</summary>
      <p>นี่คือ escape hatch เดิม ไม่ใช่ source ใหม่. JSON ด้านล่างเข้าคิวและผ่าน worker/validator ตัวเดียวกับ Quick input.</p>
      <form action={enqueueVehicleInput} className="adminForm">
        <label className="adminField adminFieldWide"><span>Input batch JSON</span><textarea name="payload" rows={24} defaultValue={example} required /></label>
        <div className="adminFormActions"><button className="adminPrimary">Validate + enqueue advanced batch</button></div>
      </form>
    </details>

    <div className="adminHeader"><div><small>PIPELINE STATUS</small><h2>25 batches ล่าสุด</h2><p>QUEUED → PROCESSING → STAGED (PR) → PUBLISHED. FAILED ต้องแก้ที่ input/validator ไม่ใช่ bypass master.</p></div></div>
    <div className="libraryTable"><table><thead><tr><th>Batch</th><th>Source</th><th>Items</th><th>Status</th><th>Result</th></tr></thead><tbody>
      {batches.length ? batches.map((row: any) => <tr key={row.batch_key}>
        <td><b>{row.batch_key}</b><small>{new Date(row.created_at).toLocaleString("th-TH")}</small></td>
        <td>{row.source_kind}</td><td>{row.item_count}</td><td>{row.status}</td>
        <td>{row.pull_request_url ? <a href={row.pull_request_url} target="_blank" rel="noreferrer">PR ↗</a> : row.release_id || row.error || "—"}</td>
      </tr>) : <tr><td colSpan={5}>ยังไม่มี batch</td></tr>}
    </tbody></table></div>
  </div>;
}
