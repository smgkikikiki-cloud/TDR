import Link from "next/link";
import { primaryNav } from "@/lib/navigation";

export function Header() {
  return (
    <header className="siteHeader">
      <div className="topline">
        <Link className="brandLockup" href="/">
          <span className="tdrMark">THAILAND</span>
          <span className="brandText">DEVELOPMENT <b>REPORT</b></span>
          <span className="productTag">AUTOMOTIVE INTELLIGENCE</span>
        </Link>
        <div className="edition">ฐานข้อมูลอุตสาหกรรมยานยนต์ไทย · V0</div>
      </div>
      <div className="navline">
        <nav aria-label="เมนูหลัก">
          {primaryNav.map((item) => (
            <Link key={item.href} className={item.href === "/reports" ? "reportNavLink" : undefined} href={item.href}>{item.label}</Link>
          ))}
        </nav>
        <Link className="searchLink" href="/search">ค้นหา ⌕</Link>
      </div>
    </header>
  );
}
