"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { browserDb } from "@/lib/supabase-browser";
import { bodyLabel, cabLabel, retailStatusLabel } from "@/lib/body-labels";
import "./compare-slots.css";

type TrimOption = {
  id: string; model_id: string | null; brand_name: string | null; model_name: string | null;
  name: string | null; powertrain: string | null; price_baht: number | null;
};
type ModelOption = { id: string; brand: string; model: string };
type CompareRow = {
  key: string; label: string; different: boolean; values: (string | null)[];
  // Evidence-safe winner highlighting -- lib/compare-winners.ts decides all
  // three server-side; the page only ever reads them, never re-derives a
  // winner itself. comparable is false (and bestIndexes empty) for every
  // row the policy has not explicitly allowlisted, so old rows render
  // exactly as before.
  comparisonMode: "QUANTITATIVE_WINNER" | "PRESENCE_ADVANTAGE" | "NEUTRAL";
  comparable: boolean;
  bestIndexes: number[];
};
type CompareGroup = { title: string; rows: CompareRow[] };
type SelectedTrim = {
  id: string; brand_name: string | null; model_name: string | null; name: string | null;
  model_slug: string | null; image_url: string | null;
  retail_status: string | null; launch_year: number | string | null; launch_quarter: number | string | null;
};
type CompareResult = {
  selected: SelectedTrim[];
  missing_selection: boolean;
  groups: CompareGroup[];
  quota: { used: number; limit: number | null; remaining: number | null; resets_at: string };
  anonymous?: { remaining: number; limit: number };
};

const RETAIL_STATUS_BADGE_CLASS: Record<string, string> = {
  CURRENT: "compareStatusCurrent",
  HISTORICAL: "compareStatusHistorical",
  UNVERIFIED: "compareStatusUnverified",
};

function launchLabel(year: number | string | null, quarter: number | string | null) {
  if (!year) return null;
  return quarter ? `เปิดตัว Q${quarter} ${year}` : `เปิดตัว ${year}`;
}

function trimLabel(trim: TrimOption) {
  const bits = [trim.name || "รุ่นย่อย"];
  if (trim.powertrain) bits.push(trim.powertrain);
  if (trim.price_baht) bits.push(`฿${Math.round(trim.price_baht).toLocaleString("th-TH")}`);
  return bits.join(" · ");
}

function trimModelKey(trim: TrimOption) {
  return trim.model_id || `${trim.brand_name}:${trim.model_name}`;
}

