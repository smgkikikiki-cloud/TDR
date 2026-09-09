"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { browserDb } from "@/lib/supabase-browser";
import styles from "../member.module.css";

export default function MemberLoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    const db = browserDb();
    if (!db) {
      setMessage("ระบบสมาชิกยังไม่ได้ตั้งค่า Supabase บน deployment นี้");
      return;
    }

    setBusy(true);
    setMessage("");
    try {
      if (mode === "login") {
        const { error } = await db.auth.signInWithPassword({ email, password });
        if (error) throw error;
        router.replace("/member");
        router.refresh();
      } else {
        const { data, error } = await db.auth.signUp({ email, password });
        if (error) throw error;
        if (data.session) {
          router.replace("/member");
          router.refresh();
        } else {
          setMessage("สร้างบัญชีแล้ว — ตรวจอีเมลเพื่อยืนยันบัญชีก่อนเข้าสู่ระบบ");
        }
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "เข้าสู่ระบบไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className={styles.shell}>
      <section className={styles.loginCard}>
        <div className={styles.eyebrow}>TDR REPORT · MEMBER</div>
        <h1>{mode === "login" ? "เข้าสู่ระบบสมาชิก" : "สร้างบัญชี TDR"}</h1>
        <p className={styles.muted}>บัญชีอย่างเดียวไม่เปิดข้อมูลจดทะเบียน สิทธิ์ TDR Report จะถูกผูกกับบัญชีหลังแพ็กเกจถูกเปิดใช้งาน</p>

        <form onSubmit={submit} className={styles.form}>
          <label>อีเมล<input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" /></label>
          <label>รหัสผ่าน<input type="password" required minLength={6} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={mode === "login" ? "current-password" : "new-password"} /></label>
          <button type="submit" disabled={busy}>{busy ? "กำลังดำเนินการ…" : mode === "login" ? "เข้าสู่ TDR Report" : "สร้างบัญชี"}</button>
        </form>

        {message ? <p className={styles.message}>{message}</p> : null}

        <button className={styles.textButton} type="button" onClick={() => { setMode(mode === "login" ? "signup" : "login"); setMessage(""); }}>
          {mode === "login" ? "ยังไม่มีบัญชี? สร้างบัญชี" : "มีบัญชีแล้ว? เข้าสู่ระบบ"}
        </button>
        <Link className={styles.backLink} href="/reports">← กลับหน้า TDR Report</Link>
      </section>
    </main>
  );
}
