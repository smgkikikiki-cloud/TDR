import Link from "next/link";
import { NavLinks } from "@/components/NavLinks";
import { reportCta } from "@/lib/navigation";

export function Header() {
  return (
    <header className="siteHeader">
      <div className="topline">
        <Link className="brandLockup" href="/">
          <span className="tdrMark">THAILAND</span>
          <span className="brandText">DEVELOPMENT <b>REPORT</b></span>
          <span className="productTag">AUTOMOTIVE INTELLIGENCE</span>
        </Link>
        <Link className="sfCta" href={reportCta.href}>
          <svg width="13" height="13" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><rect x="2.5" y="6" width="9" height="6" /><path d="M4.5 6V4a2.5 2.5 0 0 1 5 0v2" /></svg>
          <span><b>{reportCta.label}</b><em>ข้อมูลตลาดสำหรับสมาชิก</em></span>
        </Link>
      </div>
      <div className="navline">
        <NavLinks />
        <form className="headerSearch" action="/search" role="search">
          <input name="q" placeholder="ค้นหารุ่นรถ แบรนด์ โรงงาน" aria-label="ค้นหาฐานข้อมูล" />
          <button type="submit" aria-label="ค้นหา">
            <svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7"><circle cx="9" cy="9" r="6" /><path d="M13.5 13.5 17 17" /></svg>
          </button>
        </form>
      </div>
    </header>
  );
}
