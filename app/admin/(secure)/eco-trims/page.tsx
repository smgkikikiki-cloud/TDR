import { randomUUID } from "node:crypto";
import Link from "next/link";
import { enqueueEcoAttachExistingTrim, enqueueEcoMarketTrim, enqueueEcoReviewDisposition } from "@/app/admin/eco-trim-actions";
import ecoReviewState from "@/automotive/vehicle_master/vehreg/data/2026/ingest/ecosticker/review/2026-09-08.json";
import {
  ECO_TRIM_SNAPSHOT_DATE,
  getEcoTrimCandidateGroups,
  getEcoTrimSnapshotHash,
} from "@/lib/eco-trim-snapshot";
import { getPriceCoverageWorklist } from "@/lib/price-coverage-worklist";
import { adminDb } from "@/lib/supabase";
import styles from "./eco-trims.module.css";

export const dynamic = "force-dynamic";

const ECO_DETAIL_ROOT = "https://car.ecosticker.go.th/landing-page/detail/";
type SearchParams = Record<string, string | string[] | undefined>;
type ModelLabel = { brand: string; name: string };
type MarketImpact = { regs: number; share: number; blocker: string };
type ExistingTrimOption = { canonicalId: string; name: string; powertrain: string; sourceCount: number };
type ReviewDecision = {
  source_id: string;
  action: string;
  reviewer: string;
  origin?: string;
  reviewed_at?: string;
  notes?: string;
};
function first(value: string | string[] | undefined) { return Array.isArray(value) ? value[0] : value; }
function one(value: string | string[] | undefined) { return String(first(value) || "").trim(); }
function n(value: unknown) { const number = Number(value); return Number.isFinite(number) ? number.toLocaleString("th-TH") : "—"; }
function money(min: number | null, max: number | null) {
  if (min == null || max == null) return "—";
  return min === max ? `${n(min)} ฿` : `${n(min)}–${n(max)} ฿`;
}
function ecoRefs(row: any): string[] {
  const refs = row?.source_refs?.ecosticker;
  return Array.isArray(refs) ? refs.map((value) => String(value || "").toLowerCase()).filter(Boolean) : [];
}

