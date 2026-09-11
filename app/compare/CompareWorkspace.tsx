"use client";

import Link from "next/link";
import { useMemo, useRef, useState, type CSSProperties } from "react";
import { useRouter } from "next/navigation";
import { compareValue, type FreeCompareTrim } from "@/lib/free-compare";
import {
  QUICK_COMPARE_ROWS,
  WORKSPACE_COMPARE_SECTIONS,
  factsByTrim,
  rowCell,
  rowHasAnyKnown,
  workspaceRowIsDifferent,
  type CompareSpecFact,
  type WorkspaceCompareRow,
} from "@/lib/compare-workspace";

const MAX_CARS = 4;

type Slot = { modelId: string; trimId: string };
type ModelChoice = { id: string; label: string; imageUrl: string | null };

type Props = {
  allTrims: FreeCompareTrim[];
  initialTrimIds: string[];
  initialModelIds: string[];
  facts: CompareSpecFact[];
  initialDiffOnly: boolean;
  missingTrimSelection?: boolean;
  missingModelSelection?: boolean;
};

function trimLabel(trim: FreeCompareTrim) {
  return [trim.name, trim.powertrain].filter(Boolean).join(" · ");
}

function modelLabel(trim: FreeCompareTrim) {
  return [trim.brand_name, trim.model_name].filter(Boolean).join(" ");
}

function initialSlots(all: FreeCompareTrim[], models: string[], trims: string[]): Slot[] {
  const byId = new Map(all.map((trim) => [trim.id, trim]));
  const selected = trims.map((id) => byId.get(id)).filter(Boolean) as FreeCompareTrim[];
  const used = new Set<string>();
  const slots: Slot[] = models.slice(0, MAX_CARS).map((modelId) => {
    const match = selected.find((trim) => trim.model_id === modelId && !used.has(trim.id));
    if (match) used.add(match.id);
    return { modelId, trimId: match?.id || "" };
  });
  for (const trim of selected) {
    if (used.has(trim.id) || slots.length >= MAX_CARS) continue;
    slots.push({ modelId: trim.model_id || "", trimId: trim.id });
    used.add(trim.id);
  }
  while (slots.length < 2) slots.push({ modelId: "", trimId: "" });
  return slots;
}

function ModelPicker({ slotIndex, choices, value, onChange }: {
  slotIndex: number;
  choices: ModelChoice[];
  value: string;
  onChange: (id: string) => void;
}) {
  const [query, setQuery] = useState("");
  const details = useRef<HTMLDetailsElement>(null);
  const selected = choices.find((choice) => choice.id === value);
  const filtered = query.trim()
    ? choices.filter((choice) => choice.label.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())).slice(0, 16)
    : choices.slice(0, 16);
  return <details className="compareModelPicker" ref={details}>
    <summary>{selected?.label || `เลือกรถคันที่ ${slotIndex + 1}`}</summary>
    <div className="compareModelPopover">
      <input autoFocus={false} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="ค้นหาแบรนด์หรือรุ่น เช่น Camry, BYD, HR-V" />
      <div className="compareModelChoices">
        {filtered.map((choice) => <button type="button" key={choice.id} className={choice.id === value ? "on" : undefined} onClick={() => {
          onChange(choice.id);
          setQuery("");
          if (details.current) details.current.open = false;
        }}>{choice.label}</button>)}
        {!filtered.length ? <span>ไม่พบรุ่นที่ค้นหา</span> : null}
      </div>
    </div>
  </details>;
}

function displayCoreBody(value: string | null) {
  const map: Record<string, string> = { CROSSOVER: "Crossover / SUV", SEDAN: "Sedan", HATCHBACK: "Hatchback", PICKUP: "Pickup", PPV: "PPV", MPV: "MPV", VAN: "Van" };
  return value ? map[value] || value : null;
}

function displayCell(trim: FreeCompareTrim, row: WorkspaceCompareRow, factMap: ReturnType<typeof factsByTrim>) {
  const cell = rowCell(trim, row, factMap);
  if (row.source === "core" && row.key === "body_type") return { ...cell, display: displayCoreBody(cell.display) };
  return cell;
}

