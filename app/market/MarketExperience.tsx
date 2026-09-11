"use client";

import { ReactNode, useEffect, useState } from "react";
import { browserDb } from "@/lib/supabase-browser";
import { MarketWorkspace } from "@/app/member/market/MarketWorkspace";
import styles from "./market-experience.module.css";

type BrandOption = { id: string; name: string };
type ModelOption = {
  id: string;
  name: string;
  brandId: string;
  brandName: string;
  segment: string | null;
  bodyType: string | null;
  powertrains: string[];
};

type Mode = "checking" | "public" | "pro" | "error";

export function MarketExperience({
  brands,
  models,
  publicPreview,
  freePreview,
}: {
  brands: BrandOption[];
  models: ModelOption[];
  publicPreview: ReactNode;
  freePreview: ReactNode;
}) {
  const [mode, setMode] = useState<Mode>("checking");
  const [message, setMessage] = useState("");

  useEffect(() => {
    let cancelled = false;

    async function boot() {
      const db = browserDb();
      if (!db) {
        if (!cancelled) setMode("public");
        return;
      }

      const { data } = await db.auth.getSession();
      const session = data.session;
      if (!session) {
        if (!cancelled) setMode("public");
        return;
      }

      try {
        const response = await fetch("/api/report/registration?dimension=coverage&limit=1", {
          headers: { Authorization: `Bearer ${session.access_token}` },
          cache: "no-store",
        });

        if (cancelled) return;
        if (response.ok) {
          setMode("pro");
          return;
        }
        if (response.status === 401) {
          await db.auth.signOut();
          setMode("public");
          return;
        }
        if (response.status === 403) {
          setMode("public");
          return;
        }

        const body = await response.json().catch(() => ({}));
        setMessage(body.error || "ตรวจสอบสิทธิ์ Market Intelligence ไม่สำเร็จ");
        setMode("error");
      } catch (error) {
        if (cancelled) return;
        setMessage(error instanceof Error ? error.message : "ตรวจสอบสิทธิ์ Market Intelligence ไม่สำเร็จ");
        setMode("error");
      }
    }

    boot();
    return () => { cancelled = true; };
  }, []);

  if (mode === "checking") {
    return <div className={styles.checking}><span />กำลังเปิด Market Intelligence…</div>;
  }
  if (mode === "error") {
    return (
      <section className={styles.errorCard}>
        <h1>เปิด Market Intelligence ไม่สำเร็จ</h1>
        <p>{message}</p>
        <button type="button" onClick={() => location.reload()}>ลองใหม่</button>
      </section>
    );
  }
  if (mode === "pro") return <MarketWorkspace brands={brands} models={models} />;

  return <>{freePreview || publicPreview}</>;
}
