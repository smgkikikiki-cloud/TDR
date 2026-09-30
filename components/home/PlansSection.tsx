import { Button, TierBadge } from "@/components/design";

/** Plans (PAGES P01). The prices and the savings line are the owner's approved copy (docs/MERGE_DECISIONS.md, DESIGN §10),
 *  not read from lib/plans.ts: that file still holds the old prices until its own PR (blocker 4). Enterprise shows no
 *  price and no phone, and its button is the navy "Contact →". */
export function PlansSection() {
  return (
    <section className="tdr-home-blk" aria-labelledby="home-plans">
      <div className="tdr-wrap">
        <div className="tdr-home-head">
          <div>
            <div className="tdr-eyebrow">แพ็กเกจ</div>
            <h2 id="home-plans" className="tdr-home-h2 tdr-home-h2--ink">เลือกระดับที่เหมาะกับงานของคุณ</h2>
          </div>
          <span className="tdr-home-src">ราคารวม VAT 7%</span>
        </div>
        <div className="tdr-home-plans">
          <article className="tdr-home-plan">
            <TierBadge tier="free" label="Freemium" />
            <h3>ทดลองฟรี 30 วัน</h3>
            <div className="tdr-home-price tdr-home-price--free">฿0</div>
            <ul><li>งวดล่าสุด เลือกมุมมองได้ 1 แบบ</li><li>จังหวัด / 20 รุ่นแรก / เชื้อเพลิง</li><li>ไม่มีส่งออก · มีลายน้ำ</li><li>1 เบอร์โทร = 1 สิทธิ์ทดลอง</li></ul>
            <Button variant="secondary" href="/member/login">เริ่มทดลองฟรี</Button>
          </article>
          <article className="tdr-home-plan tdr-home-plan--hl">
            <TierBadge tier="pro" />
            <h3>ใช้ครบทุก Panel</h3>
            <div className="tdr-home-price">฿1,099<small>/ เดือน</small></div>
            <span className="tdr-home-muted tdr-home-sm">หรือ <b className="tdr-home-mono">฿11,490</b> / ปี · <span className="tdr-home-save">ประหยัด 12.9%</span> · เฉลี่ย <span className="tdr-home-mono">฿958</span>/เดือน</span>
            <ul><li>ทุก Panel ย้อนหลังตั้งแต่ ม.ค. 2564</li><li>เทียบปีก่อน · เดือนก่อน · YTD</li><li>สร้าง Info PNG/PDF + Top 10</li></ul>
            <Button variant="accent" href="/pricing">อัปเกรดเป็น Pro</Button>
          </article>
          <article className="tdr-home-plan">
            <TierBadge tier="enterprise" />
            <h3>สำหรับองค์กร</h3>
            <div className="tdr-home-price tdr-home-price--ent">ติดต่อทีม TDR</div>
            <span className="tdr-home-muted tdr-home-sm">2 บัญชีผู้ใช้ · ราคาตามการใช้งานของแต่ละองค์กร</span>
            <ul><li>ทุกสิทธิ์ของ Pro</li><li>ส่งออก CSV แยกตาม Panel</li><li>คุยกับทีม TDR เพื่อออกแบบแพ็กเกจ</li></ul>
            <Button variant="contact" href="/contact?topic=enterprise">Contact →</Button>
          </article>
        </div>
      </div>
    </section>
  );
}
