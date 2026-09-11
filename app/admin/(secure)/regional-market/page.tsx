import Link from "next/link";

export default function RegionalMarketPage() {
  return <div className="adminEditor">
    <div className="adminHeader">
      <div>
        <small>ADMIN BENCH · REGIONAL MARKET</small>
        <h1>ยอดจดทะเบียนรายจังหวัด</h1>
        <p>Top provinces · Regional mix · Geographic over-index · Competitive position by province</p>
      </div>
      <Link className="adminPrimaryLink" href="/admin/market">กลับ Full Market Bench</Link>
    </div>

    <div className="adminNotice">
      <b>COMING SOON — ยังไม่มีข้อมูลจริงให้แสดง</b>
      <span>
        เช็คแล้ว: ไฟล์ DLT raw ที่ ingest อยู่ตอนนี้ (dlt_YYYY-MM.csv) ไม่มีคอลัมน์จังหวัดเลยตั้งแต่ต้น — เป็นข้อมูลระดับประเทศเท่านั้น
        ไม่ใช่แค่ยังไม่ export. Registration warehouse เองก็ยังไม่เคยรับข้อมูลระดับจังหวัดจริงเลย (province เป็นค่า default &apos;ALL&apos; เท่านั้น).
        ตามที่ <code>/admin/data-quality</code> บันทึกไว้: &quot;Private provincial workbook is not available in the active repository/library&quot;
        — มีไฟล์นี้อยู่ที่ไหนสักที่แล้ว แต่ยังไม่ถูกนำเข้า repo
      </span>
    </div>

    <div className="adminNotice">
      <b>ต้องมีอะไรก่อนหน้านี้จะใช้งานได้จริง</b>
      <span>
        1) ไฟล์ข้อมูลจดทะเบียนระดับจังหวัด (DLT provincial breakdown) —
        2) เพิ่มคอลัมน์ province ให้ TDR&apos;s <code>registrations</code> table (Supabase) —
        3) ต่อ export/ingest pipeline ให้พาข้อมูลจังหวัดมาด้วย —
        4) ค่อยกลับมาเปิดหน้านี้จริง
      </span>
    </div>
  </div>;
}
