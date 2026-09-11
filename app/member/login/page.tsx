"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { browserDb } from "@/lib/supabase-browser";
import styles from "./login.module.css";

function normalizeThaiPhone(value: string) {
  const compact = value.replace(/[\s()-]/g, "");
  if (/^0\d{9}$/.test(compact)) return `+66${compact.slice(1)}`;
  if (/^\+[1-9]\d{7,14}$/.test(compact)) return compact;
  return null;
}

type Mode = "login" | "signup";

export default function MemberLoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    const requested = new URLSearchParams(window.location.search).get("mode");
    if (requested === "signup") setMode("signup");
  }, []);

  function switchMode(next: Mode) {
    setMode(next);
    setMessage("");
    const href = next === "signup" ? "/member/login?mode=signup" : "/member/login";
    router.replace(href, { scroll: false });
  }

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
        switchMode("login");
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
    <div className={styles.page}>
      <header className={styles.intro}>
        <div className={styles.eyebrow}>TDR PRO · MEMBER</div>
        <h1>{mode === "signup" ? "สร้างบัญชีเพื่อใช้ Market Intelligence" : "เข้าสู่ระบบ Market Intelligence"}</h1>
        <p>บัญชีเดียวสำหรับเครื่องมือวิเคราะห์ตลาดของ TDR ข้อมูลรถ แคทตาล็อก และเครื่องมือพื้นฐานยังเปิดใช้งานฟรีโดยไม่ต้องสมัครสมาชิก</p>
      </header>

      <section className={styles.authShell}>
        <aside className={styles.productPanel}>
          <div className={styles.productEyebrow}>MARKET INTELLIGENCE · TDR PRO</div>
          <h2>ข้อมูลตลาดสำหรับคนที่ต้องใช้มันทำงานจริง</h2>
          <p className={styles.productLead}>ยอดจดทะเบียน ส่วนแบ่งตลาด การเปลี่ยนแปลงรายรุ่น และแนวโน้มย้อนหลังจาก workspace เดียว</p>

          <div className={styles.priceBlock}><strong>฿990</strong><span>/ เดือน</span></div>
          <p className={styles.annual}>หรือ <b>฿8,790 / ปี</b><span className={styles.saving}>ประหยัด 26%</span></p>

          <ul className={styles.featureList}>
            <li><span>✓</span>ยอดจดทะเบียนและ Market Share รายรุ่น</li>
            <li><span>✓</span>ดูตามแบรนด์ รุ่น เซกเมนต์ ตัวถัง และระบบขับเคลื่อน</li>
            <li><span>✓</span>แนวโน้มย้อนหลัง 3 / 6 / 12 เดือน และ YTD</li>
            <li><span>✓</span>ส่งออกข้อมูล CSV</li>
          </ul>

          <div className={styles.comingSoon}>ติดตามตารางเปิดตัวรถใหม่ล่วงหน้า · เร็วๆ นี้</div>
        </aside>

        <div className={styles.formPanel}>
          <div className={styles.tabs} role="tablist" aria-label="บัญชีสมาชิก">
            <button type="button" className={`${styles.tab} ${mode === "login" ? styles.tabActive : ""}`} onClick={() => switchMode("login")}>เข้าสู่ระบบ</button>
            <button type="button" className={`${styles.tab} ${mode === "signup" ? styles.tabActive : ""}`} onClick={() => switchMode("signup")}>สมัครสมาชิก</button>
          </div>

          <h2>{mode === "signup" ? "สร้างบัญชี TDR" : "ยินดีต้อนรับกลับ"}</h2>
          <p className={styles.formLead}>{mode === "signup" ? "กรอกข้อมูลบัญชีก่อน ยังไม่มีการตัดเงินในหน้านี้" : "เข้าสู่บัญชีเพื่อจัดการแพ็กเกจและเปิดใช้งาน Market Intelligence"}</p>

          <form onSubmit={submit} className={styles.form}>
            <label>อีเมล<input type="email" required placeholder="name@example.com" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="email" /></label>
            <label>รหัสผ่าน<input type="password" required minLength={8} placeholder="อย่างน้อย 8 ตัวอักษร" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete={mode === "signup" ? "new-password" : "current-password"} /></label>
            {mode === "signup" ? <>
              <label>เบอร์มือถือ<input type="tel" required placeholder="08x xxx xxxx" value={phone} onChange={(event) => setPhone(event.target.value)} autoComplete="tel" /></label>
              <div className={styles.phoneHelp}><span>ใช้ผูกกับ Customer ID ของ TDR</span><span>ไทย / +66</span></div>
            </> : null}
            <button className={styles.submit} type="submit" disabled={busy}>{busy ? "กำลังดำเนินการ…" : mode === "signup" ? "สร้างบัญชีและไปต่อ →" : "เข้าสู่ระบบ →"}</button>
          </form>

          {message ? <p className={styles.message}>{message}</p> : null}

          <div className={styles.switchRow}>
            {mode === "signup" ? "มีบัญชีแล้ว? " : "ยังไม่มีบัญชี? "}
            <button className={styles.switchButton} type="button" onClick={() => switchMode(mode === "signup" ? "login" : "signup")}>{mode === "signup" ? "เข้าสู่ระบบ" : "สมัครสมาชิก"}</button>
          </div>

          <div className={styles.securityNote}>
            <div className={styles.securityIcon}>▣</div>
            <div><strong>ข้อมูลบัตรไม่ถูกเก็บโดย TDR</strong><span>หลังสร้างบัญชี การชำระเงินจะดำเนินการผ่าน Stripe Checkout เมื่อเลือกสมัครแพ็กเกจ</span></div>
          </div>

          <Link className={styles.backLink} href="/pricing">← กลับหน้าแพ็กเกจ</Link>
        </div>
      </section>
    </div>
  );
}
