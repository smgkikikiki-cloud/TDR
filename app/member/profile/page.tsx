"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { browserDb } from "@/lib/supabase-browser";
import styles from "../member.module.css";

type Activation = {
  activated: boolean;
  emailConfirmed: boolean;
  phoneVerified: boolean;
  profileComplete: boolean;
  activationSource: "VERIFIED" | "LEGACY_PAID" | null;
};

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

  // TDR-owned phone verification, in three steps:
  //  1. Reserve (this account, this phone) on TDR's own server BEFORE
  //     triggering any SMS -- rejects a phone already verified or being
  //     verified on a different TDR account.
  //  2. The browser uses Supabase's documented phone-change OTP flow
  //     (updateUser + verifyOtp) to actually send/verify the SMS.
  //  3. TDR server-side confirmation: independently re-reads this
  //     account's own current Supabase Auth state and only marks the
  //     reservation (and therefore activation) confirmed if it matches
  //     what was reserved. This closes a real Supabase gap where phone-
  //     change OTP verification is resolved through the non-unique
  //     auth.users.phone_change column -- see lib/phone-verification.ts.
  async function sendPhoneOtp() {
    if (!token) return;
    const normalized = normalizeThaiPhone(phone);
    if (!normalized) { setPhoneMessage("กรอกเบอร์มือถือไทย 10 หลัก หรือเบอร์แบบ +66 ให้ถูกต้อง"); return; }
    setPhoneBusy(true); setPhoneMessage("");
    try {
      const reserveResponse = await fetch("/api/account/phone/reserve", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ phone: normalized }),
      });
      const reserveBody = await reserveResponse.json();
      if (!reserveResponse.ok) throw new Error(reserveBody.error || "จองเบอร์เพื่อยืนยันไม่สำเร็จ");

      const db = browserDb();
      if (!db) throw new Error("deployment นี้ยังไม่ได้ตั้งค่า Supabase client");
      const { error } = await db.auth.updateUser({ phone: normalized });
      if (error) throw new Error(error.message);

      setOtpSent(true);
      setPhoneMessage("ส่งรหัสยืนยัน (OTP) ไปที่เบอร์นี้แล้ว กรุณากรอกรหัสด้านล่าง");
    } catch (error) {
      setPhoneMessage(error instanceof Error ? error.message : "ส่งรหัสยืนยันไม่สำเร็จ");
    } finally {
      setPhoneBusy(false);
    }
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
      // Supabase reporting success is not, by itself, trusted as proof
      // THIS account is verified -- the server independently re-checks.
      const confirmResponse = await fetch("/api/account/phone/confirm", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      const confirmBody = await confirmResponse.json();
      if (!confirmResponse.ok) throw new Error(confirmBody.error || "ยืนยันเบอร์มือถือไม่สำเร็จ");
      setActivation(confirmBody.activation ?? null);
      setPhoneMessage("ยืนยันเบอร์มือถือสำเร็จ");
      setOtpSent(false);
      setOtpCode("");
    } catch (confirmError) {
      setPhoneMessage(confirmError instanceof Error ? confirmError.message : "ยืนยันไม่สำเร็จ");
    } finally {
      setPhoneBusy(false);
    }
  }

  return (
    <main className={styles.shell}>
      <section className={styles.loginCard}>
        <div className={styles.eyebrow}>TDR REPORT · PROFILE</div>
        <h1>ข้อมูลบัญชี</h1>
        <p className={styles.muted}>
          เข้าสู่ระบบแล้วใช้ Compare และ Sales Tools ได้ทันทีตามสิทธิ์ของบัญชี —
          ข้อมูลด้านล่างกรอกเพิ่มได้ตามสะดวก ไม่กรอกก็ไม่กระทบการใช้งาน
        </p>

        {activation ? (
          <>
            <ul className={styles.form} style={{ marginTop: 0 }}>
              <li>{activation.emailConfirmed ? "✓" : "○"} ยืนยันอีเมล</li>
              <li>{activation.phoneVerified ? "✓" : "○"} ยืนยันเบอร์มือถือ</li>
              <li>{activation.profileComplete ? "✓" : "○"} รหัสไปรษณีย์ + บุคคล/องค์กร</li>
            </ul>
            {/* Checkout is the one thing that needs all three, not just the
                phone -- saying otherwise would send somebody to Stripe only
                to be turned away there. */}
            {!activation.activated ? (
              <p className={styles.muted}>
                สามข้อด้านบนต้องครบทั้งหมดเฉพาะตอน<b>สมัครแพ็กเกจแบบชำระเงินครั้งแรก</b>เท่านั้น
                — การใช้งานปกติไม่ต้องใช้
              </p>
            ) : null}
          </>
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
          <label>รหัสไปรษณีย์ (ไม่บังคับ)<input pattern="[0-9]{4,10}" value={postcode} onChange={(event) => setPostcode(event.target.value)} /></label>
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
