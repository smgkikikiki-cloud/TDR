"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { browserDb } from "@/lib/supabase-browser";
import { bodyLabel, cabLabel, retailStatusLabel } from "@/lib/body-labels";
import "./compare-design.css";

type TrimOption = {
  id: string; model_id: string | null; brand_name: string | null; model_name: string | null;
  name: string | null; powertrain: string | null; price_baht: number | string | null;
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

function displayPrice(price: number | string | null | undefined) {
  const amount = Number(price);
  return price != null && Number.isFinite(amount) && amount > 0
    ? `฿${Math.round(amount).toLocaleString("th-TH")}`
    : "ราคาไม่ระบุ";
}

function trimLabel(trim: TrimOption) {
  const bits = [trim.name || "ชื่อรุ่นย่อยไม่ระบุ", trim.powertrain || "ระบบขับเคลื่อนไม่ระบุ", displayPrice(trim.price_baht)];
  return bits.join(" · ");
}

function trimModelKey(trim: TrimOption) {
  return trim.model_id || `${trim.brand_name}:${trim.model_name}`;
}

function groupByModel(trims: TrimOption[]) {
  const grouped: Record<string, TrimOption[]> = {};
  for (const trim of trims) {
    const key = trimModelKey(trim);
    (grouped[key] ||= []).push(trim);
  }
  return grouped;
}

export default function ComparePage() {
  const [models, setModels] = useState<ModelOption[]>([]);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [modelsError, setModelsError] = useState("");
  const [seedTrims, setSeedTrims] = useState<TrimOption[]>([]);
  const [seedTrimsLoading, setSeedTrimsLoading] = useState(false);
  const [seedTrimsError, setSeedTrimsError] = useState("");
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
  const [authError, setAuthError] = useState("");
  const [result, setResult] = useState<CompareResult | null>(null);
  const [failedImages, setFailedImages] = useState<Record<string, boolean>>({});
  const [status, setStatus] = useState<"idle" | "loading" | "quota" | "signup" | "error">("idle");
  const [missingSelectionError, setMissingSelectionError] = useState(false);
  const [message, setMessage] = useState("");
  const [shareStatus, setShareStatus] = useState("");
  // Models handed over by the /models CompareTray (?models=<model id>). A model is not a trim, so nothing is chosen
  // for the reader: each queued model opens the picker on its own trim list and waits for an explicit choice.
  const [queuedModels, setQueuedModels] = useState<string[]>([]);

  async function loadModels() {
    setModelsLoading(true);
    setModelsError("");
    try {
      const response = await fetch("/api/compare/models");
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || "โหลดรุ่นรถไม่สำเร็จ");
      setModels(Array.isArray(body.models) ? body.models : []);
    } catch (error) {
      setModelsError(error instanceof Error ? error.message : "โหลดรุ่นรถไม่สำเร็จ");
    } finally {
      setModelsLoading(false);
    }
  }

  async function loadSeedTrims(ids: string[]) {
    if (!ids.length) return;
    setSeedTrimsLoading(true);
    setSeedTrimsError("");
    try {
      const params = new URLSearchParams();
      ids.forEach((id) => params.append("ids", id));
      const response = await fetch(`/api/compare/trims?${params.toString()}`);
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || "โหลดรถที่เลือกไว้ไม่สำเร็จ");
      setSeedTrims(Array.isArray(body.trims) ? body.trims : []);
    } catch (error) {
      setSeedTrimsError(error instanceof Error ? error.message : "โหลดรถที่เลือกไว้ไม่สำเร็จ");
    } finally {
      setSeedTrimsLoading(false);
    }
  }

  async function loadSession() {
    setAuthError("");
    setToken(undefined);
    const db = browserDb();
    if (!db) { setToken(null); return; }
    try {
      const { data, error } = await db.auth.getSession();
      if (error) throw error;
      setToken(data.session?.access_token ?? null);
    } catch {
      // Fail closed: a signed-in user must not accidentally fall through to
      // the anonymous allowance while their existing session is unreadable.
      setAuthError("ตรวจสอบสถานะบัญชีไม่สำเร็จ กรุณาลองอีกครั้ง");
    }
  }

  useEffect(() => {
    void loadModels();

    const wanted = [...new Set(new URLSearchParams(window.location.search).getAll("trims").filter(Boolean))].slice(0, 4);
    const wantedModels = [...new Set(new URLSearchParams(window.location.search).getAll("models").filter(Boolean))].slice(0, 4 - wanted.length);
    if (wantedModels.length) setQueuedModels(wantedModels);
    if (wanted.length) {
      setSlots([wanted[0] || null, wanted[1] || null, wanted[2] || null, wanted[3] || null]);
      void loadSeedTrims(wanted);
    }

    void loadSession();
  }, []);

  const loadedTrims = useMemo(
    () => [...seedTrims, ...Object.values(trimsByModel).flat()],
    [seedTrims, trimsByModel],
  );
  const seedTrimsByModel = useMemo(() => groupByModel(seedTrims), [seedTrims]);
  const byId = useMemo(() => new Map(loadedTrims.map((trim) => [trim.id, trim])), [loadedTrims]);
  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return models;
    return models.filter((model) => `${model.brand} ${model.model}`.toLowerCase().includes(needle));
  }, [models, query]);
  const openTrims = modelId ? (trimsByModel[modelId] ?? seedTrimsByModel[modelId]) : undefined;
  const chosen = useMemo(() => slots.filter((id): id is string => Boolean(id)), [slots]);
  const selectedCount = chosen.length;
  const authReady = token !== undefined;
  const shareHref = useMemo(() => {
    const params = new URLSearchParams();
    chosen.forEach((id) => params.append("trims", id));
    return "/compare?" + params.toString();
  }, [chosen]);

  async function copyShareLink() {
    if (selectedCount < 2) return;
    try {
      await navigator.clipboard.writeText(new URL(shareHref, window.location.origin).toString());
      setShareStatus("คัดลอกลิงก์แล้ว");
    } catch {
      setShareStatus("คัดลอกอัตโนมัติไม่ได้ กรุณาเปิดลิงก์แล้วคัดลอก URL จากแถบที่อยู่");
    }
  }

  async function loadModelTrims(nextModelId: string, force = false) {
    if (!nextModelId || (!force && trimsByModel[nextModelId])) return;
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
    if (status === "loading") return;
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
    setQueuedModels([]);
    setActiveSlot(null);
    setQuery("");
    setModelId("");
    setPendingTrimId("");
    setPickerError("");
  }

  /** Opens the picker for the next queued model in the first free slot, or ends the queue. */
  function openNextQueued(queue: string[], currentSlots: (string | null)[]) {
    const free = currentSlots.findIndex((value) => !value);
    if (!queue.length || free === -1) { setQueuedModels([]); return; }
    setActiveSlot(free);
    setQuery("");
    setModelId(queue[0]);
    setPendingTrimId("");
    setPickerError("");
    void loadModelTrims(queue[0]);
  }

  useEffect(() => {
    if (queuedModels.length && activeSlot === null) openNextQueued(queuedModels, slots);
    // Runs once when the queue is first filled from the URL; later steps are driven by confirm/close below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queuedModels.length > 0]);

  function chooseModel(nextModelId: string) {
    setModelId(nextModelId);
    setPendingTrimId("");
    setPickerError("");
    if (nextModelId) void loadModelTrims(nextModelId);
  }

  function confirmPicker() {
    if (activeSlot === null || !pendingTrimId) return;
    const nextSlots = slots.map((value, index) => index === activeSlot ? pendingTrimId : value);
    setSlots(nextSlots);
    clearComparisonResult();
    const rest = queuedModels.slice(1);
    closePicker();
    if (rest.length) { setQueuedModels(rest); openNextQueued(rest, nextSlots); }
  }

  function removeSlot(index: number) {
    setSlots((current) => current.map((value, slotIndex) => slotIndex === index ? null : value));
    clearComparisonResult();
    if (activeSlot === index) closePicker();
  }

  function clearComparisonResult() {
    setResult(null);
    setStatus("idle");
    setMessage("");
    setMissingSelectionError(false);
    setShareStatus("");
  }

  async function runCompare(event?: React.FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    if (!authReady) return;
    const ids = [...new Set(chosen)];
    if (ids.length < 2) return;
    setStatus("loading"); setMessage(""); setMissingSelectionError(false);
    try {
      const params = new URLSearchParams();
      ids.forEach((id) => params.append("trims", id));
      if (diffOnly) params.set("diff", "1");
      const response = await fetch(`/api/tools/compare?${params.toString()}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        cache: "no-store",
      });
      const body = await response.json();
      if (!response.ok) throw Object.assign(new Error(body.error || "เทียบรถไม่สำเร็จ"), {
        status: response.status,
        missingSelection: body.missing_selection === true,
      });
      setResult(body);
      setStatus("idle");
    } catch (error: any) {
      setStatus(error?.status === 429 ? "quota" : error?.status === 401 ? "signup" : "error");
      setMissingSelectionError(error?.missingSelection === true);
      setMessage(error instanceof Error ? error.message : "เทียบรถไม่สำเร็จ");
    }
  }

  return <div className="designPage comparePage compareDesignPage">
    <section className="compareHero">
      <div className="compareHeroCopy">
        <div className="tdr-eyebrow" lang="en">VEHICLE DATABASE / COMPARE SPECS</div>
        <h1>เทียบรถให้เห็น<span className="compareHeroAccent">ทุกความต่าง</span></h1>
        <p>เลือกรุ่นย่อยแล้วอ่านสเปกเคียงข้างกันสูงสุด 4 คัน ผลที่เด่นกว่าจะแสดงเฉพาะหัวข้อที่ข้อมูลเปรียบเทียบกันได้จริง</p>
        <Link className="compareCatalogLink" href="/models">ค้นหารถจากแคตตาล็อก <span aria-hidden="true">↗</span></Link>
      </div>
      <aside className="compareHeroAside" aria-label="ขั้นตอนการเปรียบเทียบ">
        <span>HOW TO COMPARE</span>
        <ol>
          <li><b>01</b> เลือกรุ่นรถและรุ่นย่อยอย่างน้อย 2 คัน</li>
          <li><b>02</b> กดเทียบรถเพื่อดูข้อมูลจริงจาก TDR</li>
          <li><b>03</b> ดูความแตกต่าง แล้วแชร์ลิงก์รายการที่เลือก</li>
        </ol>
      </aside>
    </section>
    <div className="compareSectionHeader">
      <div><span className="tdr-eyebrow">STEP 01 / เลือกรถ</span><h2>เลือกรุ่นย่อยที่ต้องการเทียบ</h2></div>
      <p>เลือกให้ตรงรุ่นย่อย ไม่ยืมสเปกจากรถคันอื่น</p>
    </div>

    <form className="compareSlotForm" onSubmit={runCompare}>
      <div className="compareSlotsHead">
        <b>รายการที่เลือก <span className="compareSelectedNumber">{selectedCount}/4</span></b>
        <span>สูงสุด 4 รุ่นย่อย · ขั้นต่ำ 2 คัน</span>
      </div>

      {seedTrimsError ? (
        <div className="compareInlineError" role="alert">
          <span>{seedTrimsError}</span>
          <button type="button" className="compareRetryButton" onClick={() => void loadSeedTrims(chosen)}>ลองโหลดอีกครั้ง</button>
        </div>
      ) : null}

      <section className="compareSlots" role="group" aria-label="รถที่เลือกไว้">
        {slots.map((id, index) => {
          const trim = id ? byId.get(id) : null;
          return (
            <article className={trim ? "compareSlot compareSlotFilled" : "compareSlot"} key={index}>
              {trim ? <>
                <span className="compareSlotNo">รถคันที่ {index + 1}</span>
                <strong>{[trim.brand_name, trim.model_name].filter(Boolean).join(" ")}</strong>
                <span>{trim.name || "ชื่อรุ่นย่อยไม่ระบุ"}</span>
                <small>{trim.powertrain || "ระบบขับเคลื่อนไม่ระบุ"}</small>
                <span className={`compareSlotPrice${displayPrice(trim.price_baht) === "ราคาไม่ระบุ" ? " compareSlotPriceMissing" : ""}`}>{displayPrice(trim.price_baht)}</span>
                <div className="compareSlotActions">
                  <button type="button" disabled={status === "loading"} onClick={() => openPicker(index)}>เปลี่ยนรถ</button>
                  <button type="button" disabled={status === "loading"} onClick={() => removeSlot(index)} aria-label={`เอารถคันที่ ${index + 1} ออก`}>ลบ</button>
                </div>
              </> : (
                id && seedTrimsLoading ? (
                  <div className="compareSlotLoading" role="status"><span className="compareSrOnly">กำลังโหลดรถที่แชร์มา…</span><i /><i /><i /></div>
                ) : id ? (
                  <div className="compareSlotMissing">
                    <span>รุ่นย่อยนี้ไม่อยู่ในแคตตาล็อกหรือไม่มีข้อมูลให้โหลด</span>
                    <div>
                      <button type="button" disabled={status === "loading"} onClick={() => openPicker(index)}>เลือกใหม่</button>
                      <button type="button" disabled={status === "loading"} onClick={() => removeSlot(index)} aria-label={`เอารถคันที่ ${index + 1} ที่หาไม่พบออก`}>เอาออก</button>
                    </div>
                  </div>
                ) : (
                  <button type="button" className="compareSlotAdd" disabled={status === "loading"} onClick={() => openPicker(index)}>
                    <i aria-hidden="true">+</i>
                    <b>เพิ่มรถคันที่ {index + 1}</b>
                    <small>เลือกรุ่นและรุ่นย่อย</small>
                  </button>
                )
              )}
            </article>
          );
        })}
      </section>

      {activeSlot !== null ? (
        <div className="compareSlotPicker" role="region" aria-label="ตัวเลือกรุ่นรถและรุ่นย่อย" onKeyDown={(event) => { if (event.key === "Escape") closePicker(); }}>
          <div className="compareSlotPickerHead">
            <b>{slots[activeSlot] ? `เปลี่ยนรถคันที่ ${activeSlot + 1}` : `เพิ่มรถคันที่ ${activeSlot + 1}`}</b>
            <button type="button" disabled={status === "loading"} onClick={closePicker} aria-label="ปิดตัวเลือกรถ">×</button>
          </div>

          <div className="compareSlotField">
            <label htmlFor="compare-model-search">ค้นหาแบรนด์หรือรุ่น</label>
            <input id="compare-model-search" type="search" value={query} placeholder="พิมพ์ชื่อแบรนด์หรือรุ่น"
                   disabled={modelsLoading || status === "loading"} autoFocus
                   onChange={(event) => { setQuery(event.target.value); setModelId(""); setPendingTrimId(""); setPickerError(""); }} />
            <label htmlFor="compare-model-select">เลือกรุ่นรถ</label>
            <select id="compare-model-select" value={modelId} disabled={modelsLoading || !models.length || status === "loading"} onChange={(event) => chooseModel(event.target.value)}>
              <option value="">
                {modelsLoading ? "กำลังโหลดรุ่นรถ…" : modelsError ? "โหลดรุ่นรถไม่สำเร็จ" : matches.length ? `เลือกจาก ${matches.length} รุ่น` : "ไม่พบรุ่นที่ค้นหา"}
              </option>
              {matches.map((model) => (
                <option key={model.id} value={model.id}>
                  {[model.brand, model.model].filter(Boolean).join(" ")}
                </option>
              ))}
            </select>
            {modelsError ? <div className="compareInlineError" role="alert"><span>{modelsError}</span><button type="button" className="compareRetryButton" disabled={modelsLoading} onClick={() => void loadModels()}>โหลดรุ่นรถอีกครั้ง</button></div> : null}
            {!modelsLoading && !modelsError && !models.length ? <p className="comparePickHint" role="status">ยังไม่มีรุ่นรถพร้อมให้เปรียบเทียบ</p> : null}
            {!modelsLoading && !modelsError && models.length > 0 && query.trim() && matches.length === 0 ? <p className="comparePickHint" role="status">ไม่พบรุ่นที่ตรงกับคำค้นนี้</p> : null}
          </div>

          <div className="compareSlotField">
            <span>เลือกรุ่นย่อย</span>
            {!modelId ? <p className="comparePickHint" role="status">เลือกรุ่นก่อน แล้วรุ่นย่อยจะขึ้นตรงนี้</p>
              : trimLoadingModel === modelId ? <div className="comparePickerSkeleton" role="status" aria-live="polite"><span className="compareSrOnly">กำลังโหลดรุ่นย่อย…</span><i /><i /><i /></div>
              : pickerError ? <div className="compareInlineError" role="alert"><span>{pickerError}</span><button type="button" className="compareRetryButton" disabled={status === "loading"} onClick={() => void loadModelTrims(modelId, true)}>ลองโหลดรุ่นย่อยอีกครั้ง</button></div>
              : openTrims ? (
                openTrims.length ? <div className="compareSlotTrimList">
                  {openTrims.map((trim) => {
                    const usedElsewhere = slots.some((slotId, slotIndex) => slotId === trim.id && slotIndex !== activeSlot);
                    return (
                      <button type="button" key={trim.id}
                              className={pendingTrimId === trim.id ? "compareSlotTrim on" : "compareSlotTrim"}
                              aria-pressed={pendingTrimId === trim.id}
                              disabled={usedElsewhere || status === "loading"}
                              onClick={() => setPendingTrimId(trim.id)}>
                        {trimLabel(trim)}{usedElsewhere ? " · เลือกไว้แล้ว" : ""}
                      </button>
                    );
                  })}
                </div> : <p className="comparePickHint" role="status">ไม่พบรุ่นย่อย CURRENT ของรุ่นนี้</p>
              ) : <p className="comparePickHint" role="status">เลือกรุ่นก่อน แล้วรุ่นย่อยจะขึ้นตรงนี้</p>}
          </div>

          <div className="compareSlotPickerFoot">
            <button type="button" className="compareSlotCancel" disabled={status === "loading"} onClick={closePicker}>ยกเลิก</button>
            <button type="button" className="compareSlotConfirm" disabled={!pendingTrimId || status === "loading"} onClick={confirmPicker}>
              {slots[activeSlot] ? "บันทึกการเปลี่ยนรถ" : "เพิ่มรถคันนี้"}
            </button>
          </div>
        </div>
      ) : null}

      <div className="compareRunBar">
        <label className="compareDiffToggle">
          <input type="checkbox" checked={diffOnly} disabled={status === "loading"} onChange={(event) => { setDiffOnly(event.target.checked); clearComparisonResult(); }} />
          <span>แสดงเฉพาะจุดที่ต่างกัน</span>
        </label>
        <button type="submit" aria-busy={!authReady || status === "loading"} disabled={selectedCount < 2 || !authReady || status === "loading" || activeSlot !== null}>
          {status === "loading" ? "กำลังเทียบ…" : `เทียบรถ${selectedCount ? ` (${selectedCount})` : ""}`}
        </button>
      </div>
      {!authReady && !authError ? <p className="compareInlineStatus" role="status" aria-live="polite">กำลังตรวจสอบสถานะบัญชี…</p> : null}
      {authError ? <div className="compareInlineError" role="alert"><span>{authError}</span><button type="button" className="compareRetryButton" onClick={() => void loadSession()}>ตรวจสอบบัญชีอีกครั้ง</button></div> : null}
      {result?.anonymous
        ? <p className="compareAnonHint" role="status">เหลือ <b>{result.anonymous.remaining}/{result.anonymous.limit}</b> ครั้งวันนี้ · <Link href="/member/login">สมัครฟรีเพื่อเทียบได้ไม่จำกัด</Link></p>
        : null}
      {selectedCount >= 2 ? (
        <section className="compareShareBar" aria-label="ลิงก์สำหรับแชร์รายการรถที่เลือก">
          <span>แชร์รายการรถที่เลือกไว้</span>
          <div>
            <Link href={shareHref}>เปิดลิงก์รายการที่เลือก ↗</Link>
            <button type="button" onClick={() => void copyShareLink()}>คัดลอกลิงก์</button>
          </div>
          {shareStatus ? <p role="status">{shareStatus}</p> : null}
        </section>
      ) : null}
    </form>

    {status === "signup" ? (
      <div className="compareSignupWall" role="alert">
        <b>{message}</b>
        <Link className="compareSignIn"
              href={`/member/login?next=${encodeURIComponent(shareHref)}`}>
          สมัครฟรี / เข้าสู่ระบบ
        </Link>
        <span>รถที่เลือกไว้จะยังอยู่หลังเข้าสู่ระบบ</span>
      </div>
    ) : null}
    {status === "quota" ? <div className="compareNotice" role="alert">{message} — อัปเกรดบัญชีเพื่อเทียบรถไม่จำกัดต่อวัน <Link href="/pricing">ดูแพ็กเกจ</Link></div> : null}
    {status === "error" ? <div className="compareNotice" role="alert"><span>{message}</span>{missingSelectionError
      ? <button type="button" className="compareRetryButton" onClick={() => {
        const missingIndex = slots.findIndex((id) => id && !byId.has(id));
        openPicker(missingIndex >= 0 ? missingIndex : 0);
      }}>เลือกแทนรุ่นย่อยที่หาไม่พบ</button>
      : <button type="button" className="compareRetryButton" onClick={() => void runCompare()}>ลองเปรียบเทียบอีกครั้ง</button>}</div> : null}
    {result?.missing_selection ? <div className="compareNotice" role="alert">มีรุ่นที่เลือกไว้ซึ่งไม่อยู่ในฐานข้อมูลแล้ว ระบบจึงไม่นำมาเทียบ</div> : null}
    {result && result.selected.length < 2 ? (
      <div className="compareEmptyResult" role="status">
        <h2>ยังเทียบรถชุดนี้ไม่ได้</h2>
        <p>ต้องมีรุ่นย่อยที่ยังอยู่ในฐานข้อมูลอย่างน้อย 2 คัน ระบบไม่นับรุ่นที่หาไม่พบ และไม่ได้ใช้สิทธิ์เทียบสำหรับรายการที่ไม่ครบ</p>
        <button type="button" className="compareRetryButton" onClick={() => {
          const missingIndex = slots.findIndex((id) => id && !result.selected.some((trim) => trim.id === id));
          openPicker(missingIndex >= 0 ? missingIndex : 0);
        }}>เลือกหรือเปลี่ยนรุ่นย่อย</button>
      </div>
    ) : null}

    {status === "loading" && !result ? (
      <section className="compareLoadingState" aria-live="polite">
        <span className="tdr-eyebrow">STEP 02 / ผลการเปรียบเทียบ</span>
        <h2>กำลังตรวจสอบสเปกที่เลือก</h2>
        <div className="compareLoadingBars" aria-hidden="true"><i /><i /><i /></div>
      </section>
    ) : null}
    {!result && status === "idle" ? (
      <section className="compareAwaitingResult">
        <span className="tdr-eyebrow">STEP 02 / ผลการเปรียบเทียบ</span>
        <h2>ตารางสเปกจะปรากฏตรงนี้</h2>
        <p>เลือกอย่างน้อยสองรุ่นย่อยแล้วกด “เทียบรถ” เพื่อดูความแตกต่าง ข้อมูลที่ยังไม่ยืนยันจะแสดงเป็น “—” ไม่ประมาณค่าแทน</p>
      </section>
    ) : null}
    {result && result.selected.length >= 2 ? (
      <section className="compareResultSection" aria-label="ผลการเปรียบเทียบรถ" aria-live="polite">
        <div className="compareResultIntro">
          <div><span className="tdr-eyebrow">STEP 02 / ผลการเปรียบเทียบ</span>
            <h2>สเปกเคียงข้างกัน <span className="compareResultCount">{result.selected.length} คัน</span></h2>
            <p>เครื่องหมาย ✓ แสดงเฉพาะค่าที่ดีที่สุดตามเกณฑ์เปรียบเทียบและข้อมูลที่ใช้วัดได้จริง อาจมีผลเสมอกัน</p>
          </div>
          {result.quota.limit !== null ? <p className="compareQuota">ใช้สิทธิ์เทียบรถวันนี้ {result.quota.used}/{result.quota.limit}</p> : null}
        </div>
        {result.groups.length ? <div className="compareTableWrap" role="region" tabIndex={0} aria-label="ตารางเปรียบเทียบ เลื่อนแนวนอนเพื่อดูรถคันอื่น">
        <table className="compareTable">
          <caption className="compareSrOnly">ตารางเปรียบเทียบข้อมูลรถที่เลือกไว้ {result.selected.length} คัน</caption>
          <thead>
            <tr>
              <th scope="col">หัวข้อ</th>
              {result.selected.map((trim) => (
                <th key={trim.id} scope="col">
                  <div className={trim.image_url && !failedImages[trim.id] ? "compareCarShot" : "compareCarShot empty"}>
                    {trim.image_url && !failedImages[trim.id]
                      ? <img src={trim.image_url} alt={`${trim.brand_name || ""} ${trim.model_name || ""}`.trim()} onError={() => setFailedImages((current) => ({ ...current, [trim.id]: true }))} />
                      : <span>ภาพรถไม่พร้อมใช้งาน</span>}
                  </div>
                  <span className={`compareStatusBadge ${RETAIL_STATUS_BADGE_CLASS[trim.retail_status || ""] || "compareStatusUnknown"}`}>
                    {retailStatusLabel(trim.retail_status) || "ไม่ระบุสถานะการจำหน่าย"}
                  </span>
                  <small>{trim.brand_name || "ไม่ระบุแบรนด์"}</small>
                  <strong>{trim.model_name || "ไม่ระบุรุ่น"}</strong>
                  <span>{trim.name || "ชื่อรุ่นย่อยไม่ระบุ"}</span>
                  <span className="compareHeaderPrice">{displayPrice(byId.get(trim.id)?.price_baht)}</span>
                  {launchLabel(trim.launch_year, trim.launch_quarter) ? (
                    <span className="compareLaunchMeta">{launchLabel(trim.launch_year, trim.launch_quarter)}</span>
                  ) : null}
                  {trim.model_slug ? <Link href={`/models/${trim.model_slug}`}>ดูหน้ารุ่น →</Link> : null}
                  <button type="button" className="compareHeaderRemove"
                    disabled={status === "loading"}
                    onClick={() => { const index = slots.findIndex((id) => id === trim.id); if (index >= 0) removeSlot(index); }}
                    aria-label={`นำ ${trim.brand_name || ""} ${trim.model_name || ""} ${trim.name || ""} ออกจากรายการ`}>นำออก ×</button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {result.groups.map((group) => [
              <tr className="compareGroup" key={`${group.title}:head`}><th scope="rowgroup" colSpan={result.selected.length + 1}>{group.title}</th></tr>,
              ...group.rows.map((row) => (
                <tr key={row.key} className={row.different ? "compareDifferent" : undefined}>
                  <th scope="row">{row.label}{row.different ? <em>ต่าง</em> : null}</th>
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
                    return <td key={`${row.key}:${index}`} className={cellClass}>
                      <span>{displayValue || "—"}</span>
                      {isWinner ? <span className="compareWinnerMark"><span aria-hidden="true">✓</span> เด่น</span> : null}
                    </td>;
                  })}
                </tr>
              )),
            ])}
          </tbody>
        </table>
        </div> : <div className="compareEmptyResult" role="status">
          <h2>{diffOnly ? "ไม่มีหัวข้อที่แตกต่างกัน" : "ยังไม่มีข้อมูลสเปกที่เปรียบเทียบได้"}</h2>
          <p>{diffOnly ? "ไม่มีหัวข้อที่ระบบเปรียบเทียบได้จริงและพบความแตกต่างในรถชุดนี้" : "ข้อมูลสเปกที่ยืนยันได้ยังไม่เพียงพอสำหรับรถชุดนี้ ลองเลือกรุ่นย่อยอื่น"}</p>
        </div>}
        <p className="compareResultSource">ที่มา: ฐานข้อมูลรถยนต์ TDR · การเปรียบเทียบอิงข้อมูลรุ่นย่อยและเงื่อนไขสเปกเดียวกัน · “—” หมายถึงไม่มีข้อมูลที่ยืนยันได้</p>
      </section>
    ) : null}
  </div>;
}
