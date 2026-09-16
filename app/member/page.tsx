"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { browserDb } from "@/lib/supabase-browser";
import { REGISTRATION_DIMENSION_MODULE, SALES_MODULES, type SalesModule } from "@/lib/access-policy";
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

const MODULE_LABEL: Record<SalesModule, string> = {
  brand_share: "ส่วนแบ่งแบรนด์",
  model_share: "ส่วนแบ่งรุ่น",
  month_on_month: "เปรียบเทียบเดือนต่อเดือน",
  segment_share: "ส่วนแบ่งตามเซกเมนต์",
  powertrain_share: "ส่วนแบ่งระบบขับเคลื่อน",
  chinese_bev_rank: "อันดับรถไฟฟ้าจีน",
};

// dimension -> selectable module, inverse of REGISTRATION_DIMENSION_MODULE.
const DIMENSION_BY_MODULE: Record<SalesModule, string> = Object.fromEntries(
  Object.entries(REGISTRATION_DIMENSION_MODULE)
    .filter(([, module]) => module !== null)
    .map(([dimension, module]) => [module as SalesModule, dimension]),
) as Record<SalesModule, string>;

type ModuleStatus = { tier: "FREE" | "INDIVIDUAL" | "PRO"; pickCount: number | null; selection: SalesModule[] | null };
type FeatureInfo = { label: string; label_th: string; state: "unavailable" | "teaser" | "limited" | "full" | "tailored" };

