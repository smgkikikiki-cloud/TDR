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
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    const db = browserDb();
    if (!db) return setMessage("ระบบสมาชิกยังไม่ได้ตั้งค่า Supabase บน deployment นี้");

    setBusy(true);
    setMessage("");

    if (mode === "signup") {
      const normalized = normalizeThaiPhone(phone);
      if (!normalized) {
        setBusy(false);
        return setMessage("กรอกเบอร์มือถือไทย 10 หลัก หรือเบอร์แบบ +66 ให้ถูกต้อง");
      }
      const { data, error } = await db.auth.signUp({
        email,
        password,
        options: {
          data: { phone_e164: normalized },
          emailRedirectTo: `${window.location.origin}/member/billing`,
        },
      });
      setBusy(false);
      if (error) return setMessage(error.message);
      if (!data.session) {
        setMessage("สร้างบัญชีแล้ว กรุณายืนยันอีเมลจากข้อความของ Supabase แล้วกลับมาเข้าสู่ระบบ");
        setMode("login");
        return;
      }
      router.replace("/member/billing");
      router.refresh();
      return;
    }

    const { data, error } = await db.auth.signInWithPassword({ email, password });
    setBusy(false);
    if (error || !data.session) return setMessage(error?.message || "เข้าสู่ระบบไม่สำเร็จ");
    router.replace("/member/billing");
    router.refresh();
  }

  return (
    <main className={styles.shell}>
      <section className={styles.loginCard}>
        <div className={styles.eyebrow}>TDR REPORT · MEMBER</div>
        <h1>{mode === "signup" ? "สร้างบัญชี TDR Report" : "เข้าสู่ระบบ TDR Report"}</h1>
        <p className={styles.muted}>ข้อมูลรถ ราคา และสเปกยังเปิดฟรี บัญชีใช้เฉพาะเครื่องมือวิเคราะห์แบบสมาชิก โดยเบอร์มือถือจะผูกกับ Customer ID และบัตรถูกเก็บโดย Stripe ไม่ใช่ TDR</p>

        <form onSubmit={submit} className={styles.form}>
          <label>อีเมล<input type="email" required value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="email" /></label>
          <label>รหัสผ่าน<input type="password" required minLength={8} value={password} onChange={(event) => setPassword(event.target.value)} autoComplete={mode === "signup" ? "new-password" : "current-password"} /></label>
          {mode === "signup" ? <label>เบอร์มือถือ<input type="tel" required placeholder="08x xxx xxxx" value={phone} onChange={(event) => setPhone(event.target.value)} autoComplete="tel" /></label> : null}
          <button type="submit" disabled={busy}>{busy ? "กำลังดำเนินการ…" : mode === "signup" ? "สร้างบัญชี" : "เข้าสู่ระบบ"}</button>
        </form>

        {message ? <p className={styles.message}>{message}</p> : null}
        <button className={styles.textButton} type="button" onClick={() => { setMode(mode === "signup" ? "login" : "signup"); setMessage(""); }}>
          {mode === "signup" ? "มีบัญชีแล้ว · เข้าสู่ระบบ" : "ยังไม่มีบัญชี · สมัครสมาชิก"}
        </button>
        <Link className={styles.backLink} href="/reports">← กลับหน้า TDR Report</Link>
      </section>
    </main>
  );
}
