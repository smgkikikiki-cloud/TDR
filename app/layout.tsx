import type { Metadata } from "next";
import "../design/tokens.css";
import "../design/components.css";
import "./globals.css";
import "./semantic-tokens.css";
import "./catalog-v12.css";
import "./storefront.css";
import "./model-trim-summary.css";
import "./compare.css";
import "./home-v2.css";
import "./home-polish.css";
import "./shell.css";
import { designFontVariables } from "./fonts";
import { Header } from "@/components/Header";
import { Footer } from "@/components/Footer";
import { BottomBar } from "@/components/BottomBar";
import { PublicChrome } from "@/components/PublicChrome";
import { NoCopyGuard } from "@/components/NoCopyGuard";

export const metadata: Metadata = {
  title: "TDR Automotive Intelligence",
  description: "ฐานข้อมูลการผลิตรถยนต์ โรงงาน รุ่นรถ บริษัท และข่าวอุตสาหกรรมยานยนต์ไทย",
};

// Applies a stored theme choice before first paint (no flash). With no stored choice <html> has no
// data-theme and tokens.css follows prefers-color-scheme; components/ThemeToggle.tsx writes the choice.
const themeScript = `try{var t=localStorage.getItem("tdr-theme");if(t==="dark"||t==="light")document.documentElement.dataset.theme=t}catch(e){}`;

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="th" className={designFontVariables} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body>
        <NoCopyGuard />
        <PublicChrome><Header /></PublicChrome>
        <div className="pageFrame">
          <main>{children}</main>
        </div>
        <PublicChrome><Footer /><BottomBar /></PublicChrome>
      </body>
    </html>
  );
}
