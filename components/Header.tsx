import Link from "next/link";
import { NavLinks } from "@/components/NavLinks";
import { loginCta, pricingCta } from "@/lib/navigation";

export function Header() {
  return (
    <header className="siteHeader saasHeader">
      <div className="saasHeaderRow">
        <Link className="brandLockup" href="/">
          <span className="tdrMark">THAILAND</span>
          <span className="brandText">DEVELOPMENT <b>REPORT</b></span>
          <span className="productTag">AUTOMOTIVE INTELLIGENCE</span>
        </Link>

        <div className="saasHeaderNav">
          <NavLinks />
        </div>

        <div className="saasHeaderActions">
          <Link className="saasLogin" href={loginCta.href}>{loginCta.label}</Link>
          <Link className="saasPricing" href={pricingCta.href}>{pricingCta.label}</Link>
        </div>
      </div>
    </header>
  );
}
