import Link from "next/link";
import { NavLinks } from "@/components/NavLinks";
import { MobileNav } from "@/components/MobileNav";
import { memberEntry } from "@/lib/navigation";

export function Header() {
  return (
    <header className="siteHeader">
      <div className="topline">
        <Link className="brandLockup" href="/">
          <span className="tdrMark">THAILAND</span>
          <span className="brandText">DEVELOPMENT <b>REPORT</b></span>
          <span className="productTag">AUTOMOTIVE INTELLIGENCE</span>
        </Link>
        {/* A padlock in a box advertising a section that is already in the nav
            is decoration. The only thing a header needs on the right is the
            way into an account. */}
        <Link className="headerAccount" href={memberEntry.href}>{memberEntry.label}</Link>
        {/* Below 700px the nav row is replaced by this drawer: a scrollable
            row gives no hint that more sections exist off-screen. */}
        <MobileNav />
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
