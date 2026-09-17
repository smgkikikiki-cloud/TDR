"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { browserDb } from "@/lib/supabase-browser";
import { bodyLabel } from "@/lib/body-labels";

type TrimOption = { id: string; brand_name: string | null; model_name: string | null; name: string | null };
type CompareRow = { key: string; label: string; different: boolean; values: (string | null)[] };
type CompareGroup = { title: string; rows: CompareRow[] };
type SelectedTrim = { id: string; brand_name: string | null; model_name: string | null; name: string | null; model_slug: string | null; image_url: string | null };
type CompareResult = {
  selected: SelectedTrim[];
  missing_selection: boolean;
  groups: CompareGroup[];
  quota: { used: number; limit: number | null; remaining: number | null; resets_at: string };
};

function choiceLabel(trim: TrimOption) {
  return [trim.brand_name, trim.model_name, trim.name].filter(Boolean).join(" · ");
}

export default function ComparePage() {
  const [allTrims, setAllTrims] = useState<TrimOption[]>([]);
  const [slots, setSlots] = useState<string[]>(["", "", "", ""]);
  const [diffOnly, setDiffOnly] = useState(false);
  const [token, setToken] = useState<string | null | undefined>(undefined);
  const [result, setResult] = useState<CompareResult | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "quota" | "error">("idle");
  const [message, setMessage] = useState("");

  useEffect(() => {
    fetch("/api/compare/trims").then((r) => r.json()).then((body) => setAllTrims(body.trims || []));
    const db = browserDb();
    if (!db) { setToken(null); return; }
    db.auth.getSession().then(({ data }) => setToken(data.session?.access_token ?? null));
  }, []);

  const selectedCount = useMemo(() => slots.filter(Boolean).length, [slots]);

  async function runCompare(event: React.FormEvent) {
    event.preventDefault();
    if (!token) return;
    const ids = [...new Set(slots.filter(Boolean))];
    if (ids.length < 2) return;
    setStatus("loading"); setMessage("");
    try {
      const params = new URLSearchParams();
      ids.forEach((id) => params.append("trims", id));
      if (diffOnly) params.set("diff", "1");
      const response = await fetch(`/api/tools/compare?${params.toString()}`, {
        headers: { Authorization: `Bearer ${token}` },
        cache: "no-store",
      });
      const body = await response.json();
      if (!response.ok) throw Object.assign(new Error(body.error || "เทียบรถไม่สำเร็จ"), { status: response.status });
      setResult(body);
      setStatus("idle");
    } catch (error: any) {
      setStatus(error?.status === 429 ? "quota" : "error");
      setMessage(error instanceof Error ? error.message : "เทียบรถไม่สำเร็จ");
    }
  }

  return <div className="comparePage">
    <section className="compareHero">
      <div>
        <div className="sfEyebrow">VEHICLE COMPARE</div>
        <h1>เทียบรถแบบตรงรุ่นย่อย</h1>
        <p>เลือก 2–4 รุ่นย่อยเพื่อเปรียบเทียบราคา ขนาด ระบบขับเคลื่อน และสเปกพื้นฐาน</p>
      </div>
      <Link href="/models">กลับไปดูแคตตาล็อก →</Link>
    </section>

    {token === null ? (
      <section className="compareEmpty">
        <b>ต้องเข้าสู่ระบบก่อนเทียบรถ</b>
        <span>เครื่องมือเทียบรถเป็นฟีเจอร์ของบัญชี TDR (สมัครฟรีได้ ไม่ต้องผูกบัตร) — ดูข้อมูลรุ่น/ราคายังเปิดสาธารณะตามปกติ</span>
        <Link href="/member/login">เข้าสู่ระบบ / สมัครสมาชิกฟรี →</Link>
      </section>
    ) : (
      <form className="comparePicker" onSubmit={runCompare}>
        {[0, 1, 2, 3].map((slot) => (
          <label key={slot}>
            <span>คันที่ {slot + 1}{slot < 2 ? " · ต้องเลือก" : " · ไม่บังคับ"}</span>
            <select value={slots[slot]} onChange={(event) => setSlots((prev) => prev.map((v, i) => i === slot ? event.target.value : v))} required={slot < 2}>
              <option value="">เลือกรุ่นย่อย</option>
              {allTrims.map((trim) => <option key={`${slot}:${trim.id}`} value={trim.id}>{choiceLabel(trim)}</option>)}
            </select>
          </label>
        ))}
        <label className="compareDiffToggle">
          <input type="checkbox" checked={diffOnly} onChange={(event) => setDiffOnly(event.target.checked)} />
          <span>แสดงเฉพาะจุดที่ต่างกัน</span>
        </label>
        <button type="submit" disabled={selectedCount < 2 || status === "loading"}>{status === "loading" ? "กำลังเทียบ…" : "เทียบรถ"}</button>
      </form>
    )}

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
                  <small>{trim.brand_name}</small>
                  <strong>{trim.model_name}</strong>
                  <span>{trim.name}</span>
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
                    const displayValue = row.key === "body_type" && value ? bodyLabel(value) : value;
                    return <td key={`${row.key}:${index}`} className={displayValue ? undefined : "compareMissing"}>{displayValue || "—"}</td>;
                  })}
                </tr>
              )),
            ])}
          </tbody>
        </table>
      </section>
    ) : null}

    <section className="compareFootnote">
      <b>หลักของหน้านี้</b>
      <p>แถวที่ไม่มีข้อมูลในทุกคันจะไม่แสดงเลย ส่วนช่อง “—” หมายถึงยังไม่มีข้อมูลในฐานข้อมูล ไม่ได้เดาหรือนำค่าของรุ่นใกล้เคียงมาเติม. ราคาแคมเปญแยกจาก List price และข้อมูลยาง/ล้อยังไม่อยู่ใน public product scope ตอนนี้.</p>
    </section>
  </div>;
}
