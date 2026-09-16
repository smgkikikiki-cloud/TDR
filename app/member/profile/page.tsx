"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { browserDb } from "@/lib/supabase-browser";
import styles from "../member.module.css";

type Activation = { activated: boolean; emailConfirmed: boolean; phoneVerified: boolean; profileComplete: boolean };

function normalizeThaiPhone(value: string) {
  const compact = value.replace(/[\s()-]/g, "");
  if (/^0\d{9}$/.test(compact)) return `+66${compact.slice(1)}`;
  if (/^\+[1-9]\d{7,14}$/.test(compact)) return compact;
  return null;
}

export default function MemberProfilePage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [postcode, setPostcode] = useState("");
  const [isIndividual, setIsIndividual] = useState(true);
  const [companyName, setCompanyName] = useState("");
  const [marketingConsent, setMarketingConsent] = useState(false);
  const [consentText, setConsentText] = useState("");
  const [activation, setActivation] = useState<Activation | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [saved, setSaved] = useState(false);

  const [phone, setPhone] = useState("");
  const [otpCode, setOtpCode] = useState("");
  const [otpSent, setOtpSent] = useState(false);
  const [phoneBusy, setPhoneBusy] = useState(false);
  const [phoneMessage, setPhoneMessage] = useState("");

  async function refreshStatus(accessToken: string) {
    const response = await fetch("/api/account/profile", {
      headers: { Authorization: `Bearer ${accessToken}` },
      cache: "no-store",
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || "โหลดสถานะไม่สำเร็จ");
    setConsentText(body.marketing_consent_text || "");
    setActivation(body.activation ?? null);
    if (body.profile) {
      setPostcode(body.profile.postcode || "");
      setIsIndividual(body.profile.is_individual !== false);
      setCompanyName(body.profile.company_name || "");
      setMarketingConsent(Boolean(body.profile.marketing_consent));
    }
    return body;
  }

  useEffect(() => {
    async function boot() {
      const db = browserDb();
      if (!db) return;
      const { data } = await db.auth.getSession();
      if (!data.session) { router.replace("/member/login"); return; }
      setToken(data.session.access_token);
      try {
        await refreshStatus(data.session.access_token);
      } catch (error) {
        setMessage(error instanceof Error ? error.message : "โหลดสถานะไม่สำเร็จ");
      }
    }
    boot();
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
      setActivation(body.activation ?? null);
      setSaved(true);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "บันทึกไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }

  // Real Supabase Auth phone verification (updateUser + verifyOtp with
  // type "phone_change"), not a typed string stored as if it were
  // verified. Once Supabase Auth confirms the phone, the existing
  // tdr_sync_customer_from_auth trigger (migration_v21) links it into
  // tdr_customer_phone_identities automatically -- this page only needs
  // to trigger the OTP flow and then re-read activation status.
  async function sendPhoneOtp() {
    const db = browserDb();
    if (!db) return;
    const normalized = normalizeThaiPhone(phone);
    if (!normalized) { setPhoneMessage("กรอกเบอร์มือถือไทย 10 หลัก หรือเบอร์แบบ +66 ให้ถูกต้อง"); return; }
    setPhoneBusy(true); setPhoneMessage("");
    const { error } = await db.auth.updateUser({ phone: normalized });
    setPhoneBusy(false);
    if (error) { setPhoneMessage(error.message); return; }
    setOtpSent(true);
    setPhoneMessage("ส่งรหัสยืนยัน (OTP) ไปที่เบอร์นี้แล้ว กรุณากรอกรหัสด้านล่าง");
  }

  async function confirmPhoneOtp() {
    const db = browserDb();
    if (!db || !token) return;
    const normalized = normalizeThaiPhone(phone);
    if (!normalized || !otpCode.trim()) { setPhoneMessage("กรอกรหัส OTP ที่ได้รับทาง SMS"); return; }
    setPhoneBusy(true); setPhoneMessage("");
    const { error } = await db.auth.verifyOtp({ phone: normalized, token: otpCode.trim(), type: "phone_change" });
    if (error) {
      setPhoneBusy(false);
      setPhoneMessage(error.message);
      return;
    }
    try {
      await refreshStatus(token);
      setPhoneMessage("ยืนยันเบอร์มือถือสำเร็จ");
      setOtpSent(false);
      setOtpCode("");
    } catch (refreshError) {
      setPhoneMessage(refreshError instanceof Error ? refreshError.message : "ยืนยันสำเร็จ แต่โหลดสถานะไม่สำเร็จ");
    } finally {
      setPhoneBusy(false);
    }
  }

  return (
    <main className={styles.shell}>
      <section className={styles.loginCard}>
        <div className={styles.eyebrow}>TDR REPORT · PROFILE</div>
        <h1>ยืนยันตัวตนและข้อมูลบัญชี</h1>
        <p className={styles.muted}>ต้องยืนยันอีเมล ยืนยันเบอร์มือถือ และกรอกโปรไฟล์ให้ครบก่อนใช้เครื่องมือสมาชิก (Compare / Sales Tools) — ไม่ต้องผูกบัตร</p>

        {activation ? (
          <ul className={styles.form} style={{ marginTop: 0 }}>
            <li>{activation.emailConfirmed ? "✓" : "○"} ยืนยันอีเมลแล้ว</li>
            <li>{activation.phoneVerified ? "✓" : "○"} ยืนยันเบอร์มือถือแล้ว</li>
            <li>{activation.profileComplete ? "✓" : "○"} กรอกโปรไฟล์ครบ (รหัสไปรษณีย์ + องค์กร/บุคคลทั่วไป)</li>
            {activation.activated ? <li><b>พร้อมใช้งาน Compare และ Sales Tools แล้ว</b></li> : null}
          </ul>
        ) : null}

        <div className={styles.form}>
          <label>เบอร์มือถือ<input type="tel" placeholder="08x xxx xxxx" value={phone} onChange={(event) => setPhone(event.target.value)} autoComplete="tel" /></label>
          {!otpSent ? (
            <button type="button" disabled={phoneBusy} onClick={sendPhoneOtp}>{phoneBusy ? "กำลังส่ง…" : "ส่งรหัสยืนยัน (OTP)"}</button>
          ) : (
            <>
              <label>รหัส OTP<input inputMode="numeric" value={otpCode} onChange={(event) => setOtpCode(event.target.value)} /></label>
              <button type="button" disabled={phoneBusy} onClick={confirmPhoneOtp}>{phoneBusy ? "กำลังยืนยัน…" : "ยืนยันรหัส OTP"}</button>
              <button type="button" className={styles.textButton} disabled={phoneBusy} onClick={sendPhoneOtp}>ส่งรหัสอีกครั้ง</button>
            </>
          )}
          {phoneMessage ? <p className={styles.message}>{phoneMessage}</p> : null}
        </div>

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
