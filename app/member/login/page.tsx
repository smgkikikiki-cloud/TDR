"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { browserDb } from "@/lib/supabase-browser";
import styles from "../member.module.css";

function normalizeThaiPhone(value: string) {
  const compact = value.replace(/[\s()-]/g, "");
  if (/^0\d{9}$/.test(compact)) return `+66${compact.slice(1)}`;
  if (/^\+[1-9]\d{7,14}$/.test(compact)) return compact;
  return null;
}

export default function MemberLoginPage() {
  const router = useRouter();
  const [phone, setPhone] = useState("");
  const [phoneE164, setPhoneE164] = useState<string | null>(null);
  const [otp, setOtp] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function requestOtp(event: FormEvent) {
    event.preventDefault();
    const db = browserDb();
    if (!db) return setMessage("ระบบสมาชิกยังไม่ได้ตั้งค่า Supabase บน deployment นี้");
    const normalized = normalizeThaiPhone(phone);
    if (!normalized) return setMessage("กรอกเบอร์มือถือไทย 10 หลัก หรือเบอร์แบบ +66 ให้ถูกต้อง");
    setBusy(true); setMessage("");
    const { error } = await db.auth.signInWithOtp({
      phone: normalized,
      options: { shouldCreateUser: true },
    });
    setBusy(false);
    if (error) return setMessage(error.message);
    setPhoneE164(normalized);
    setMessage("ส่งรหัส OTP แล้ว กรุณากรอกรหัส 6 หลักจาก SMS");
  }

  async function verifyOtp(event: FormEvent) {
    event.preventDefault();
    const db = browserDb();
    if (!db || !phoneE164) return setMessage("กรุณาขอ OTP ใหม่");
    if (!/^\d{6}$/.test(otp)) return setMessage("OTP ต้องเป็นตัวเลข 6 หลัก");
    setBusy(true); setMessage("");
    const { data, error } = await db.auth.verifyOtp({ phone: phoneE164, token: otp, type: "sms" });
    setBusy(false);
    if (error || !data.session) return setMessage(error?.message || "ยืนยัน OTP ไม่สำเร็จ");
    router.replace("/member/billing");
    router.refresh();
  }

  return (
    <main className={styles.shell}>
      <section className={styles.loginCard}>
        <div className={styles.eyebrow}>TDR REPORT · MEMBER</div>
        <h1>{phoneE164 ? "ยืนยันเบอร์มือถือ" : "เข้าสู่ระบบด้วยเบอร์มือถือ"}</h1>
        <p className={styles.muted}>ข้อมูลรถ ราคา และสเปกยังเปิดฟรี บัญชีนี้ใช้เฉพาะเครื่องมือวิเคราะห์แบบสมาชิก โดย Customer ID จะผูกกับเบอร์ที่ผ่าน OTP เท่านั้น</p>

        {!phoneE164 ? <form onSubmit={requestOtp} className={styles.form}>
          <label>เบอร์มือถือ<input type="tel" required placeholder="08x xxx xxxx" value={phone} onChange={(event) => setPhone(event.target.value)} autoComplete="tel" /></label>
          <button type="submit" disabled={busy}>{busy ? "กำลังส่ง…" : "รับรหัส OTP"}</button>
        </form> : <form onSubmit={verifyOtp} className={styles.form}>
          <label>รหัส OTP<input inputMode="numeric" pattern="[0-9]{6}" maxLength={6} required value={otp} onChange={(event) => setOtp(event.target.value.replace(/\D/g, ""))} autoComplete="one-time-code" /></label>
          <button type="submit" disabled={busy}>{busy ? "กำลังยืนยัน…" : "ยืนยันและเข้าสู่ระบบ"}</button>
        </form>}

        {message ? <p className={styles.message}>{message}</p> : null}
        {phoneE164 ? <button className={styles.textButton} type="button" onClick={() => { setPhoneE164(null); setOtp(""); setMessage(""); }}>เปลี่ยนเบอร์ / ขอ OTP ใหม่</button> : null}
        <Link className={styles.backLink} href="/reports">← กลับหน้า TDR Report</Link>
      </section>
    </main>
  );
}
