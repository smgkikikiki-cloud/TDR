import Link from "next/link";
import { Button } from "@/components/design";
import { MarketUpdating } from "@/components/home/states";
import { ProvinceProbe } from "@/components/home/ProvinceProbe";

/** Hero (PAGES P01). The market headline ("รถใหม่ X% เป็น EV แล้ว"), the KPI trio and the data period are
 *  computed from the latest market period, so they wait for the new engine (blocker 11): the headline falls back to
 *  the number-free line already on the live site, and the trio is a pending block. */
export function HomeHero() {
  return (
    <section className="tdr-home-hero" aria-labelledby="home-h1">
      <div className="tdr-home-hero__copy">
        <div className="tdr-eyebrow" lang="en">TDR Automotive Intelligence</div>
        <h1 id="home-h1" className="tdr-home-h1">ข้อมูลตลาด<br />รถยนต์ไทย</h1>
        <p className="tdr-home-lead">เห็นตลาดรถใหม่ทั้งประเทศในที่เดียว เจาะได้ถึงระดับจังหวัด รุ่น และเชื้อเพลิง ลึกไปจนถึงขนาดล้อและเบอร์ยาง อัปเดตทุกเดือน</p>
        <MarketUpdating title="ยอดจดทะเบียนรวมรายเดือน" />
        <div className="tdr-home-cta">
          <Button variant="accent" href="/member/login">เริ่มดูฟรี 30 วัน →</Button>
          <div className="tdr-home-reassure">✓ ไม่ต้องใช้บัตร &nbsp;·&nbsp; ✓ ยืนยันด้วยเบอร์โทร &nbsp;·&nbsp; ✓ ครบ 30 วันไม่ตัดเงิน</div>
        </div>
        <div className="tdr-home-alt">
          <span className="tdr-home-muted">หรือ</span>{" "}
          <Link className="tdr-home-altlink" href="/search">⌕ ค้นหารุ่นรถ สเปก และราคา</Link>{" "}
          <span className="tdr-home-muted">· ใช้ได้เลย ไม่ต้องสมัคร</span>
        </div>
      </div>
      <ProvinceProbe />
    </section>
  );
}
