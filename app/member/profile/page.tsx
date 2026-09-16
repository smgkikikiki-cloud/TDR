"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { browserDb } from "@/lib/supabase-browser";
import styles from "../member.module.css";

export default function MemberProfilePage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [postcode, setPostcode] = useState("");
  const [isIndividual, setIsIndividual] = useState(true);
  const [companyName, setCompanyName] = useState("");
  const [marketingConsent, setMarketingConsent] = useState(false);
  const [consentText, setConsentText] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    async function boot() {
      const db = browserDb();
      if (!db) return;
      const { data } = await db.auth.getSession();
      if (!data.session) { router.replace("/member/login"); return; }
      setToken(data.session.access_token);
      const response = await fetch("/api/account/profile", {
        headers: { Authorization: `Bearer ${data.session.access_token}` },
        cache: "no-store",
      });
      const body = await response.json();
      setConsentText(body.marketing_consent_text || "");
      if (body.profile) {
        setPostcode(body.profile.postcode || "");
        setIsIndividual(body.profile.is_individual !== false);
        setCompanyName(body.profile.company_name || "");
        setMarketingConsent(Boolean(body.profile.marketing_consent));
      }
    }
    boot();
  }, [router]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!token) return;
    setBusy(true); setMessage("");
    try {
      const response = await fetch("/api/account/profile", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({
          postcode,
          is_individual: isIndividual,
          company_name: companyName,
          marketing_consent: marketingConsent,
        }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || "บันทึกไม่สำเร็จ");
      setSaved(true);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "บันทึกไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className={styles.shell}>
      <section className={styles.loginCard}>
        <div className={styles.eyebrow}>TDR REPORT · PROFILE</div>
        <h1>ข้อมูลบัญชี</h1>
        <p className={styles.muted}>ใช้ระบุตัวตน/ธุรกิจของบัญชี Free นี้ ไม่บังคับต้องยินยอมรับข่าวสารการตลาด</p>

        <form onSubmit={submit} className={styles.form}>
          <label>รหัสไปรษณีย์<input required pattern="[0-9]{4,10}" value={postcode} onChange={(event) => setPostcode(event.target.value)} /></label>
          <label className={styles.check}>
            <input type="checkbox" checked={!isIndividual} onChange={(event) => setIsIndividual(!event.target.checked)} />
            <span>สมัครในนามองค์กร/บริษัท (ไม่เลือก = บุคคลทั่วไป / Individual / Not affiliated)</span>
          </label>
          {!isIndividual ? (
            <label>ชื่อบริษัท/องค์กร<input required={!isIndividual} value={companyName} onChange={(event) => setCompanyName(event.target.value)} /></label>
          ) : null}
          <label className={styles.check}>
            <input type="checkbox" checked={marketingConsent} onChange={(event) => setMarketingConsent(event.target.checked)} />
            <span>{consentText || "I would like to receive market updates, research insights, product news, and occasional promotional communications from Thailand Development Report by email."}</span>
          </label>
          <button type="submit" disabled={busy}>{busy ? "กำลังบันทึก…" : "บันทึกข้อมูล"}</button>
        </form>

        {message ? <p className={styles.message}>{message}</p> : null}
        {saved ? <p className={styles.message}>บันทึกแล้ว</p> : null}
        <Link className={styles.backLink} href="/member">ไปที่ Dashboard →</Link>
      </section>
    </main>
  );
}
