import { listResearchFiles } from "@/lib/research-files";
import {
  deleteResearchFileAction, openResearchFileAction, renameResearchFileAction,
  uploadResearchFileAction,
} from "@/app/admin/research-file-actions";

export const dynamic = "force-dynamic";

function size(bytes: number | null) {
  if (!bytes) return "—";
  const mb = bytes / (1024 * 1024);
  return mb >= 1 ? `${mb.toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

export default async function ResearchFilesPage() {
  const files = await listResearchFiles();

  return <div className="adminEditor">
    <div className="adminHeader">
      <div>
        <small>RESEARCH FILES</small>
        <h1>ไฟล์งานวิจัยภายใน</h1>
        <p>ที่เก็บไฟล์ของทีม — PDF, สเปรดชีต, เด็ค. ไม่เกี่ยวกับบทวิเคราะห์ที่เผยแพร่บนเว็บ</p>
      </div>
    </div>

    <form action={uploadResearchFileAction} className="adminForm">
      <label className="adminField adminFieldWide">
        <span>อัปโหลดไฟล์ (สูงสุด 50 MB)</span>
        <input name="file" type="file" required />
      </label>
      <div className="adminFormActions"><button className="adminPrimary">อัปโหลด</button></div>
    </form>

    <div className="libraryTable"><table>
      <thead><tr><th>ชื่อไฟล์</th><th>ขนาด</th><th>แก้ไขล่าสุด</th><th>เปลี่ยนชื่อ</th><th></th></tr></thead>
      <tbody>
        {files.length ? files.map((file) => <tr key={file.name}>
          <td>
            <form action={openResearchFileAction}>
              <input type="hidden" name="name" value={file.name} />
              <button className="adminLinkButton"><b>{file.name}</b></button>
            </form>
          </td>
          <td>{size(file.sizeBytes)}</td>
          <td>{file.updatedAt ? new Date(file.updatedAt).toLocaleString("th-TH") : "—"}</td>
          <td>
            <form action={renameResearchFileAction} className="adminInlineForm">
              <input type="hidden" name="name" value={file.name} />
              <input name="new_name" type="text" defaultValue={file.name} aria-label={`ชื่อใหม่ของ ${file.name}`} />
              <button>เปลี่ยนชื่อ</button>
            </form>
          </td>
          <td>
            <form action={deleteResearchFileAction}>
              <input type="hidden" name="name" value={file.name} />
              <button>ลบ</button>
            </form>
          </td>
        </tr>) : <tr><td colSpan={5}>ยังไม่มีไฟล์</td></tr>}
      </tbody>
    </table></div>
  </div>;
}
