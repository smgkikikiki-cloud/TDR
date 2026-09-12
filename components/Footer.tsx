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
          <Link href="/upcoming">รุ่นที่กำลังมา</Link>
        </div>
        <div>
          <h3>Market Intelligence</h3>
          <Link href="/market">ข้อมูลตลาด</Link>
          <Link href="/compare">เทียบรถ</Link>
          <Link href="/news">บทวิเคราะห์</Link>
        </div>
        <div>
          <h3>บัญชีและแพ็กเกจ</h3>
          <Link href="/pricing">ดูแพ็กเกจ</Link>
          <Link href="/companies">บริษัท</Link>
          <Link href="/member/login">เข้าสู่ระบบ</Link>
        </div>
      </div>
    </footer>
  );
}
