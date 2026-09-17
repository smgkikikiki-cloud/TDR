"use client";

/**
 * Shown by the admin error boundaries. Without one, anything a page or a
 * server action throws -- a validation guard, a stale-release rejection, an
 * expired review, a missing Supabase credential -- reaches the user as
 * Next.js's raw crash screen (a full stack trace in dev, a blank
 * "Application error" in production), which makes a working guard look like
 * a broken app. Those messages are already written for a human, in Thai, so
 * this shows them and offers the two ways out: try again, or go back.
 */
export function AdminErrorPanel({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return <div className="adminEditor">
    <div className="adminHeader">
      <div>
        <small>ADMIN</small>
        <h1>ทำรายการนี้ไม่สำเร็จ</h1>
        <p>ข้อมูลยังไม่ถูกบันทึกอะไรทั้งสิ้น — แก้ตามข้อความด้านล่างแล้วลองใหม่ได้เลย</p>
      </div>
    </div>

    <div className="adminError">{error.message || "เกิดข้อผิดพลาดที่ไม่ทราบสาเหตุ"}</div>

    <div className="adminFormActions">
      <button className="adminPrimary" onClick={reset}>ลองใหม่อีกครั้ง</button>
      <a className="adminSecondary" href="/admin/vehicles">← กลับรายการรถ</a>
    </div>

    {error.digest ? <p className="adminHint">อ้างอิงสำหรับตรวจ log: {error.digest}</p> : null}
  </div>;
}
