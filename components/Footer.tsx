import Image from "next/image";
import Link from "next/link";
import logo from "@/design/assets/brand/tdr-logo-full.png";

/** Site footer (design/DESIGN.md §7, reference/home_v7.html): inverse surface, logo on a
 *  white plate, the six legal/site links, and the data source line. */
export function Footer() {
  return (
    <footer className="tdr-footer">
      <div className="tdr-wrap tdr-footer__row">
        <span className="tdr-footer__logo"><Image src={logo} alt="TDR Automotive Intelligence" /></span>
        <nav aria-label="ลิงก์ท้ายเว็บ">
          <Link href="/about">เกี่ยวกับ TDR</Link>
          <Link href="/contact">ติดต่อเรา</Link>
          <Link href="/pricing">แพ็กเกจ</Link>
          <Link href="/news">ข่าวและการเปลี่ยนแปลง</Link>
          <Link href="/terms">เงื่อนไขการใช้บริการ</Link>
          <Link href="/privacy">นโยบายความเป็นส่วนตัว</Link>
        </nav>
        <span className="tdr-footer__src">ข้อมูลยอดจดทะเบียน: กรมการขนส่งทางบก (Open Data Common)</span>
      </div>
    </footer>
  );
}