async function loadDimension(token: string, dimension: string, actionId: string, period?: string) {
  const params = new URLSearchParams({ dimension, limit: "100" });
  if (period) params.set("period", period);
  const response = await fetch(`/api/report/registration?${params.toString()}`, {
    headers: { Authorization: `Bearer ${token}`, "X-TDR-Action-Id": actionId },
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
  const [status, setStatus] = useState<"loading" | "ready" | "forbidden" | "quota" | "picker" | "error">("loading");
  const [message, setMessage] = useState("");
  const [moduleStatus, setModuleStatus] = useState<ModuleStatus | null>(null);
  const [picked, setPicked] = useState<SalesModule[]>([]);
  const [token, setToken] = useState<string | null>(null);
  const [features, setFeatures] = useState<Record<string, FeatureInfo>>({});

  async function loadDashboard(accessToken: string, modules: SalesModule[] | null) {
    const db = browserDb();
    const actionId = crypto.randomUUID();
    try {
      const coverageRows = await loadDimension(accessToken, "coverage", actionId);
      const latest = [...coverageRows].sort((a, b) => String(a.period).localeCompare(String(b.period))).at(-1);
      if (!latest) throw new Error("ยังไม่มีข้อมูลจดทะเบียนในระบบ");
      const period = String(latest.period).slice(0, 10);
      const activeModules = modules ?? SALES_MODULES;
      const wanted = new Set(activeModules.map((m) => DIMENSION_BY_MODULE[m]));
      const [brands, models, mom, segments, powertrains, chineseBev] = await Promise.all([
        wanted.has("brand") ? loadDimension(accessToken, "brand", actionId, period) : Promise.resolve([]),
        wanted.has("model") ? loadDimension(accessToken, "model", actionId, period) : Promise.resolve([]),
        wanted.has("mom") ? loadDimension(accessToken, "mom", actionId, period) : Promise.resolve([]),
        wanted.has("segment") ? loadDimension(accessToken, "segment", actionId, period) : Promise.resolve([]),
        wanted.has("powertrain") ? loadDimension(accessToken, "powertrain", actionId, period) : Promise.resolve([]),
        wanted.has("chinese-bev") ? loadDimension(accessToken, "chinese-bev", actionId, period) : Promise.resolve([]),
      ]);
      setData({ period, coverage: latest, brands, models, mom, segments, powertrains, chineseBev });
      setStatus("ready");
    } catch (error: any) {
      if (error?.status === 401) {
        await db?.auth.signOut();
        router.replace("/member/login");
        return;
      }
      if (error?.status === 429) setStatus("quota");
      else if (error?.status === 403) setStatus("forbidden");
      else setStatus("error");
      setMessage(error instanceof Error ? error.message : "โหลดข้อมูลไม่สำเร็จ");
    }
  }

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
      setToken(session.access_token);

      try {
        const moduleResponse = await fetch("/api/tools/sales-modules", {
          headers: { Authorization: `Bearer ${session.access_token}` },
          cache: "no-store",
        });
        const moduleBody = await moduleResponse.json();
        if (!moduleResponse.ok) throw new Error(moduleBody.error || "โหลดสถานะ Sales Tools ไม่สำเร็จ");
        if (cancelled) return;
        const modStatus: ModuleStatus = { tier: moduleBody.tier, pickCount: moduleBody.pick_count, selection: moduleBody.selection };
        setModuleStatus(modStatus);

        // Reserved capabilities (e.g. Provincial Registration) are fetched
        // from the centralized policy, not hardcoded here -- this call
        // never touches the unfinished data pipeline itself, it only
        // reads the coming-soon/ladder state.
        fetch("/api/tools/features", { headers: { Authorization: `Bearer ${session.access_token}` }, cache: "no-store" })
          .then((r) => r.json())
          .then((body) => { if (!cancelled && body.features) setFeatures(body.features); })
          .catch(() => {});

        if (modStatus.tier === "FREE" && !modStatus.selection) {
          setStatus("picker");
          return;
        }
        await loadDashboard(session.access_token, modStatus.selection);
      } catch (error) {
        if (cancelled) return;
        setStatus("error");
        setMessage(error instanceof Error ? error.message : "โหลดข้อมูลไม่สำเร็จ");
      }
    }
    boot();
    return () => { cancelled = true; };
  }, [router]);

  function togglePicked(module: SalesModule) {
    setPicked((prev) => {
      if (prev.includes(module)) return prev.filter((m) => m !== module);
      if (moduleStatus?.pickCount && prev.length >= moduleStatus.pickCount) return prev;
      return [...prev, module];
    });
  }

  async function confirmPicked() {
    if (!token || !moduleStatus?.pickCount) return;
    try {
      const response = await fetch("/api/tools/sales-modules", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ modules: picked }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || "บันทึกตัวเลือกไม่สำเร็จ");
      setModuleStatus((prev) => (prev ? { ...prev, selection: body.selection } : prev));
      setStatus("loading");
      await loadDashboard(token, body.selection);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "บันทึกตัวเลือกไม่สำเร็จ");
    }
  }

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
  if (status === "picker") return (
    <main className={styles.shell}>
      <section className={styles.stateCard}>
        <div className={styles.eyebrow}>TDR REPORT · FREE</div>
        <h1>เลือกโมดูล Sales Tools {moduleStatus?.pickCount || 4} จาก {SALES_MODULES.length}</h1>
        <p>บัญชี Free เลือกได้ {moduleStatus?.pickCount || 4} โมดูลต่อรอบ (1 เดือนปฏิทิน เวลาไทย) แล้วจะล็อกไว้จนกว่าจะขึ้นรอบถัดไป อัปเกรดเป็น Individual หรือ Pro เพื่อใช้ได้ทุกโมดูลไม่จำกัด</p>
        {message ? <p className={styles.message}>{message}</p> : null}
        <div className={styles.moduleGrid}>
          {SALES_MODULES.map((module) => (
            <label key={module} className={picked.includes(module) ? styles.moduleChecked : undefined}>
              <input type="checkbox" checked={picked.includes(module)} onChange={() => togglePicked(module)} />
              <span>{MODULE_LABEL[module]}</span>
            </label>
          ))}
        </div>
        <button disabled={picked.length !== (moduleStatus?.pickCount || 4)} onClick={confirmPicked}>ยืนยันตัวเลือก</button>
      </section>
    </main>
  );
  if (status === "quota") return <main className={styles.shell}><section className={styles.stateCard}><div className={styles.eyebrow}>TDR REPORT</div><h1>ใช้โควตา Sales Tools ของวันนี้ครบแล้ว</h1><p>{message}</p><p className={styles.muted}>บัญชี Free ใช้ได้ 10 คำขอต่อวัน (เวลาไทย) อัปเกรดเป็น Individual หรือ Pro เพื่อใช้งานไม่จำกัด</p><Link href="/pricing">ดูแพ็กเกจ</Link></section></main>;
  if (status === "forbidden") return <main className={styles.shell}><section className={styles.stateCard}><div className={styles.eyebrow}>TDR REPORT</div><h1>บัญชีนี้ยังไม่มีสิทธิ์ข้อมูลจดทะเบียน</h1><p>{message}</p><button onClick={signOut}>ออกจากระบบ</button></section></main>;
  if (status === "error" || !data) return <main className={styles.shell}><section className={styles.stateCard}><h1>โหลดรายงานไม่สำเร็จ</h1><p>{message}</p><button onClick={() => location.reload()}>ลองใหม่</button></section></main>;

  const month = new Intl.DateTimeFormat("th-TH", { month: "long", year: "numeric" }).format(new Date(`${data.period}T00:00:00Z`));

  return (
    <main className={styles.shell}>
      <header className={styles.header}>
        <div><div className={styles.eyebrow}>TDR REPORT · REGISTRATION INTELLIGENCE</div><h1>ตลาดรถยนต์ไทย · {month}</h1><p>ภาพรวมข้อมูลจดทะเบียน DLT ที่ map เข้ากับ canonical Vehicle Master ของ TDR; ใช้ Market Comparison สำหรับกำหนด Segment, Body, Brand, Model และ Powertrain เพื่อเทียบตลาดแบบละเอียด</p></div>
        <div className={styles.memberActions}><Link className={styles.secondary} href="/member/market">เปิด Market Comparison</Link><button className={styles.secondary} onClick={signOut}>ออกจากระบบ</button></div>
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

      {Object.entries(features).map(([key, feature]) => feature.state === "teaser" ? (
        <section className={styles.panel} key={key}>
          <div className={styles.panelHead}>
            <div><div className={styles.eyebrow}>SALES TOOLS · COMING SOON</div><h2>{feature.label_th}</h2></div>
            <span className={styles.comingSoonBadge}>Coming soon</span>
          </div>
          <p className={styles.muted}>เครื่องมือนี้ยังอยู่ระหว่างพัฒนาชุดข้อมูล ยังไม่มีตัวเลขให้แสดงในตอนนี้ — จะเปิดใช้งานเมื่อชุดข้อมูลรายจังหวัดพร้อม</p>
        </section>
      ) : null)}

      <p className={styles.footnote}>August coverage may be lower than prior months when only the classless pivot source is available. Ambiguous pickup nameplates stay raw instead of being forced into Cab/Double Cab.</p>
    </main>
  );
}
