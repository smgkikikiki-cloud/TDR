"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { browserDb } from "@/lib/supabase-browser";
import styles from "../member.module.css";

type BillingStatus = {
  user: { id: string; email: string | null; phone: string | null };
  customerBound: boolean;
  subscription: null | {
    plan_code: string;
    status: string;
    current_period_end: string | null;
    cancel_at_period_end: boolean;
    provider: string;
  };
  entitlement: null | { product: string; status: string; valid_until: string | null };
  checkoutConfigured: boolean;
  portalConfigured: boolean;
};

async function api(token: string, path: string, init?: RequestInit) {
  const response = await fetch(path, {
    ...init,
    headers: { ...(init?.headers || {}), Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  const body = await response.json();
  if (!response.ok) throw Object.assign(new Error(body.error || "ดำเนินการไม่สำเร็จ"), { status: response.status });
  return body;
}

function date(value: string | null | undefined) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("th-TH", { dateStyle: "medium" }).format(new Date(value));
}

export default function MemberBillingPage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [data, setData] = useState<BillingStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    async function boot() {
      const db = browserDb();
      if (!db) return setMessage("deployment นี้ยังไม่ได้ตั้งค่า Supabase client");
      const { data: sessionData } = await db.auth.getSession();
      if (!sessionData.session) {
        router.replace("/member/login");
        return;
      }
      const accessToken = sessionData.session.access_token;
      setToken(accessToken);
      try {
        const status = await api(accessToken, "/api/billing/status");
        setData(status);
        const checkout = new URLSearchParams(window.location.search).get("checkout");
        if (checkout === "success") setMessage("ชำระเงินเสร็จแล้ว ระบบกำลังยืนยัน webhook และเปิดสิทธิ์ TDR Report");
        if (checkout === "cancelled") setMessage("ยกเลิก Checkout แล้ว ยังไม่มีการเปลี่ยนสิทธิ์สมาชิก");
      } catch (error) {
        setMessage(error instanceof Error ? error.message : "โหลดข้อมูลการชำระเงินไม่สำเร็จ");
      }
    }
    boot();
  }, [router]);

  async function startCheckout() {
    if (!token) return;
    setBusy(true); setMessage("");
    try {
      const result = await api(token, "/api/billing/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan: "registration_monthly" }),
      });
      window.location.assign(result.url);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "เปิด Checkout ไม่สำเร็จ");
      setBusy(false);
    }
  }

  async function openPortal() {
    if (!token) return;
    setBusy(true); setMessage("");
    try {
      const result = await api(token, "/api/billing/portal", { method: "POST" });
      window.location.assign(result.url);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "เปิดหน้าจัดการการชำระเงินไม่สำเร็จ");
      setBusy(false);
    }
  }

  return (
    <main className={styles.shell}>
      <header className={styles.header}>
        <div>
          <div className={styles.eyebrow}>TDR REPORT · BILLING</div>
          <h1>บัญชีและการชำระเงิน</h1>
          <p>ข้อมูลรถฝั่ง consumer ยังเปิดฟรีโดยไม่ต้องล็อกอิน หน้านี้ใช้เฉพาะ subscription ของ TDR Report เท่านั้น และ TDR ไม่เก็บเลขบัตร/CVV เอง</p>
        </div>
        <Link className={styles.secondary} href="/member">กลับ Dashboard</Link>
      </header>

      {message ? <p className={styles.message}>{message}</p> : null}

      {!data ? (
        <section className={styles.stateCard}>กำลังโหลดข้อมูลบัญชี…</section>
      ) : <>
        <section className={styles.kpis}>
          <article><span>อีเมล</span><strong className={styles.accountValue}>{data.user.email || "—"}</strong><small>บัญชี Supabase</small></article>
          <article><span>เบอร์มือถือ</span><strong className={styles.accountValue}>{data.user.phone || "—"}</strong><small>customer identity/contact</small></article>
          <article><span>Subscription</span><strong>{data.subscription?.status || "ยังไม่มี"}</strong><small>{data.subscription?.provider || "Stripe เมื่อเริ่มจ่าย"}</small></article>
          <article><span>TDR Report access</span><strong>{data.entitlement?.status || "ยังไม่มี"}</strong><small>ถึง {date(data.entitlement?.valid_until)}</small></article>
        </section>

        <section className={styles.panel}>
          <div className={styles.panelHead}>
            <div><div className={styles.eyebrow}>TDR REPORT</div><h2>Registration Intelligence · รายเดือน</h2></div>
            <span>{data.subscription?.cancel_at_period_end ? "ยกเลิกเมื่อจบรอบ" : "subscription"}</span>
          </div>
          <div className={styles.billingCopy}>
            <p>การสมัครสมาชิกจะสร้าง Stripe Customer ผูกกับบัญชีนี้ บัตรถูกเก็บโดย Stripe และ webhook เป็นตัวเปิด/ต่ออายุ entitlement ของ TDR โดยอัตโนมัติ</p>
            {data.subscription?.current_period_end ? <p>รอบปัจจุบันถึง <b>{date(data.subscription.current_period_end)}</b></p> : null}
          </div>
          <div className={styles.billingActions}>
            {!data.subscription || ["CANCELED", "EXPIRED", "UNPAID"].includes(data.subscription.status) ? (
              <button disabled={busy || !data.checkoutConfigured} onClick={startCheckout}>
                {data.checkoutConfigured ? "สมัครด้วยบัตรเครดิต / เดบิต" : "รอตั้งค่า Stripe Price"}
              </button>
            ) : null}
            {data.customerBound ? (
              <button className={styles.secondary} disabled={busy || !data.portalConfigured} onClick={openPortal}>จัดการบัตร / ใบเสร็จ / ยกเลิก</button>
            ) : null}
            <button className={styles.secondary} disabled={busy} onClick={() => location.reload()}>รีเฟรชสถานะ</button>
          </div>
          <p className={styles.note}>PromptPay จะต่อเป็น prepaid pass ภายหลังโดยใช้ entitlement ชุดเดียวกัน ไม่บังคับให้โครงสร้าง subscription หลักต้องผูกกับ QR</p>
        </section>
      </>}
    </main>
  );
}