export function CompareWorkspace({ allTrims, initialTrimIds, initialModelIds, facts, initialDiffOnly, missingTrimSelection, missingModelSelection }: Props) {
  const router = useRouter();
  const [slots, setSlots] = useState<Slot[]>(() => initialSlots(allTrims, initialModelIds, initialTrimIds));
  const [diffOnly, setDiffOnly] = useState(initialDiffOnly);
  const [pickerNonce, setPickerNonce] = useState(0);
  const byId = useMemo(() => new Map(allTrims.map((trim) => [trim.id, trim])), [allTrims]);
  const modelChoices = useMemo(() => {
    const map = new Map<string, ModelChoice>();
    for (const trim of allTrims) {
      if (!trim.model_id || map.has(trim.model_id)) continue;
      map.set(trim.model_id, { id: trim.model_id, label: modelLabel(trim), imageUrl: (trim as any).model_image_url || null });
    }
    return [...map.values()].sort((a, b) => a.label.localeCompare(b.label));
  }, [allTrims]);
  const factMap = useMemo(() => factsByTrim(facts), [facts]);
  const selected = slots.map((slot) => byId.get(slot.trimId)).filter(Boolean) as FreeCompareTrim[];

  function sync(next: Slot[], nextDiff = diffOnly) {
    const params = new URLSearchParams();
    next.forEach((slot) => { if (slot.modelId) params.append("models", slot.modelId); });
    next.forEach((slot) => { if (slot.trimId) params.append("trims", slot.trimId); });
    if (nextDiff) params.set("diff", "1");
    router.replace(`/compare${params.size ? `?${params.toString()}` : ""}`, { scroll: false });
  }

  function updateSlot(index: number, patch: Partial<Slot>) {
    const next = slots.map((slot, i) => i === index ? { ...slot, ...patch } : slot);
    setSlots(next);
    sync(next);
  }

  function chooseModel(index: number, modelId: string) {
    updateSlot(index, { modelId, trimId: "" });
  }

  function chooseTrim(index: number, trimId: string) {
    const trim = byId.get(trimId);
    updateSlot(index, { trimId, modelId: trim?.model_id || slots[index].modelId });
  }

  function removeSlot(index: number) {
    const next = slots.filter((_, i) => i !== index);
    while (next.length < 2) next.push({ modelId: "", trimId: "" });
    setSlots(next);
    sync(next);
  }

  function addSlot() {
    if (slots.length >= MAX_CARS) return;
    setSlots([...slots, { modelId: "", trimId: "" }]);
  }

  function toggleDiff(value: boolean) {
    setDiffOnly(value);
    sync(slots, value);
  }

  const matrixStyle = { "--compare-cars": selected.length } as CSSProperties;
  const quickRows = QUICK_COMPARE_ROWS.filter((row) => rowHasAnyKnown(selected, row, factMap));
  const sections = WORKSPACE_COMPARE_SECTIONS.map((section) => ({
    ...section,
    rows: section.rows.filter((row) => rowHasAnyKnown(selected, row, factMap) && (!diffOnly || workspaceRowIsDifferent(selected, row, factMap))),
  }));

  return <>
    <section className="compareHero compareHeroV2">
      <div>
        <div className="sfEyebrow">FREE VEHICLE COMPARE</div>
        <h1>เทียบรถให้เห็นความต่างจริง</h1>
        <p>เลือก Trim จริง 2–4 คัน แล้วดูราคา สเปก หน้าจอ อุปกรณ์ความปลอดภัย และ ADAS จาก canonical Vehicle Master ชุดเดียวกัน — ระบบไม่เดารุ่นย่อยหรือเติมข้อมูลที่ยังไม่ยืนยัน</p>
      </div>
      <Link href="/models">← เลือกจากแคตตาล็อก</Link>
    </section>

    {(missingTrimSelection || missingModelSelection) ? <div className="compareNotice">
      {missingTrimSelection ? "มี Trim ที่เลือกไว้ซึ่งไม่อยู่ใน active canonical release แล้ว ระบบจึงถอดออกจากการเทียบ " : ""}
      {missingModelSelection ? "มี Model ที่ยังไม่มี Trim สำหรับ Free Compare จึงเปิดช่องนั้นให้เลือกใหม่ได้ " : ""}
    </div> : null}

    <section className="compareSlots" key={pickerNonce}>
      <div className="compareSlotsHead"><div><b>เลือกรถและรุ่นย่อย</b><span>ต้องเลือก Trim จริงก่อน ระบบจะไม่เลือกตัวแทนให้เอง</span></div><span>{selected.length} / {MAX_CARS} คันพร้อมเทียบ</span></div>
      <div className="compareSlotGrid">
        {slots.map((slot, index) => {
          const options = slot.modelId ? allTrims.filter((trim) => trim.model_id === slot.modelId) : [];
          const selectedTrim = byId.get(slot.trimId);
          const choice = modelChoices.find((model) => model.id === slot.modelId);
          return <article className={`compareSlot ${selectedTrim ? "ready" : ""}`} key={`${index}:${slot.modelId}`}>
            <div className="compareSlotNo">คันที่ {index + 1}{index < 2 ? " · ต้องเลือก" : ""}</div>
            {choice?.imageUrl ? <img className="compareSlotImage" src={choice.imageUrl} alt="" /> : <div className="compareSlotImage placeholder">TDR</div>}
            <ModelPicker slotIndex={index} choices={modelChoices} value={slot.modelId} onChange={(id) => chooseModel(index, id)} />
            <select className="compareTrimSelect" value={slot.trimId} disabled={!slot.modelId} onChange={(event) => chooseTrim(index, event.target.value)}>
              <option value="">{slot.modelId ? "เลือกรุ่นย่อย / Trim" : "เลือกรถก่อน"}</option>
              {options.map((trim) => <option key={trim.id} value={trim.id}>{trimLabel(trim)}</option>)}
            </select>
            {selectedTrim ? <div className="compareSlotPrice">{compareValue(selectedTrim, "price") || "ราคาปัจจุบันยังไม่ยืนยัน"}</div> : <div className="compareSlotHint">เลือก Model แล้วเลือก Trim ที่ต้องการเทียบ</div>}
            {(slots.length > 2 || slot.modelId) ? <button className="compareSlotRemove" type="button" onClick={() => removeSlot(index)}>×</button> : null}
          </article>;
        })}
        {slots.length < MAX_CARS ? <button className="compareAddSlot" type="button" onClick={addSlot}><b>＋</b><span>เพิ่มรถอีกคัน</span></button> : null}
      </div>
    </section>

    {selected.length < 2 ? <section className="compareEmpty compareEmptyV2"><b>เลือกอย่างน้อย 2 Trim เพื่อเริ่มเปรียบเทียบ</b><span>ถ้ามาจากแคตตาล็อก Model จะถูกเลือกไว้ให้แล้ว เหลือแค่เลือก Trim จริงของแต่ละคัน</span></section> : <>
      <div className="compareCommandBar">
        <div><b>เปรียบเทียบ {selected.length} คัน</b><span>แถว “—” = ยังไม่มีข้อมูลที่ตรวจสอบได้ ไม่ได้แปลว่าไม่มีอุปกรณ์</span></div>
        <div className="compareViewToggle"><button className={!diffOnly ? "on" : undefined} type="button" onClick={() => toggleDiff(false)}>ทั้งหมด</button><button className={diffOnly ? "on" : undefined} type="button" onClick={() => toggleDiff(true)}>เฉพาะจุดที่ต่าง</button></div>
      </div>

      <section className="compareQuick">
        <div className="compareSectionTitle"><small>QUICK COMPARE</small><h2>เห็นภาพก่อนลงรายละเอียด</h2></div>
        <div className="compareMatrixScroll">
          <div className="compareMatrix" style={matrixStyle}>
            <div className="compareCarHeader compareStickyRow">
              <div className="compareAttribute compareAttributeHead">หัวข้อ</div>
              {selected.map((trim) => <div className="compareCarHeadCell" key={trim.id}>
                {(trim as any).model_image_url ? <img src={(trim as any).model_image_url} alt="" /> : null}
                <small>{trim.brand_name}</small><strong>{trim.model_name}</strong><span>{trim.name}</span>
                <b>{compareValue(trim, "price") || "—"}</b>
              </div>)}
            </div>
            {quickRows.map((row) => {
              const different = workspaceRowIsDifferent(selected, row, factMap);
              return <div className={`compareDataRow ${different ? "different" : ""}`} key={row.id}>
                <div className="compareAttribute">{row.label}{different ? <em>ต่าง</em> : null}</div>
                {selected.map((trim) => {
                  const cell = displayCell(trim, row, factMap);
                  return <div className={`compareValueCell ${!cell.known ? "unknown" : ""}`} key={`${row.id}:${trim.id}`}>{cell.display || "—"}</div>;
                })}
              </div>;
            })}
          </div>
        </div>
      </section>

      <section className="compareFull">
        <div className="compareSectionTitle"><small>FULL COMPARISON</small><h2>รายละเอียดทั้งหมดที่มีข้อมูลยืนยัน</h2></div>
        <div className="compareMatrixScroll">
          <div className="compareMatrix" style={matrixStyle}>
            <div className="compareCarHeader compareStickyRow">
              <div className="compareAttribute compareAttributeHead">ข้อมูล</div>
              {selected.map((trim) => <div className="compareCarHeadCell compact" key={trim.id}><small>{trim.brand_name}</small><strong>{trim.model_name}</strong><span>{trim.name}</span></div>)}
            </div>
            {sections.map((section) => <details className="compareSection" open key={section.id}>
              <summary>{section.title}<span>{section.rows.length ? `${section.rows.length} รายการ` : "ยังไม่มีข้อมูลยืนยัน"}</span></summary>
              {section.rows.length ? section.rows.map((row) => {
                const different = workspaceRowIsDifferent(selected, row, factMap);
                return <div className={`compareDataRow ${different ? "different" : ""}`} key={row.id}>
                  <div className="compareAttribute">{row.label}{different ? <em>ต่าง</em> : null}</div>
                  {selected.map((trim) => {
                    const cell = displayCell(trim, row, factMap);
                    const feature = row.source === "spec" && (cell.display === "มี" || cell.display === "ไม่มี");
                    return <div className={`compareValueCell ${!cell.known ? "unknown" : ""}`} key={`${row.id}:${trim.id}`}>{feature ? <span className={`compareFeature ${cell.display === "มี" ? "present" : "absent"}`}>{cell.display}</span> : cell.display || "—"}</div>;
                  })}
                </div>;
              }) : <div className="compareNoVerified">ยังไม่มี verified fact สำหรับหมวดนี้ใน Trim ที่เลือก — ระบบไม่ตีความช่องว่างว่า “ไม่มีอุปกรณ์”</div>}
            </details>)}
          </div>
        </div>
      </section>
    </>}

    <section className="compareFootnote compareFootnoteV2"><b>หลักการอ่านข้อมูล</b><p>“มี/ไม่มี” แสดงเฉพาะเมื่อ canonical spec fact เป็น KNOWN จริงเท่านั้น ส่วน “—” หมายถึงยังไม่มีค่าที่ตรวจสอบได้หรือยังไม่ควรสรุป. ตัวเลขและอุปกรณ์ไม่ถูกนำไปคำนวณคะแนนรวม และ TDR ไม่ประกาศผู้ชนะอัตโนมัติเพราะค่าที่มากกว่าหรือมีอุปกรณ์มากกว่าไม่ได้หมายถึงเหมาะกับทุกคน.</p></section>
  </>;
}
