import Image from "next/image";
import Link from "next/link";
import { NavLinks } from "@/components/NavLinks";
import { MobileNav } from "@/components/MobileNav";
import { SearchOverlay } from "@/components/search/SearchOverlay";
import { ThemeToggle } from "@/components/ThemeToggle";
import { memberEntry, pricingEntry, signupEntry } from "@/lib/navigation";
import logo from "@/design/assets/brand/tdr-logo-full.png";

/** Site header (design/DESIGN.md §7, reference/home_v7.html). Logo, the four sections, search (P07),
 *  theme toggle, packages link, sign in, sign up; the burger takes over below 1024px. */
export function Header() {
  return (
    <header className="tdr-header">
      <div className="tdr-wrap tdr-header__row">
        <Link className="tdr-logo" href="/" aria-label="TDR หน้าแรก">
          <Image src={logo} alt="TDR Automotive Intelligence" priority />
        </Link>
        <NavLinks />
        <div className="tdr-acts">
          <SearchOverlay />
          <ThemeToggle className="tdr-icon-btn tdr-theme" />
          <Link className="tdr-btn tdr-btn--ghost tdr-pk" href={pricingEntry.href}>{pricingEntry.label}</Link>
          <Link className="tdr-btn tdr-btn--secondary tdr-login" href={memberEntry.href}>{memberEntry.label}</Link>
          <Link className="tdr-btn tdr-signup" href={signupEntry.href}>{signupEntry.label}</Link>
          <MobileNav />
        </div>
      </div>
    </header>
  );
}
