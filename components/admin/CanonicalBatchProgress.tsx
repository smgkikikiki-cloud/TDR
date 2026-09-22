"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

type Snapshot = {
  batchKey: string;
  status: string;
  attempts: number;
  releaseId: string | null;
  error: string | null;
  updatedAt: string | null;
  processingStartedAt: string | null;
  stagedAt: string | null;
  publishedAt: string | null;
};

type Props = {
  batchKey: string;
  dispatchStarted: boolean;
  returnTo: string;
  actionLabel: string;
};

const TERMINAL = new Set(["PUBLISHED", "FAILED", "REJECTED"]);

function statusCopy(status: string) {
  switch (status) {
    case "QUEUED": return "รอ worker";
    case "PROCESSING": return "กำลังแก้ canonical data";
    case "STAGED": return "เขียนข้อมูลแล้ว · กำลัง publish";
    case "PUBLISHED": return "เผยแพร่แล้ว";
    case "FAILED": return "ไม่สำเร็จ";
    case "REJECTED": return "ถูกปฏิเสธ";
    default: return status || "กำลังตรวจสถานะ";
  }
}

export default function CanonicalBatchProgress({
  batchKey, dispatchStarted, returnTo, actionLabel,
}: Props) {
  const router = useRouter();
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [readError, setReadError] = useState("");

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let redirectTimer: ReturnType<typeof setTimeout> | undefined;

    async function poll() {
      try {
        const response = await fetch(`/api/admin/canonical-batches/${encodeURIComponent(batchKey)}`, {
          cache: "no-store",
        });
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(body?.error || `status ${response.status}`);
        if (cancelled) return;
        const next = body as Snapshot;
        setSnapshot(next);
        setReadError("");

        if (next.status === "PUBLISHED") {
          // Give the operator a moment to see success, then reopen the vehicle
          // from the newly active release. The deleted/edited trim should now
          // be visibly gone/updated without a manual refresh.
          redirectTimer = setTimeout(() => router.replace(returnTo), 700);
          return;
        }
        if (!TERMINAL.has(next.status)) {
          timer = setTimeout(poll, 2000);
        }
      } catch (error) {
        if (cancelled) return;
        setReadError(error instanceof Error ? error.message : "อ่านสถานะไม่สำเร็จ");
        timer = setTimeout(poll, 4000);
      }
    }

    void poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      if (redirectTimer) clearTimeout(redirectTimer);
    };
  }, [batchKey, returnTo, router]);

  const status = snapshot?.status || "QUEUED";
  const failed = status === "FAILED" || status === "REJECTED";

  return <div className={failed ? "adminNotice" : "adminSaved"}>
    <p><b>{actionLabel}</b></p>
    <p>
      สถานะ: <b>{statusCopy(status)}</b>
      {snapshot?.attempts ? ` · attempt ${snapshot.attempts}` : ""}
    </p>
    {status === "QUEUED" ? <p>
      {dispatchStarted
        ? "ส่งสัญญาณให้ GitHub worker แล้ว — ปกติควรเริ่มภายในไม่กี่วินาที"
        : "คำสั่งถูกเก็บไว้แล้ว แต่ worker ไม่ได้ถูกปลุกทันที — fallback จะ sweep queue ทุก 5 นาที"}
    </p> : null}
    {status === "PROCESSING" ? <p>worker หยิบงานแล้ว กำลังเขียนและตรวจ canonical data</p> : null}
    {status === "STAGED" ? <p>ข้อมูลผ่าน validation และถูก stage แล้ว เหลือ publish active release</p> : null}
    {status === "PUBLISHED" ? <p>เสร็จแล้ว กำลังพากลับไปหน้า Vehicle…</p> : null}
    {failed ? <p role="alert">{snapshot?.error || "worker ทำรายการนี้ไม่สำเร็จ"}</p> : null}
    {readError ? <p role="alert">อ่านสถานะล่าสุดไม่ได้: {readError}</p> : null}
    <p><small><code>{batchKey}</code></small></p>
    {failed ? <p><Link href={returnTo}>← กลับหน้า Vehicle</Link></p> : null}
  </div>;
}