export default async function EcoTrimReviewPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const sp = await searchParams;
  const q = one(sp.q).toLocaleLowerCase();
  const modelFilter = one(sp.model);
  const showAttached = one(sp.attached) === "1";
  const showReviewed = one(sp.reviewed) === "1";
  const db = adminDb();
  if (!db) return <div className="adminEditor"><div className="adminNotice">Admin database is not configured.</div></div>;

  const groups = getEcoTrimCandidateGroups();
  const snapshotHash = getEcoTrimSnapshotHash();
  const humanReviewBySource = new Map<string, ReviewDecision>(
    (ecoReviewState.decisions as ReviewDecision[])
      .filter((row) => row.origin === "human" || String(row.reviewer || "").toLowerCase() !== "agent-proposed")
      .map((row) => [String(row.source_id).toLowerCase(), row]),
  );
  const [{ data: modelsData, error: modelsError }, { data: brandsData, error: brandsError }, { data: trimsData, error: trimsError }, impact] = await Promise.all([
    db.from("current_vehicle_models")
      .select("canonical_id,brand_id,name_en,name_th,generation_id").limit(1000),
    db.from("current_vehicle_brands")
      .select("canonical_id,name_en,name_th").limit(500),
    db.from("current_market_trims")
      .select("canonical_id,model_id,generation_id,name,powertrain,source_refs").limit(1000),
    getPriceCoverageWorklist(db, 321),
  ]);
  if (modelsError) throw new Error(`ECO review model query failed: ${modelsError.message}`);
  if (brandsError) throw new Error(`ECO review brand query failed: ${brandsError.message}`);
  if (trimsError) throw new Error(`ECO review trim query failed: ${trimsError.message}`);

  const brands = new Map<string, string>((brandsData || []).map((row: any): [string, string] => [
    String(row.canonical_id), String(row.name_en || row.name_th || row.canonical_id),
  ]));
  const models = new Map<string, ModelLabel>((modelsData || []).map((row: any): [string, ModelLabel] => [String(row.canonical_id), {
    brand: brands.get(String(row.brand_id)) || String(row.brand_id || ""),
    name: String(row.name_en || row.name_th || row.canonical_id),
  }]));
  const trims = trimsData || [];
  const trimCountByModel = new Map<string, number>();
  const attachedSourceIds = new Set<string>();
  for (const row of trims) {
    const modelId = String(row.model_id || "");
    trimCountByModel.set(modelId, (trimCountByModel.get(modelId) || 0) + 1);
    for (const sourceId of ecoRefs(row)) attachedSourceIds.add(sourceId);
  }
  const impactByModel = new Map<string, MarketImpact>(impact.items.map((row): [string, MarketImpact] => [row.canonicalModelId, {
    regs: row.registrations3m,
    share: row.registrationSharePct,
    blocker: row.blocker,
  }]));

  const enriched = groups.map((group) => {
    const model = models.get(group.modelId);
    const attached = group.sourceIds.some((id) => attachedSourceIds.has(id));
    const market = impactByModel.get(group.modelId) || { regs: 0, share: 0, blocker: "—" };
    const humanDecisions = group.sourceIds
      .map((id) => humanReviewBySource.get(id.toLowerCase()))
      .filter((row): row is ReviewDecision => Boolean(row));
    const actionSet = new Set(humanDecisions.map((row) => row.action));
    const reviewDisposition = humanDecisions.length === group.sourceIds.length
      && actionSet.size === 1
      && ["reject", "defer"].includes(humanDecisions[0]?.action || "")
      ? humanDecisions[0].action
      : null;
    const reviewSummary = humanDecisions.length
      ? [...new Set(humanDecisions.map((row) => `${row.reviewer} · ${row.reviewed_at || "—"}${row.notes ? ` · ${row.notes}` : ""}`))].join(" | ")
      : "";
    const existingTrimOptions: ExistingTrimOption[] = trims
      .filter((row: any) => row.model_id === group.modelId
        && row.generation_id === group.generationId
        && String(row.powertrain || "").toUpperCase() === group.powertrain)
      .map((row: any): ExistingTrimOption => ({
        canonicalId: String(row.canonical_id || ""),
        name: String(row.name || row.canonical_id || ""),
        powertrain: String(row.powertrain || "").toUpperCase(),
        sourceCount: ecoRefs(row).length,
      }))
      .filter((row: ExistingTrimOption) => Boolean(row.canonicalId && row.name))
      .sort((a: ExistingTrimOption, b: ExistingTrimOption) => a.name.localeCompare(b.name));
    return {
      ...group,
      attached,
      reviewDisposition,
      reviewSummary,
      humanReviewedCount: humanDecisions.length,
      brand: model?.brand || group.modelId.split(".")[0].toUpperCase(),
      modelName: model?.name || group.modelId,
      currentTrimCount: trimCountByModel.get(group.modelId) || 0,
      existingTrimOptions,
      registrations3m: market.regs,
      registrationSharePct: market.share,
      priceBlocker: market.blocker,
    };
  });

  const modelOptions = [...new Map<string, string>(enriched.map((row): [string, string] => [row.modelId, `${row.brand} ${row.modelName}`])).entries()]
    .sort((a, b) => a[1].localeCompare(b[1]));
  const visible = enriched
    .filter((row) => showAttached || !row.attached)
    .filter((row) => showReviewed || !row.reviewDisposition)
    .filter((row) => !modelFilter || row.modelId === modelFilter)
    .filter((row) => !q || `${row.brand} ${row.modelName} ${row.rawLabel} ${row.powertrain} ${row.modelId}`.toLocaleLowerCase().includes(q))
    .sort((a, b) => b.registrations3m - a.registrations3m || b.sourceCount - a.sourceCount || `${a.brand} ${a.modelName} ${a.rawLabel}`.localeCompare(`${b.brand} ${b.modelName} ${b.rawLabel}`));
  const shown = visible.slice(0, 80);
  const attachedGroups = enriched.filter((row) => row.attached).length;
  const rejectedGroups = enriched.filter((row) => row.reviewDisposition === "reject").length;
  const deferredGroups = enriched.filter((row) => row.reviewDisposition === "defer").length;
  const noTrimGroups = enriched.filter((row) => !row.attached && !row.reviewDisposition && row.currentTrimCount === 0).length;
  const attachableGroups = enriched.filter((row) => !row.attached && !row.reviewDisposition && row.existingTrimOptions.length > 0).length;
  const submittedAt = new Date().toISOString();

  return <div className="adminEditor">
    <div className="adminHeader">
      <div>
        <small>ADMIN BENCH · ECO → MARKETTRIM REVIEW</small>
        <h1>Review ECO identity → Attach / Create / Reject / Defer</h1>
        <p>Snapshot ถูก hash-verify ก่อนอ่าน. Identity ที่ใช่ไป canonical queue; record ที่ไม่ใช่ retail trim ให้ reject; เคสที่หลักฐานยังไม่พอให้ defer. HUMAN-reviewed disposition ถูกเก็บใน review file เดิมผ่าน staging PR.</p>
      </div>
      <Link className="adminPrimaryLink" href="/admin/prices/coverage">ดู Price coverage ↗</Link>
    </div>

    <div className="adminStatGrid">
      <div className="adminStat"><span>Ready candidate groups</span><strong>{n(enriched.length)}</strong><small>exact signature groups, not fuzzy merged</small></div>
      <div className="adminStat"><span>Already attached</span><strong>{n(attachedGroups)}</strong><small>hidden by default</small></div>
      <div className="adminStat"><span>Attachable to existing</span><strong>{n(attachableGroups)}</strong><small>same model + generation + powertrain</small></div>
      <div className="adminStat"><span>Reject / Defer</span><strong>{n(rejectedGroups)} / {n(deferredGroups)}</strong><small>HUMAN dispositions, hidden by default</small></div>
      <div className="adminStat"><span>No MarketTrim yet</span><strong>{n(noTrimGroups)}</strong><small>unresolved groups on models with 0 current trims</small></div>
    </div>

    <div className="adminNotice">
      <b>Attach first, create only when needed</b>
      <span>ถ้า ECO candidate คือ grade ที่มี canonical MarketTrim อยู่แล้ว ให้เลือก Attach. Create new ใช้เมื่อ reviewer ยืนยันว่าเป็น grade ใหม่จริง. Reject/Defer เป็น review metadata ไม่แตะ serving vehicle facts.</span>
    </div>
    <div className="adminNotice">
      <b>Identity only</b>
      <span>ECO ราคา / dimensions / tyre / wheel / battery ที่เห็นใน source ไม่ถูกส่งไปพร้อม identity review. LIST_PRICE ต้องเข้าผ่าน Price Ledger และ evidence policy แยกต่างหาก.</span>
    </div>
    <div className="adminNotice">
      <b>Snapshot</b>
      <span>{ECO_TRIM_SNAPSHOT_DATE} · sha256:{snapshotHash.slice(0, 16)}… · human dispositions มาจาก review file ที่ version-control อยู่กับ snapshot เดิม</span>
    </div>

    <form className="adminForm" method="get">
      <label className="adminField adminFieldWide"><span>ค้นหา Brand / Model / raw ECO label</span><input name="q" defaultValue={one(sp.q)} placeholder="D-Max / Ranger / Mazda2…"/></label>
      <label className="adminField adminFieldWide"><span>Canonical model</span><select name="model" defaultValue={modelFilter}><option value="">ทุก model</option>{modelOptions.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>
      <label className="adminField"><span>แสดง attached แล้ว</span><select name="attached" defaultValue={showAttached ? "1" : "0"}><option value="0">ซ่อน</option><option value="1">แสดง</option></select></label>
      <label className="adminField"><span>แสดง reject/defer แล้ว</span><select name="reviewed" defaultValue={showReviewed ? "1" : "0"}><option value="0">ซ่อน</option><option value="1">แสดง</option></select></label>
      <div className="adminFormActions"><button className="adminPrimary">Apply filter</button></div>
    </form>

    <div className="adminHeader"><div><small>PRIORITY QUEUE</small><h2>{n(visible.length)} groups ตรง filter · แสดง {n(shown.length)}</h2><p>เรียงด้วยยอดจดทะเบียน 3 เดือนล่าสุดก่อน เพื่อปลด coverage ของตลาดจริงเร็วกว่าไล่ alphabet.</p></div></div>
    <div className="libraryTable"><table>
      <thead><tr><th>Market impact</th><th>Canonical target</th><th>ECO evidence</th><th>Current state</th><th>Human decision</th></tr></thead>
      <tbody>{shown.map((row) => <tr key={row.key}>
        <td className={styles.impactCell}><b>{n(row.registrations3m)}</b><br/><small>{Number(row.registrationSharePct || 0).toFixed(2)}% of mapped 3M · {row.priceBlocker}</small></td>
        <td className={styles.targetCell}><b>{row.brand} {row.modelName}</b><br/><small>{row.generationId} · {row.powertrain}</small></td>
        <td className={styles.evidenceCell}><b>{row.rawLabel}</b><br/><small>{row.sourceCount} ECO UUID{row.sourceCount === 1 ? "" : "s"} · ECO evidence price {money(row.ecoPriceMinThb, row.ecoPriceMaxThb)}</small><div>{row.sourceIds.slice(0,3).map((sourceId) => <div key={sourceId}><a href={`${ECO_DETAIL_ROOT}${sourceId}`} target="_blank" rel="noreferrer">{sourceId} ↗</a></div>)}{row.sourceIds.length > 3 ? <small>+{row.sourceIds.length - 3} more source UUIDs</small> : null}</div></td>
        <td>{row.attached ? <><b>ATTACHED</b><br/><small>อย่างน้อยหนึ่ง source UUID อยู่ใน canonical trim แล้ว</small></> : row.reviewDisposition ? <><b>{row.reviewDisposition.toUpperCase()}</b><br/><small>{row.reviewSummary || "HUMAN reviewed"}</small></> : <><b>{row.currentTrimCount} current trims</b><br/><small>{row.humanReviewedCount ? `${row.humanReviewedCount}/${row.sourceCount} source refs มี partial HUMAN decision` : row.existingTrimOptions.length ? `${row.existingTrimOptions.length} same-generation/powertrain trim candidates` : row.currentTrimCount ? "มี trim แต่ไม่มี candidate ที่ generation/powertrain ตรง" : "NO_MARKET_TRIM priority"}</small></>}</td>
        <td>{row.attached ? <span>ไม่เสนอ review ซ้ำ</span> : row.reviewDisposition ? <form action={enqueueEcoReviewDisposition} className={styles.reviewForm}>
          <input type="hidden" name="group_key" value={row.key}/>
          <input type="hidden" name="submission_id" value={randomUUID()}/>
          <input type="hidden" name="submitted_at" value={submittedAt}/>
          <input type="hidden" name="disposition" value="reopen"/>
          <label><span>เหตุผลที่ reopen</span><input name="reason" placeholder="พบ brochure ใหม่ / ตัดสิน disposition ผิด…" required/></label>
          <button className="adminPrimary">Reopen candidate</button>
        </form> : <div className={styles.decisionStack}>
          {row.existingTrimOptions.length ? <form action={enqueueEcoAttachExistingTrim} className={styles.reviewForm}>
            <input type="hidden" name="group_key" value={row.key}/>
            <input type="hidden" name="submission_id" value={randomUUID()}/>
            <input type="hidden" name="submitted_at" value={submittedAt}/>
            <label><span>Attach to existing trim</span><select name="target_trim_id" defaultValue="" required><option value="" disabled>เลือก canonical trim…</option>{row.existingTrimOptions.map((trim) => <option key={trim.canonicalId} value={trim.canonicalId}>{trim.name} · {trim.powertrain}{trim.sourceCount ? ` · ${trim.sourceCount} ECO refs` : ""}</option>)}</select></label>
            <label><span>Review note</span><input name="reason" placeholder="ยืนยันว่า ECO row คือ canonical grade นี้…" required/></label>
            <button className="adminPrimary">Attach evidence to existing</button>
          </form> : null}
          <form action={enqueueEcoMarketTrim} className={styles.reviewForm}>
            <input type="hidden" name="group_key" value={row.key}/>
            <input type="hidden" name="submission_id" value={randomUUID()}/>
            <input type="hidden" name="submitted_at" value={submittedAt}/>
            <label><span>Create new canonical trim name</span><input name="trim_name" placeholder="เช่น Premium / Max / Z Prestige" required/></label>
            <label><span>Review note</span><input name="reason" placeholder="ยืนยันว่าเป็น grade ใหม่จาก ECO detail / brochure…" required/></label>
            <button className="adminPrimary">Create + queue MarketTrim</button>
          </form>
          <form action={enqueueEcoReviewDisposition} className={styles.reviewForm}>
            <input type="hidden" name="group_key" value={row.key}/>
            <input type="hidden" name="submission_id" value={randomUUID()}/>
            <input type="hidden" name="submitted_at" value={submittedAt}/>
            <label><span>Disposition</span><select name="disposition" defaultValue="defer" required><option value="defer">DEFER · หลักฐานยังไม่พอ</option><option value="reject">REJECT · ไม่ใช่ retail MarketTrim</option></select></label>
            <label><span>Review note</span><input name="reason" placeholder="เหตุผลที่ defer/reject…" required/></label>
            <button className="adminPrimary">Queue disposition</button>
          </form>
        </div>}</td>
      </tr>)}</tbody>
    </table></div>

    {visible.length > shown.length ? <div className="adminNotice"><span>แสดง 80 groups แรกตาม market impact เพื่อกันหน้า admin หนักเกินไป. ใช้ search/model filter เพื่อเจาะกลุ่มถัดไป.</span></div> : null}
    <div className="adminQuickGrid"><Link href="/admin/vehicle-input"><b>Canonical input queue</b><span>ดู batch หลัง submit / staging PR</span></Link><Link href="/admin/prices/coverage"><b>Price coverage</b><span>ดู NO_MARKET_TRIM / MISSING_LIST_PRICE</span></Link><Link href="/admin/data-quality"><b>Parity gate</b><span>เช็ก retirement blockers</span></Link></div>
  </div>;
}
