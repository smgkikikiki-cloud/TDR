import Image from "next/image";
import Link from "next/link";
import { NavLinks } from "@/components/NavLinks";
import { MobileNav } from "@/components/MobileNav";
import { SearchOverlay } from "@/components/search/SearchOverlay";
import { ThemeToggle } from "@/components/ThemeToggle";
import { memberEntry, pricingEntry, signupEntry } from "@/lib/navigation";
import logoColor from "@/design/assets/brand/logo/tdr-logo-h-color@3x.png";
import logoReverse from "@/design/assets/brand/logo/tdr-logo-h-reverse@3x.png";

/** Site header (design/DESIGN.md §7, reference/home_v7.html). Logo, the four sections, search (P07),
 *  theme toggle, packages link, sign in, sign up; the burger takes over below 1024px. */
export function Header() {
  return (
    <header className="tdr-header">
      <div className="tdr-wrap tdr-header__row">
        <Link className="tdr-logo" href="/" aria-label="TDR หน้าแรก">
          {/* Official files only (brand guidelines v1.0): full colour on light, reverse on dark. CSS shows one of them. */}
          <Image className="tdr-logo__light" src={logoColor} alt="TDR Thailand Development Report" priority />
          <Image className="tdr-logo__dark" src={logoReverse} alt="" aria-hidden="true" />
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
