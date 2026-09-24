import { notFound } from "next/navigation";
import { loadVehicleWorkspace } from "@/lib/canonical-editor";
import { setModelRetailState } from "@/app/admin/vehicle-lifecycle-actions";

export default async function VehicleLifecycleLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ modelId: string }>;
}) {
  const { modelId } = await params;
  const workspace = await loadVehicleWorkspace(modelId);
  if (!workspace) notFound();

  const historical = String(workspace.model.status || "").toUpperCase() === "HISTORICAL";

  return <>
    <div className="adminNotice">
      <b>สถานะการขาย: {historical ? "เลิกขาย / ARCHIVED" : "ขายอยู่ / CURRENT"}</b>
      <span>
        ระบบถือรถใน catalog ว่ายังขายอยู่โดย default เพื่อให้ price updater ไล่หาราคาต่อ
        จนกว่าจะปิดรุ่นนี้เอง
      </span>
      <form action={setModelRetailState} className="adminInlineForm">
        <input type="hidden" name="model_id" value={modelId} />
        <input type="hidden" name="page_release_id" value={workspace.releaseId} />
        <input type="hidden" name="retail_status" value={historical ? "CURRENT" : "HISTORICAL"} />
        <button>{historical ? "นำรุ่นนี้กลับมาขาย" : "เลิกขายรุ่นนี้"}</button>
      </form>
    </div>
    {children}
  </>;
}
