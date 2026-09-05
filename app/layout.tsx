import type { Metadata } from "next";
import "./globals.css";
import "./catalog-v12.css";
import "./storefront.css";
import { Header } from "@/components/Header";
import { Footer } from "@/components/Footer";
import { PublicChrome } from "@/components/PublicChrome";

export const metadata: Metadata = {
  title: "TDR Automotive Intelligence",
  description: "ฐานข้อมูลการผลิตรถยนต์ โรงงาน รุ่นรถ บริษัท และข่าวอุตสาหกรรมยานยนต์ไทย",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="th">
      <body>
        <div className="pageFrame">
          <PublicChrome><Header /></PublicChrome>
          <main>{children}</main>
          <PublicChrome><Footer /></PublicChrome>
        </div>
      </body>
    </html>
  );
}
