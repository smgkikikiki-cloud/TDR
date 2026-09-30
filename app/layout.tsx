import type { Metadata } from "next";
import "../design/tokens.css";
import "./globals.css";
import "./semantic-tokens.css";
import "./catalog-v12.css";
import "./storefront.css";
import "./model-trim-summary.css";
import "./compare.css";
import "./home-v2.css";
import "./home-polish.css";
import { designFontVariables } from "./fonts";
import { Header } from "@/components/Header";
import { Footer } from "@/components/Footer";
import { PublicChrome } from "@/components/PublicChrome";
import { NoCopyGuard } from "@/components/NoCopyGuard";

export const metadata: Metadata = {
  title: "TDR Automotive Intelligence",
  description: "ฐานข้อมูลการผลิตรถยนต์ โรงงาน รุ่นรถ บริษัท และข่าวอุตสาหกรรมยานยนต์ไทย",
};

// data-theme is pinned to light until the shell PR adds the theme toggle: the legacy app is
// light-only and tokens.css would otherwise switch color-scheme with the OS setting.
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="th" data-theme="light" className={designFontVariables}>
      <body>
        <NoCopyGuard />
        <div className="pageFrame">
          <PublicChrome><Header /></PublicChrome>
          <main>{children}</main>
          <PublicChrome><Footer /></PublicChrome>
        </div>
      </body>
    </html>
  );
}
