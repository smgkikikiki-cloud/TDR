import Link from "next/link";

export function Footer() {
  return (
    <footer className="siteFooter">
      <div>
        <strong>Thailand Development Report — Automotive Intelligence</strong>
        <p>ฐานข้อมูลรถยนต์ การผลิต โรงงาน บริษัท และความเคลื่อนไหวของอุตสาหกรรมยานยนต์ไทย จากข้อมูลสาธารณะที่ตรวจสอบแหล่งที่มาได้</p>
      </div>
      <div className="footerNav">
        <div>
          <h3>แคตตาล็อก</h3>
          <Link href="/models">รถทุกรุ่น</Link>
          <Link href="/brands">แบรนด์</Link>
          <Link href="/search">ค้นหา</Link>
        </div>
        <div>
          <h3>ผลิตในไทย</h3>
          <Link href="/production">รุ่นที่ผลิตในไทย</Link>
          <Link href="/production?view=model">ดูตามรุ่น</Link>
          <Link href="/news">ข่าวอุตสาหกรรม</Link>
        </div>
        <div>
          <h3>ข้อมูลตลาด</h3>
          <Link href="/reports">TDR Report</Link>
          <Link href="/companies">บริษัท</Link>
          <Link href="/upcoming">รุ่นที่กำลังมา</Link>
        </div>
      </div>
    </footer>
  );
}