export default function ComparePage() {
  const [models, setModels] = useState<ModelOption[]>([]);
  const [seedTrims, setSeedTrims] = useState<TrimOption[]>([]);
  const [trimsByModel, setTrimsByModel] = useState<Record<string, TrimOption[]>>({});
  const [trimLoadingModel, setTrimLoadingModel] = useState<string | null>(null);
  const [pickerError, setPickerError] = useState("");
  const [slots, setSlots] = useState<(string | null)[]>([null, null, null, null]);
  const [activeSlot, setActiveSlot] = useState<number | null>(null);
  const [query, setQuery] = useState("");
  const [modelId, setModelId] = useState("");
  const [pendingTrimId, setPendingTrimId] = useState("");
  const [diffOnly, setDiffOnly] = useState(false);
  const [token, setToken] = useState<string | null | undefined>(undefined);
  const [result, setResult] = useState<CompareResult | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "quota" | "signup" | "error">("idle");
  const [message, setMessage] = useState("");

  useEffect(() => {
    fetch("/api/compare/models")
      .then(async (response) => {
        const body = await response.json();
        if (!response.ok) throw new Error(body.error || "โหลดรุ่นรถไม่สำเร็จ");
        setModels(body.models || []);
      })
      .catch((error) => setPickerError(error instanceof Error ? error.message : "โหลดรุ่นรถไม่สำเร็จ"));

    const wanted = [...new Set(new URLSearchParams(window.location.search).getAll("trims").filter(Boolean))].slice(0, 4);
    if (wanted.length) {
      setSlots([wanted[0] || null, wanted[1] || null, wanted[2] || null, wanted[3] || null]);
      const params = new URLSearchParams();
      wanted.forEach((id) => params.append("ids", id));
      fetch(`/api/compare/trims?${params.toString()}`)
        .then(async (response) => {
          const body = await response.json();
          if (!response.ok) throw new Error(body.error || "โหลดรถที่เลือกไว้ไม่สำเร็จ");
          setSeedTrims(body.trims || []);
        })
        .catch((error) => setPickerError(error instanceof Error ? error.message : "โหลดรถที่เลือกไว้ไม่สำเร็จ"));
    }

    const db = browserDb();
    if (!db) { setToken(null); return; }
    db.auth.getSession().then(({ data }) => setToken(data.session?.access_token ?? null));
  }, []);

  const loadedTrims = useMemo(
    () => [...seedTrims, ...Object.values(trimsByModel).flat()],
    [seedTrims, trimsByModel],
  );
  const byId = useMemo(() => new Map(loadedTrims.map((trim) => [trim.id, trim])), [loadedTrims]);
  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return models;
    return models.filter((model) => `${model.brand} ${model.model}`.toLowerCase().includes(needle));
  }, [models, query]);
  const openTrims = modelId ? trimsByModel[modelId] : undefined;
  const chosen = useMemo(() => slots.filter((id): id is string => Boolean(id)), [slots]);
  const selectedCount = chosen.length;

  async function loadModelTrims(nextModelId: string) {
    if (!nextModelId || trimsByModel[nextModelId]) return;
    setTrimLoadingModel(nextModelId);
    setPickerError("");
    try {
      const response = await fetch(`/api/compare/trims?model_id=${encodeURIComponent(nextModelId)}`);
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || "โหลดรุ่นย่อยไม่สำเร็จ");
      setTrimsByModel((current) => ({ ...current, [nextModelId]: body.trims || [] }));
    } catch (error) {
      setPickerError(error instanceof Error ? error.message : "โหลดรุ่นย่อยไม่สำเร็จ");
    } finally {
      setTrimLoadingModel((current) => current === nextModelId ? null : current);
    }
  }

  function openPicker(index: number) {
    const currentId = slots[index];
    const currentTrim = currentId ? byId.get(currentId) : null;
    const currentModelId = currentTrim ? trimModelKey(currentTrim) : "";
    setActiveSlot(index);
    setQuery("");
    setModelId(currentModelId);
    setPendingTrimId(currentId || "");
    setPickerError("");
    if (currentModelId) void loadModelTrims(currentModelId);
  }

  function closePicker() {
    setActiveSlot(null);
    setQuery("");
    setModelId("");
    setPendingTrimId("");
    setPickerError("");
  }

  function chooseModel(nextModelId: string) {
    setModelId(nextModelId);
    setPendingTrimId("");
    setPickerError("");
    if (nextModelId) void loadModelTrims(nextModelId);
  }

  function confirmPicker() {
    if (activeSlot === null || !pendingTrimId) return;
    setSlots((current) => current.map((value, index) => index === activeSlot ? pendingTrimId : value));
    setResult(null);
    closePicker();
  }

  function removeSlot(index: number) {
    setSlots((current) => current.map((value, slotIndex) => slotIndex === index ? null : value));
    setResult(null);
    if (activeSlot === index) closePicker();
  }

  async function runCompare(event: React.FormEvent) {
    event.preventDefault();
    const ids = [...new Set(chosen)];
    if (ids.length < 2) return;
    setStatus("loading"); setMessage("");
    try {
      const params = new URLSearchParams();
      ids.forEach((id) => params.append("trims", id));
      if (diffOnly) params.set("diff", "1");
      const response = await fetch(`/api/tools/compare?${params.toString()}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        cache: "no-store",
      });
      const body = await response.json();
      if (!response.ok) throw Object.assign(new Error(body.error || "เทียบรถไม่สำเร็จ"), { status: response.status });
      setResult(body);
      setStatus("idle");
    } catch (error: any) {
      setStatus(error?.status === 429 ? "quota" : error?.status === 401 ? "signup" : "error");
      setMessage(error instanceof Error ? error.message : "เทียบรถไม่สำเร็จ");
    }
  }

  return <div className="comparePage">
    <section className="compareHero">
      <div>
        <div className="sfEyebrow">เปรียบเทียบสเปก</div>
        <h1>เทียบรถแบบตรงรุ่นย่อย</h1>
      </div>
      <Link href="/models">กลับไปดูแคตตาล็อก →</Link>
    </section>

    <form className="compareSlotForm" onSubmit={runCompare}>
      <div className="compareSlotsHead">
        <b>รถที่ต้องการเปรียบเทียบ</b>
        <span>เลือกได้สูงสุด 4 รุ่นย่อย · ต้องมีอย่างน้อย 2 คัน</span>
      </div>

      <div className="compareSlots" aria-label="รถที่เลือกไว้">
        {slots.map((id, index) => {
          const trim = id ? byId.get(id) : null;
          return (
            <article className={trim ? "compareSlot compareSlotFilled" : "compareSlot"} key={index}>
              {trim ? <>
                <span className="compareSlotNo">รถคันที่ {index + 1}</span>
                <strong>{[trim.brand_name, trim.model_name].filter(Boolean).join(" ")}</strong>
                <span>{trim.name || "รุ่นย่อย"}</span>
                <small>{trim.powertrain || ""}</small>
                <div className="compareSlotActions">
                  <button type="button" onClick={() => openPicker(index)}>เปลี่ยนรถ</button>
                  <button type="button" onClick={() => removeSlot(index)} aria-label={`เอารถคันที่ ${index + 1} ออก`}>ลบ</button>
                </div>
              </> : (
                <button type="button" className="compareSlotAdd" onClick={() => openPicker(index)}>
                  <i aria-hidden="true">+</i>
                  <b>เพิ่มรถคันที่ {index + 1}</b>
                  <small>เลือกรุ่นและรุ่นย่อย</small>
                </button>
              )}
            </article>
          );
        })}
      </div>

      {activeSlot !== null ? (
        <div className="compareSlotPicker">
          <div className="compareSlotPickerHead">
            <b>{slots[activeSlot] ? `เปลี่ยนรถคันที่ ${activeSlot + 1}` : `เพิ่มรถคันที่ ${activeSlot + 1}`}</b>
            <button type="button" onClick={closePicker} aria-label="ปิดตัวเลือกรถ">×</button>
          </div>

          <label className="compareSlotField">
            <span>เลือกรุ่น</span>
            <input type="search" value={query} placeholder="พิมพ์ชื่อแบรนด์หรือรุ่น"
                   onChange={(event) => { setQuery(event.target.value); setModelId(""); setPendingTrimId(""); setPickerError(""); }} />
            <select value={modelId} aria-label="รุ่นรถ" onChange={(event) => chooseModel(event.target.value)}>
              <option value="">{matches.length ? `เลือกจาก ${matches.length} รุ่น` : "ไม่พบรุ่นที่ค้นหา"}</option>
              {matches.map((model) => (
                <option key={model.id} value={model.id}>
                  {[model.brand, model.model].filter(Boolean).join(" ")}
                </option>
              ))}
            </select>
          </label>

          <div className="compareSlotField">
            <span>เลือกรุ่นย่อย</span>
            {!modelId ? <p className="comparePickHint">เลือกรุ่นก่อน แล้วรุ่นย่อยจะขึ้นตรงนี้</p>
              : trimLoadingModel === modelId ? <p className="comparePickHint">กำลังโหลดรุ่นย่อย…</p>
              : pickerError ? <p className="comparePickHint">{pickerError}</p>
              : openTrims ? (
                openTrims.length ? <div className="compareSlotTrimList">
                  {openTrims.map((trim) => {
                    const usedElsewhere = slots.some((slotId, slotIndex) => slotId === trim.id && slotIndex !== activeSlot);
                    return (
                      <button type="button" key={trim.id}
                              className={pendingTrimId === trim.id ? "compareSlotTrim on" : "compareSlotTrim"}
                              aria-pressed={pendingTrimId === trim.id}
                              disabled={usedElsewhere}
                              onClick={() => setPendingTrimId(trim.id)}>
                        {trimLabel(trim)}{usedElsewhere ? " · เลือกไว้แล้ว" : ""}
                      </button>
                    );
                  })}
                </div> : <p className="comparePickHint">ไม่พบรุ่นย่อย CURRENT ของรุ่นนี้</p>
              ) : <p className="comparePickHint">เลือกรุ่นก่อน แล้วรุ่นย่อยจะขึ้นตรงนี้</p>}
          </div>

          <div className="compareSlotPickerFoot">
            <button type="button" className="compareSlotCancel" onClick={closePicker}>ยกเลิก</button>
            <button type="button" className="compareSlotConfirm" disabled={!pendingTrimId} onClick={confirmPicker}>
              {slots[activeSlot] ? "บันทึกการเปลี่ยนรถ" : "เพิ่มรถคันนี้"}
            </button>
          </div>
        </div>
      ) : null}

      <div className="compareRunBar">
        <label className="compareDiffToggle">
          <input type="checkbox" checked={diffOnly} onChange={(event) => setDiffOnly(event.target.checked)} />
          <span>แสดงเฉพาะจุดที่ต่างกัน</span>
        </label>
        <button type="submit" disabled={selectedCount < 2 || status === "loading"}>
          {status === "loading" ? "กำลังเทียบ…" : `เทียบรถ${selectedCount ? ` (${selectedCount})` : ""}`}
        </button>
      </div>
      {token === null && result?.anonymous
        ? <p className="compareAnonHint">เทียบได้อีก {result.anonymous.remaining} ครั้งโดยไม่ต้องสมัคร · สมัครฟรีแล้วเทียบได้ไม่จำกัด</p>
        : null}
    </form>

    {status === "signup" ? (
      <div className="compareSignupWall">
        <b>{message}</b>
        <Link className="compareSignIn"
              href={`/member/login?next=${encodeURIComponent(`/compare?${chosen.map((id) => `trims=${encodeURIComponent(id)}`).join("&")}`)}`}>
          สมัครฟรี / เข้าสู่ระบบ
        </Link>
        <span>รถที่เลือกไว้จะยังอยู่หลังเข้าสู่ระบบ</span>
      </div>
    ) : null}
    {status === "quota" ? <div className="compareNotice">{message} — อัปเกรดบัญชีเพื่อเทียบรถไม่จำกัดต่อวัน <Link href="/pricing">ดูแพ็กเกจ</Link></div> : null}
    {status === "error" ? <div className="compareNotice">{message}</div> : null}
    {result?.missing_selection ? <div className="compareNotice">มีรุ่นที่เลือกไว้ซึ่งไม่อยู่ในฐานข้อมูลแล้ว ระบบจึงไม่นำมาเทียบ</div> : null}

    {result && result.selected.length >= 2 ? (
      <section className="compareTableWrap" aria-label="ตารางเปรียบเทียบรถ">
        {result.quota.limit !== null ? <p className="compareQuota">เทียบรถวันนี้: {result.quota.used}/{result.quota.limit}</p> : null}
        <table className="compareTable">
          <thead>
            <tr>
              <th>หัวข้อ</th>
              {result.selected.map((trim) => (
                <th key={trim.id}>
                  <div className={trim.image_url ? "compareCarShot" : "compareCarShot empty"}>
                    {trim.image_url
                      ? <img src={trim.image_url} alt={`${trim.brand_name || ""} ${trim.model_name || ""}`.trim()} />
                      : <span>{trim.model_name || "TDR"}</span>}
                  </div>
                  {trim.retail_status ? (
                    <span className={`compareStatusBadge ${RETAIL_STATUS_BADGE_CLASS[trim.retail_status] || ""}`}>
                      {retailStatusLabel(trim.retail_status)}
                    </span>
                  ) : null}
                  <small>{trim.brand_name}</small>
                  <strong>{trim.model_name}</strong>
                  <span>{trim.name}</span>
                  {launchLabel(trim.launch_year, trim.launch_quarter) ? (
                    <span className="compareLaunchMeta">{launchLabel(trim.launch_year, trim.launch_quarter)}</span>
                  ) : null}
                  {trim.model_slug ? <Link href={`/models/${trim.model_slug}`}>ดูหน้ารุ่น →</Link> : null}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {result.groups.map((group) => [
              <tr className="compareGroup" key={`${group.title}:head`}><th colSpan={result.selected.length + 1}>{group.title}</th></tr>,
              ...group.rows.map((row) => (
                <tr key={row.key} className={row.different ? "compareDifferent" : undefined}>
                  <th>{row.label}{row.different ? <em>ต่าง</em> : null}</th>
                  {row.values.map((value, index) => {
                    const displayValue = row.key === "body_type" && value ? bodyLabel(value)
                      : row.key === "cab_type" && value ? cabLabel(value)
                      : value;
                    // A winner is only ever painted for a row the server
                    // already marked comparable -- an incompatible-qualifier
                    // or missing-data row never reaches bestIndexes, so
                    // there is nothing here to double-check client-side.
                    const isWinner = row.comparable && row.bestIndexes.includes(index);
                    const cellClass = [
                      displayValue ? null : "compareMissing",
                      isWinner ? "compareWinnerCell" : null,
                    ].filter(Boolean).join(" ") || undefined;
                    return <td key={`${row.key}:${index}`} className={cellClass}>{displayValue || "—"}</td>;
                  })}
                </tr>
              )),
            ])}
          </tbody>
        </table>
      </section>
    ) : null}
  </div>;
}
