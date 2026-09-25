"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { browserDb } from "@/lib/supabase-browser";

type FullArticle = {
  body_th: string;
  already_unlocked: boolean;
  quota: { used: number; limit: number | null; remaining: number | null; resets_at: string } | null;
};

/**
 * The one thing on the article page that needs a session: unlocking the
 * full body. Everything above it (title, author, date, summary) is
 * server-rendered and public; this is a client component only because
 * knowing who is reading requires the browser's own Supabase session.
 *
 * An anonymous reader never gets a "press to see it fail" button -- they
 * see the sign-up CTA directly, because app/api/research/read/route.ts
 * would 401 them anyway, and pretending otherwise is a worse UX than being
 * straight about it up front.
 */
export function ResearchUnlock({ slug }: { slug: string }) {
  const [token, setToken] = useState<string | null | undefined>(undefined);
  const [status, setStatus] = useState<"idle" | "loading" | "unlocked" | "quota" | "error">("idle");
  const [message, setMessage] = useState("");
  const [article, setArticle] = useState<FullArticle | null>(null);

  useEffect(() => {
    const db = browserDb();
    if (!db) { setToken(null); return; }
    db.auth.getSession().then(({ data }) => setToken(data.session?.access_token ?? null));
  }, []);

  async function unlock() {
    if (!token) return;
    setStatus("loading");
    setMessage("");
    try {
      const response = await fetch(`/api/research/read?slug=${encodeURIComponent(slug)}`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        cache: "no-store",
      });
      const body = await response.json();
      if (!response.ok) throw Object.assign(new Error(body.error || "โหลดบทวิเคราะห์ไม่สำเร็จ"), { status: response.status });
      setArticle({ body_th: body.article.body_th, already_unlocked: body.already_unlocked, quota: body.quota });
      setStatus("unlocked");
    } catch (error: any) {
      setStatus(error?.status === 429 ? "quota" : "error");
      setMessage(error instanceof Error ? error.message : "โหลดบทวิเคราะห์ไม่สำเร็จ");
    }
  }

  if (status === "unlocked" && article) {
    return <section className="researchBody">
      {article.body_th.split(/\n{2,}/).map((paragraph, index) => <p key={index}>{paragraph}</p>)}
      {article.quota && article.quota.limit !== null ? (
        <p className="researchQuota">
          อ่านฉบับเต็มไปแล้ว {article.quota.used}/{article.quota.limit} ครั้งในเดือนนี้
          {article.already_unlocked ? " (บทความนี้ปลดล็อกไว้แล้ว อ่านซ้ำไม่เสียสิทธิ์)" : ""}
        </p>
      ) : null}
    </section>;
  }

  if (token === null) {
    return <section className="researchGate">
      <b>เข้าสู่ระบบเพื่ออ่านฉบับเต็ม</b>
      <span>บัญชีฟรีอ่านฉบับเต็มได้ 2 บทความ/เดือน อัปเกรดเพื่ออ่านไม่จำกัด</span>
      <Link className="sfBtn" href={`/member/login?next=${encodeURIComponent(`/research/${slug}`)}`}>
        สมัครฟรี / เข้าสู่ระบบ
      </Link>
    </section>;
  }

  return <section className="researchGate">
    {status === "quota" ? (
      <>
        <b>ใช้สิทธิ์อ่านฉบับเต็มของเดือนนี้ครบแล้ว</b>
        <span>{message} อัปเกรดบัญชีเพื่ออ่านไม่จำกัด</span>
        <Link className="sfBtn" href="/pricing">ดูแพ็กเกจ</Link>
      </>
    ) : status === "error" ? (
      <>
        <b>โหลดบทวิเคราะห์ไม่สำเร็จ</b>
        <span>{message}</span>
        <button className="sfBtn" type="button" onClick={unlock}>ลองอีกครั้ง</button>
      </>
    ) : (
      <button className="sfBtn" type="button" disabled={status === "loading" || token === undefined} onClick={unlock}>
        {status === "loading" ? "กำลังโหลด…" : "อ่านฉบับเต็ม"}
      </button>
    )}
  </section>;
}
