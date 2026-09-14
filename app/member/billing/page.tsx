"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { browserDb } from "@/lib/supabase-browser";
import styles from "./billing.module.css";

type PlanCode = "registration_monthly" | "registration_annual";

type BillingStatus = {
  user: { id: string; customerId: string; email: string | null; phone: string };
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
  annualCheckoutConfigured: boolean;
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

function maskedPhone(value: string) {
  const digits = value.replace(/\D/g, "");
  if (digits.startsWith("66") && digits.length >= 11) return `+66 ${digits.slice(2, 4)} xxx xxxx`;
  return value;
}

function isActiveSubscription(data: BillingStatus | null) {
  if (!data?.subscription) return false;
  return !["CANCELED", "EXPIRED", "UNPAID"].includes(data.subscription.status);
}

export default function MemberBillingPage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [data, setData] = useState<BillingStatus | null>(null);
  const [selectedPlan, setSelectedPlan] = useState<PlanCode>("registration_monthly");
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
        const status = await api(accessToken, "/api/billing/status") as BillingStatus;
        setData(status);
        if (status.subscription?.plan_code === "registration_annual") setSelectedPlan("registration_annual");
        else if (!status.subscription && status.annualCheckoutConfigured) setSelectedPlan("registration_annual");
        const checkout = new URLSearchParams(window.location.search).get("checkout");
        if (checkout === "success") setMessage("ชำระเงินเสร็จแล้ว ระบบกำลังยืนยัน webhook และเปิดสิทธิ์ Market Intelligence");
        if (checkout === "cancelled") setMessage("ยกเลิก Stripe Checkout แล้ว ยังไม่มีการเปลี่ยนสิทธิ์สมาชิก");
      } catch (error) {
        setMessage(error instanceof Error ? error.message : "โหลดข้อมูลการชำระเงินไม่สำเร็จ");
      }
    }
    boot();
  }, [router]);

  const activeSubscription = isActiveSubscription(data);
  const annualSelected = selectedPlan === "registration_annual";
  const checkoutReady = Boolean(data && (annualSelected ? data.annualCheckoutConfigured : data.checkoutConfigured));

  const selected = useMemo(() => annualSelected ? {
    label: "TDR Pro · รายปี",
    cadence: "รายปี (12 เดือน)",
    amount: "฿8,790",
    detail: "จาก ฿11,880 · ประหยัด ฿3,090",
  } : {
    label: "TDR Pro · รายเดือน",
    cadence: "รายเดือน",
    amount: "฿990",
    detail: "ยกเลิกได้ทุกเมื่อ",
  }, [annualSelected]);

  async function startCheckout() {
    if (!token || !checkoutReady || activeSubscription) return;
    setBusy(true);
    setMessage("");
    try {
      const result = await api(token, "/api/billing/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan: selectedPlan }),
      });
      window.location.assign(result.url);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "เปิด Stripe Checkout ไม่สำเร็จ");
      setBusy(false);
    }
  }

  async function openPortal() {
    if (!token) return;
    setBusy(true);
    setMessage("");
    try {
      const result = await api(token, "/api/billing/portal", { method: "POST" });
      window.location.assign(result.url);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "เปิดหน้าจัดการสมาชิกไม่สำเร็จ");
      setBusy(false);
    }
  }

  return (
    <main className={styles.page}>
      <header className={styles.hero}>
        <div className={styles.eyebrow}>BILLING</div>
        <h1>เลือกแพ็กเกจสำหรับบัญชีของคุณ</h1>
        <p>สร้างบัญชีเรียบร้อยแล้ว ขั้นตอนถัดไปคือเลือกแพ็กเกจ และไปชำระเงินผ่าน Stripe Checkout</p>
      </header>

      {message ? <div className={styles.message}>{message}</div> : null}

      {!data ? <section className={styles.loading}>กำลังโหลดข้อมูลบัญชี…</section> : (
        <>
          <div className={styles.layout}>
            <section className={styles.main}>
              <div className={styles.periodTabs}>
                <button className={!annualSelected ? styles.active : ""} type="button" onClick={() => setSelectedPlan("registration_monthly")}>
                  <b>รายเดือน</b><span>ยืดหยุ่น เหมาะสำหรับการเริ่มต้น</span>
                </button>
                <button className={annualSelected ? styles.active : ""} type="button" onClick={() => setSelectedPlan("registration_annual")}>
                  <b>รายปี <span className={styles.saveBadge}>ประหยัด 26%</span></b><span>คุ้มค่ากว่าสำหรับการใช้งานระยะยาว</span>
                </button>
              </div>

              <div className={styles.planGrid}>
                <article className={`${styles.planCard} ${!annualSelected ? styles.selected : ""}`} onClick={() => setSelectedPlan("registration_monthly")}>
                  <div className={styles.planTitle}><span className={styles.radio} />TDR Pro · รายเดือน</div>
                  <div className={styles.price}><strong>฿990</strong><span>/ เดือน</span></div>
                  <p className={styles.struck}>ยกเลิกได้ทุกเมื่อ</p>
                  <ul className={styles.features}>
                    <li>เข้าถึงข้อมูลและฟีเจอร์ทั้งหมด</li>
                    <li>อัปเดตข้อมูลต่อเนื่อง</li>
                    <li>ยกเลิกได้ทุกเมื่อ</li>
                  </ul>
                </article>

                <article className={`${styles.planCard} ${annualSelected ? styles.selected : ""} ${!data.annualCheckoutConfigured ? styles.unavailable : ""}`} onClick={() => setSelectedPlan("registration_annual")}>
                  {data.annualCheckoutConfigured ? <span className={styles.best}>คุ้มสุด</span> : <span className={styles.unavailableBadge}>ยังไม่เปิดชำระรายปี</span>}
                  <div className={styles.planTitle}><span className={styles.radio} />TDR Pro · รายปี</div>
                  <div className={styles.price}><strong>฿8,790</strong><span>/ ปี</span></div>
                  <p className={styles.struck}>จาก <s>฿11,880</s> <span className={styles.savings}>ประหยัด ฿3,090 ต่อปี</span></p>
                  <ul className={styles.features}>
                    <li>เข้าถึงข้อมูลและฟีเจอร์ทั้งหมด</li>
                    <li>อัปเดตข้อมูลต่อเนื่อง</li>
                    <li>ประหยัด 26% จากราคารายเดือน</li>
                    <li>ต่ออายุอัตโนมัติและยกเลิกได้ผ่าน Stripe Portal</li>
                  </ul>
                </article>
              </div>

              <section className={styles.checkout}>
                <h2>ไปชำระเงิน</h2>
                <p>ตรวจสอบรายละเอียดก่อนดำเนินการชำระเงิน</p>
                <div className={styles.summary}>
                  <div className={styles.summaryRow}><span>แพ็กเกจ</span><strong>{selected.label}</strong></div>
                  <div className={styles.summaryRow}><span>รอบชำระ</span><strong>{selected.cadence}</strong></div>
                </div>
                <div className={styles.total}>
                  <span>ยอดที่ต้องชำระรอบนี้</span>
                  <div><strong>{selected.amount}</strong><small>{selected.detail}</small></div>
                </div>
                {activeSubscription ? (
                  <button className={styles.pay} type="button" disabled>บัญชีนี้มีแพ็กเกจที่ใช้งานอยู่แล้ว</button>
                ) : (
                  <button className={styles.pay} type="button" disabled={busy || !checkoutReady} onClick={startCheckout}>
                    {busy ? "กำลังเปิด Stripe Checkout…" : checkoutReady ? "▣  ชำระเงินผ่าน Stripe  →" : annualSelected ? "ยังไม่เปิดชำระรายปี" : "รอตั้งค่า Stripe Price"}
                  </button>
                )}
                {!checkoutReady && annualSelected ? <p className={styles.errorNote}>ต้องตั้งค่า STRIPE_PRICE_REGISTRATION_ANNUAL ก่อนจึงจะเปิด Checkout รายปีได้</p> : null}
                <p className={styles.security}>🔒 ข้อมูลบัตรจะถูกจัดการโดย Stripe และไม่ได้ถูกเก็บโดย TDR</p>
                <Link className={styles.later} href="/market">ฉันจะชำระภายหลัง</Link>
              </section>
            </section>

            <aside className={styles.side}>
              <section className={styles.sideCard}>
                <h2>บัญชีของคุณ</h2>
                <div className={styles.accountRows}>
                  <div className={styles.accountRow}><span>อีเมล</span><strong>{data.user.email || "—"}</strong></div>
                  <div className={styles.accountRow}><span>เบอร์มือถือ</span><strong>{maskedPhone(data.user.phone)}</strong></div>
                  <div className={styles.accountRow}><span>Customer ID</span><strong>{data.user.customerId}</strong></div>
                  <div className={styles.accountRow}><span>สถานะปัจจุบัน</span><strong className={styles.statusPill}>{data.entitlement && ["ACTIVE", "GRACE"].includes(data.entitlement.status) ? "TDR Pro" : "Free"}</strong></div>
                </div>
                {activeSubscription ? <p className={styles.existing}>แพ็กเกจปัจจุบัน: {data.subscription?.plan_code === "registration_annual" ? "รายปี" : "รายเดือน"} · ถึง {date(data.subscription?.current_period_end)}</p> : null}
              </section>

              <section className={styles.sideCard}>
                <h2>เมื่ออัปเกรดแล้วจะได้</h2>
                <ul className={styles.benefits}>
                  <li>ยอดจดทะเบียนรายรุ่น</li>
                  <li>ส่วนแบ่งตลาด (Market Share)</li>
                  <li>การเปลี่ยนแปลงตลาด (MoM / YoY)</li>
                  <li>แนวโน้มย้อนหลัง 3 / 6 / 12 เดือน และ YTD</li>
                  <li>ส่งออกข้อมูล (CSV)</li>
                  <li>ติดตามตารางเปิดตัวรถใหม่ล่วงหน้า <span className={styles.soon}>เร็วๆ นี้</span></li>
                </ul>
              </section>

              <section className={styles.sideCard}>
                <h2>มีแพ็กเกจอยู่แล้ว?</h2>
                <p className={styles.manageCopy}>หลังชำระเงินสำเร็จ คุณจะสามารถดูสถานะสมาชิก วันต่ออายุ และจัดการการชำระเงินผ่าน Stripe Portal ได้จากหน้านี้</p>
                <button className={styles.manage} type="button" disabled={busy || !data.customerBound || !data.portalConfigured} onClick={openPortal}>ดูการสมัครสมาชิกของฉัน →</button>
                <button className={styles.refresh} type="button" disabled={busy} onClick={() => location.reload()}>รีเฟรชสถานะ</button>
              </section>
            </aside>
          </div>

          <section className={styles.footerTrust}>
            <article><div className={styles.icon}>✓</div><div><b>ชำระเงินปลอดภัย</b><span>ชำระผ่าน Stripe ตามมาตรฐานระบบชำระเงินสากล</span></div></article>
            <article><div className={styles.icon}>↻</div><div><b>จัดการแพ็กเกจภายหลังได้</b><span>จัดการบัตร ใบเสร็จ และการยกเลิกผ่าน Stripe Portal</span></div></article>
            <article><div className={styles.icon}>▤</div><div><b>สถานะการชำระเงินอยู่ในบัญชี</b><span>ระบบสมาชิกของ TDR ใช้ webhook เพื่ออัปเดตสิทธิ์หลังการชำระเงิน</span></div></article>
          </section>
        </>
      )}
    </main>
  );
}
