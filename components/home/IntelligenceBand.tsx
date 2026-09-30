import Link from "next/link";
import { Button, Card, Flag } from "@/components/design";
import { MarketUpdating } from "@/components/home/states";
import { PROVINCE_PATHS } from "@/components/home/province-paths";

const PROVINCES = PROVINCE_PATHS.length;

const PANELS = [
  { n: "PANEL 1", title: "ยอดจดรายจังหวัด", text: `เชื้อเพลิง · ${PROVINCES} จังหวัด`, soon: true },
  { n: "PANEL 2", title: "ขนาดล้อ", text: "ขอบ ≤14 ถึง 21+ นิ้ว · ประมาณการ", soon: true },
  { n: "PANEL 3", title: "เบอร์ยาง", text: "รายเบอร์ รายจังหวัด · ประมาณการ", soon: true },
  { n: "PANEL 4", title: "แนวโน้ม", text: "YoY · MoM · YTD รายรุ่น", soon: true },
] as const;

/** Intelligence band (PAGES P01): the five Panel cards plus the trend, powertrain and brand-share cards. Panels 1-4 are
 *  "coming soon" until the Ice import; Panel 5 links to today's market page. The three market cards wait for the new
 *  engine (blocker 11) and render their approved titles as pending blocks, with no figures. */
export function IntelligenceBand() {
  return (
    <section className="tdr-home-band" aria-labelledby="home-intel">
      <div className="tdr-wrap">
        <div className="tdr-home-band__top">
          <div>
            <div className="tdr-eyebrow tdr-home-on-inverse" lang="en">TDR Automotive Intelligence</div>
            <h2 id="home-intel" className="tdr-home-h2">ยอดจดทะเบียน <span className="tdr-home-nw">ขนาดล้อ</span> และ<span className="tdr-home-nw">เบอร์ยาง</span> <span className="tdr-home-nw">รายจังหวัด</span></h2>
            <p className="tdr-home-on-inverse-muted">ข้อมูลตั้งแต่ ม.ค. 2564 อัปเดตทุกเดือน เลือกหลายเดือน หลายแบรนด์ และเทียบข้ามปีได้ · ทุก Panel แยกข้อมูลกัน ไม่ผสมข้าม Panel</p>
            <div className="tdr-home-band__cta">
              <Button variant="secondary" className="tdr-home-inv" href="/market">เปิด Automotive Intelligence ↗</Button>
              <Button variant="secondary" className="tdr-home-inv-outline" href="/pricing">ดูแพ็กเกจ</Button>
            </div>
          </div>
          <div className="tdr-home-panels">
            {PANELS.map((p) => (
              <Link key={p.n} href="/market" className="tdr-home-panel">
                <span className="tdr-home-panel__n">{p.n}<Flag kind="soon">เร็วๆ นี้</Flag></span>
                <b>{p.title}</b>
                <small>{p.text}</small>
              </Link>
            ))}
            <Link href="/market" className="tdr-home-panel tdr-home-panel--p5">
              <span className="tdr-home-panel__n">PANEL 5<span className="tdr-tier tdr-tier--free">Freemium ✓</span></span>
              <b>ส่วนแบ่งตลาด</b>
              <small>แบรนด์ · ระบบขับเคลื่อน · ตัวถัง · Segment · รายรุ่น (Pro)</small>
            </Link>
          </div>
        </div>

        <div className="tdr-home-band__grid">
          <Card tone="dashed" className="tdr-home-pending">
            <div className="tdr-card__head"><b className="tdr-card__title">ยอดจดรายจังหวัด</b><Flag kind="soon">เร็วๆ นี้</Flag></div>
            <p className="tdr-home-muted">แผนที่ {PROVINCES} จังหวัด แยกเชื้อเพลิงและรุ่น จะเปิดใน Panel 1</p>
          </Card>
          <div className="tdr-home-stack">
            <MarketUpdating title="ยอดจดทะเบียนรวมรายเดือน" />
            <MarketUpdating title="สัดส่วนระบบขับเคลื่อน" />
          </div>
          <div className="tdr-home-stack">
            <MarketUpdating title="ส่วนแบ่งแบรนด์" />
            <Link className="tdr-home-more" href="/market">เปิด Panel 5 ส่วนแบ่งตลาด →</Link>
          </div>
        </div>

        <div className="tdr-home-trial">
          <div><b>ทดลองฟรี 30 วัน</b> <span className="tdr-home-on-inverse-muted">· เลือกมุมมองได้ 1 แบบ งวดล่าสุด</span></div>
          <div className="tdr-home-trial__opts"><span>รายจังหวัด</span><span>20 รุ่นแรก</span><span>สัดส่วนเชื้อเพลิง</span></div>
          <Button variant="secondary" className="tdr-home-inv" href="/member/login">เริ่มทดลองฟรี</Button>
        </div>
        <div className="tdr-home-src tdr-home-on-inverse-muted">ที่มา: กรมการขนส่งทางบก (Open Data Common) · ค่าล้อ/ยางเป็นประมาณการ แสดงสัดส่วนที่ครอบคลุมทุกครั้ง</div>
      </div>
    </section>
  );
}
