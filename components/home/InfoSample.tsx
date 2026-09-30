import { TierBadge } from "@/components/design";
import { MarketUpdating } from "@/components/home/states";

/** Info & Top 10 (PAGES P01). The sample Top 5 is built from registrations by model, so it waits for the new market
 *  engine (blocker 11); the copy and the locked tier badges are static. */
export function InfoSample() {
  return (
    <section className="tdr-home-blk" aria-labelledby="home-info">
      <div className="tdr-wrap tdr-home-info">
        <div>
          <div className="tdr-eyebrow" lang="en">Info &amp; Top 10</div>
          <h2 id="home-info" className="tdr-home-h2 tdr-home-h2--ink">สร้าง Info พร้อมใช้ <span className="tdr-home-hl">จากตัวเลขที่คุณเลือก</span></h2>
          <ul className="tdr-home-list">
            <li>การ์ดโซเชียล · สรุป A4 · Top 10 (รุ่น / แบรนด์ · จังหวัดและเบอร์ยางเร็วๆ นี้)</li>
            <li>ส่งออก PNG / PDF พร้อมลายน้ำชื่อผู้ใช้และรหัสไฟล์</li>
            <li>ส่งออก CSV แยกตาม Panel สำหรับ Enterprise</li>
          </ul>
          <div className="tdr-home-badges"><TierBadge tier="pro" locked /><TierBadge tier="enterprise" locked label="Enterprise · CSV" /></div>
        </div>
        <div aria-label="ตัวอย่าง Info Top 5" role="group">
          <MarketUpdating title="Top 5 รุ่นจดทะเบียน" />
        </div>
      </div>
    </section>
  );
}
