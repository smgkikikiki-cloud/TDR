import Link from "next/link";
import { NavLinks } from "@/components/NavLinks";
import { MobileNav } from "@/components/MobileNav";
import { memberEntry } from "@/lib/navigation";

export function Header() {
  return (
    <header className="siteHeader siteHeaderV2">
      <div className="headerV2Row">
        <Link className="brandLockup headerV2Brand" href="/">
          <span className="tdrMark">THAILAND</span>
          <span className="brandText">DEVELOPMENT <b>REPORT</b></span>
          <span className="productTag">AUTOMOTIVE INTELLIGENCE</span>
        </Link>

        <div className="headerV2Nav"><NavLinks /></div>

        <form className="headerSearch headerV2Search" action="/search" role="search">
          <input name="q" placeholder="ค้นหารุ่นรถหรือแบรนด์" aria-label="ค้นหารุ่นรถหรือแบรนด์" />
          <button type="submit" aria-label="ค้นหา">
            <svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7"><circle cx="9" cy="9" r="6" /><path d="M13.5 13.5 17 17" /></svg>
          </button>
        </form>

        <Link className="headerAccount headerV2Account" href={memberEntry.href}>{memberEntry.label}</Link>
        <MobileNav />
      </div>
    </header>
  );
}
