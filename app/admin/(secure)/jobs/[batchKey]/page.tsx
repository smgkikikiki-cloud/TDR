import Link from "next/link";
import CanonicalBatchProgress from "@/components/admin/CanonicalBatchProgress";

function safeAdminReturn(value: string | undefined) {
  if (!value) return "/admin/vehicles";
  if (!value.startsWith("/admin/vehicles/")) return "/admin/vehicles";
  if (value.includes("//") || value.includes("\\")) return "/admin/vehicles";
  return value;
}

export default async function CanonicalJobPage({
  params,
  searchParams,
}: {
  params: Promise<{ batchKey: string }>;
  searchParams: Promise<{ dispatch?: string; return?: string; action?: string }>;
}) {
  const { batchKey } = await params;
  const query = await searchParams;
  const returnTo = safeAdminReturn(query.return);
  const actionLabel = query.action === "delete-trim" ? "กำลังลบรุ่นย่อย" : "กำลังบันทึกข้อมูลรถ";

  return <div className="adminEditor">
    <div className="adminHeader">
      <div>
        <small>CANONICAL VEHICLE JOB</small>
        <h1>{actionLabel}</h1>
        <p>หน้านี้ตามสถานะให้เอง ไม่ต้องกดรีเฟรช</p>
      </div>
      <Link className="adminPrimaryLink" href={returnTo}>← กลับหน้า Vehicle</Link>
    </div>

    <CanonicalBatchProgress
      batchKey={batchKey}
      dispatchStarted={query.dispatch === "started"}
      returnTo={returnTo}
      actionLabel={actionLabel}
    />
  </div>;
}
