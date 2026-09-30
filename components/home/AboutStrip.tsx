import Link from "next/link";

export function AboutStrip() {
  return (
    <section className="tdr-home-blk" aria-labelledby="home-about">
      <div className="tdr-wrap tdr-home-about">
        <div><div className="tdr-eyebrow" lang="en">About TDR</div><h2 id="home-about" className="tdr-home-h2 tdr-home-h2--ink">Thailand Development Report</h2></div>
        <p className="tdr-home-muted">TDR วิเคราะห์การพัฒนาเศรษฐกิจและโครงสร้างพื้นฐานของไทย จากข้อมูลภาครัฐที่ตรวจสอบย้อนกลับได้ · <Link href="/about">เกี่ยวกับ TDR</Link> · <Link href="/contact">ติดต่อเรา</Link></p>
      </div>
    </section>
  );
}
