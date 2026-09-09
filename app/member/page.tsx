"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { browserDb } from "@/lib/supabase-browser";
import styles from "./member.module.css";

type Row = Record<string, any>;

type DashboardData = {
  period: string;
  coverage: Row | null;
  brands: Row[];
  models: Row[];
  mom: Row[];
  segments: Row[];
  powertrains: Row[];
  chineseBev: Row[];
};

async function loadDimension(token: string, dimension: string, period?: string) {
  const params = new URLSearchParams({ dimension, limit: "100" });
  if (period) params.set("period", period);
  const response = await fetch(`/api/report/registration?${params.toString()}`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  const body = await response.json();
  if (!response.ok) throw Object.assign(new Error(body.error || "โหลดข้อมูลไม่สำเร็จ"), { status: response.status });
  return body.rows as Row[];
}

function n(value: unknown) {
  return Number(value || 0).toLocaleString("th-TH");
}

function pct(value: unknown, digits = 1) {
  const number = Number(value);
  return Number.isFinite(number) ? `${number.toFixed(digits)}%` : "—";
}

export default function MemberDashboardPage() {
  const router = useRouter();
  const [data, setData] = useState<DashboardData | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "forbidden" | "error">("loading");
  const [message, setMessage] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function boot() {
      const db = browserDb();
      if (!db) {
        setStatus("error");
        setMessage("deployment นี้ยังไม่ได้ตั้งค่า Supabase client");
        return;
      }
      const { data: sessionData } = await db.auth.getSession();
      const session = sessionData.session;
      if (!session) {
        router.replace("/member/login");
        return;
      }

      try {
        const coverageRows = await loadDimension(session.access_token, "coverage");
        const latest = [...coverageRows].sort((a, b) => String(a.period).localeCompare(String(b.period))).at(-1);
        if (!latest) throw new Error("ยังไม่มีข้อมูลจดทะเบียนในระบบ");
        const period = String(latest.period).slice(0, 10);
        const [brands, models, mom, segments, powertrains, chineseBev] = await Promise.all([
          loadDimension(session.access_token, "brand", period),
          loadDimension(session.access_token, "model", period),
          loadDimension(session.access_token, "mom", period),
          loadDimension(session.access_token, "segment", period),
          loadDimension(session.access_token, "powertrain", period),
          loadDimension(session.access_token, "chinese-bev", period),
        ]);
        if (cancelled) return;
        setData({ period, coverage: latest, brands, models, mom, segments, powertrains, chineseBev });
        setStatus("ready");
      } catch (error: any) {
        if (cancelled) return;
        if (error?.status === 401) {
          await db.auth.signOut();
          router.replace("/member/login");
          return;
        }
        if (error?.status === 403) setStatus("forbidden");
        else setStatus("error");
        setMessage(error instanceof Error ? error.message : "โหลดข้อมูลไม่สำเร็จ");
      }
    }
    boot();
    return () => { cancelled = true; };
  }, [router]);

  const movers = useMemo(() => {
    if (!data) return [];
    return data.mom
      .filter((row) => row.previous_registrations != null && row.mom_delta != null)
      .sort((a, b) => Math.abs(Number(b.mom_delta)) - Math.abs(Number(a.mom_delta)))
      .slice(0, 12);
  }, [data]);

  async function signOut() {
    await browserDb()?.auth.signOut();
    router.replace("/member/login");
  }

  if (status === "loading") return <main className={styles.shell}><div className={styles.stateCard}>กำลังโหลด TDR Report…</div></main>;
  if (status === "forbidden") return <main className={styles.shell}><section className={styles.stateCard}><div className={styles.eyebrow}>TDR REPORT</div><h1>บัญชีนี้ยังไม่มีสิทธิ์ข้อมูลจดทะเบียน</h1><p>{message}</p><p className={styles.muted}>สำหรับลูกค้าทดลอง ทีม TDR สามารถเปิดสิทธิ์ registration_full ให้บัญชีนี้ได้ทันทีหลังยืนยันแพ็กเกจ</p><button onClick={signOut}>ออกจากระบบ</button></section></main>;
  if (status === "error" || !data) return <main className={styles.shell}><section className={styles.stateCard}><h1>โหลดรายงานไม่สำเร็จ</h1><p>{message}</p><button onClick={() => location.reload()}>ลองใหม่</button></section></main>;

  const month = new Intl.DateTimeFormat("th-TH", { month: "long", year: "numeric" }).format(new Date(`${data.period}T00:00:00Z`));

  return (
    <main className={styles.shell}>
      <header className={styles.header}>
        <div><div className={styles.eyebrow}>TDR REPORT · REGISTRATION INTELLIGENCE</div><h1>ตลาดรถยนต์ไทย · {month}</h1><p>ข้อมูลจดทะเบียน DLT ที่ผ่าน crosswalk ของ TDR — MarketTrim ยังคงเป็นฐานข้อมูลอีกชุดหนึ่งและไม่ได้ถูกนำมาปนกัน</p></div>
        <button className={styles.secondary} onClick={signOut}>ออกจากระบบ</button>
      </header>

      <section className={styles.kpis}>
        <article><span>จดทะเบียนรวม</span><strong>{n(data.coverage?.total_registrations)}</strong><small>คัน</small></article>
        <article><span>Canonical mapping</span><strong>{pct(data.coverage?.mapped_unit_pct)}</strong><small>{n(data.coverage?.mapped_registrations)} คันที่ผูกกับรุ่นได้</small></article>
        <article><span>อันดับ 1 แบรนด์</span><strong>{data.brands[0]?.brand_name || "—"}</strong><small>{pct(data.brands[0]?.market_share_pct, 2)} share</small></article>
        <article><span>Chinese BEV #1</span><strong>{data.chineseBev[0]?.model_name || "—"}</strong><small>{n(data.chineseBev[0]?.registrations)} คัน</small></article>
      </section>

      <div className={styles.grid2}>
        <section className={styles.panel}>
          <div className={styles.panelHead}><div><div className={styles.eyebrow}>MARKET SHARE</div><h2>แบรนด์</h2></div><span>Top 12</span></div>
          <div className={styles.tableWrap}><table><thead><tr><th>#</th><th>แบรนด์</th><th>คัน</th><th>Share</th></tr></thead><tbody>{data.brands.slice(0, 12).map((row) => <tr key={row.brand_key}><td>{row.market_rank}</td><td><b>{row.brand_name}</b></td><td>{n(row.registrations)}</td><td>{pct(row.market_share_pct, 2)}</td></tr>)}</tbody></table></div>
        </section>

        <section className={styles.panel}>
          <div className={styles.panelHead}><div><div className={styles.eyebrow}>CHINA · BEV</div><h2>อันดับรถไฟฟ้าจีน</h2></div><span>model-level</span></div>
          <div className={styles.tableWrap}><table><thead><tr><th>#</th><th>รุ่น</th><th>แบรนด์</th><th>คัน</th></tr></thead><tbody>{data.chineseBev.slice(0, 12).map((row) => <tr key={`${row.bev_rank}-${row.model_id}`}><td>{row.bev_rank}</td><td><b>{row.model_name}</b></td><td>{row.brand_name}</td><td>{n(row.registrations)}</td></tr>)}</tbody></table></div>
        </section>
      </div>

      <div className={styles.grid2}>
        <section className={styles.panel}>
          <div className={styles.panelHead}><div><div className={styles.eyebrow}>POWERTRAIN</div><h2>สัดส่วนระบบขับเคลื่อน</h2></div><span>coverage {pct(data.powertrains[0]?.market_coverage_pct)}</span></div>
          <div className={styles.barList}>{data.powertrains.map((row) => <div className={styles.barRow} key={row.powertrain}><div><b>{row.powertrain}</b><span>{n(row.registrations)} คัน</span></div><div className={styles.bar}><i style={{ width: `${Math.min(Number(row.share_of_classified_pct), 100)}%` }} /></div><strong>{pct(row.share_of_classified_pct, 2)}</strong></div>)}</div>
          <p className={styles.note}>คำนวณเฉพาะรุ่น canonical ที่มี powertrain เดียว เพื่อไม่เดารุ่น ICE/HEV/PHEV/BEV ที่ DLT ไม่ได้แยกรุ่นย่อยชัดเจน</p>
        </section>

        <section className={styles.panel}>
          <div className={styles.panelHead}><div><div className={styles.eyebrow}>SEGMENT</div><h2>ส่วนแบ่งตามเซกเมนต์</h2></div><span>coverage {pct(data.segments[0]?.market_coverage_pct)}</span></div>
          <div className={styles.barList}>{data.segments.slice(0, 10).map((row) => <div className={styles.barRow} key={row.segment}><div><b>{row.segment}</b><span>{n(row.registrations)} คัน</span></div><div className={styles.bar}><i style={{ width: `${Math.min(Number(row.share_of_classified_pct), 100)}%` }} /></div><strong>{pct(row.share_of_classified_pct, 2)}</strong></div>)}</div>
        </section>
      </div>

      <section className={styles.panel}>
        <div className={styles.panelHead}><div><div className={styles.eyebrow}>MONTH-ON-MONTH</div><h2>รุ่นที่ขยับแรงจากเดือนก่อน</h2></div><span>เฉพาะ canonical model ที่เทียบข้ามเดือนได้</span></div>
        <div className={styles.tableWrap}><table><thead><tr><th>แบรนด์</th><th>รุ่น</th><th>เดือนก่อน</th><th>เดือนนี้</th><th>Δ คัน</th><th>MoM</th></tr></thead><tbody>{movers.map((row) => <tr key={row.entity_key}><td>{row.brand_name}</td><td><b>{row.model_name}</b></td><td>{n(row.previous_registrations)}</td><td>{n(row.registrations)}</td><td className={Number(row.mom_delta) >= 0 ? styles.positive : styles.negative}>{Number(row.mom_delta) >= 0 ? "+" : ""}{n(row.mom_delta)}</td><td>{row.mom_pct == null ? "—" : `${Number(row.mom_pct) >= 0 ? "+" : ""}${pct(row.mom_pct)}`}</td></tr>)}</tbody></table></div>
      </section>

      <p className={styles.footnote}>August coverage may be lower than prior months when only the classless pivot source is available. Ambiguous pickup nameplates stay raw instead of being forced into Cab/Double Cab.</p>
    </main>
  );
}
