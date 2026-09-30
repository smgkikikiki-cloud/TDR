import { Flag, TierBadge } from "@/components/design";
import { PROVINCE_PATHS, PROVINCE_VIEWBOX } from "@/components/home/province-paths";

/** The locked province probe (P01): a static, decorative ghost map, the locked-row list with tier badges, and the
 *  "coming soon" flag. The map carries geometry only, no values, so nothing real is in the DOM (DESIGN §10.5). */
export function ProvinceProbe() {
  return (
    <div className="tdr-home-probe" role="group" aria-label="ข้อมูลรายจังหวัด เร็วๆ นี้">
      <div className="tdr-home-probe__head"><b>ยอดจดรายจังหวัด</b><Flag kind="soon">เร็วๆ นี้</Flag></div>
      <div className="tdr-home-probe__body">
        <div className="tdr-home-ghostmap" aria-hidden="true">
          <svg viewBox={PROVINCE_VIEWBOX} className="tdr-home-map" focusable="false">
            {PROVINCE_PATHS.map(([name, d]) => <path key={name} d={d} className="tdr-region tdr-fill-map-2" />)}
          </svg>
        </div>
        <div className="tdr-home-pinfo">
          <div className="tdr-home-pname">{PROVINCE_PATHS.length} จังหวัด</div>
          <p className="tdr-home-muted">ยอดจดรายจังหวัด แยกเชื้อเพลิง รุ่นขายดี ขนาดล้อ และเบอร์ยาง กำลังจะเปิดให้ดูใน Automotive Intelligence</p>
          <div className="tdr-home-locked">
            <div className="tdr-home-lrow"><span>ยอดจดรายจังหวัด</span><TierBadge tier="free" locked label="ทดลองฟรี" /></div>
            <div className="tdr-home-lrow"><span>5 รุ่นขายดีในจังหวัด</span><TierBadge tier="free" locked label="ทดลองฟรี" /></div>
            <div className="tdr-home-lrow"><span>ขนาดล้อยอดนิยม</span><TierBadge tier="pro" locked /></div>
            <div className="tdr-home-lrow"><span>เบอร์ยางอันดับ 1</span><TierBadge tier="pro" locked /></div>
          </div>
        </div>
      </div>
      <div className="tdr-home-src">ข้อมูลรายจังหวัดจาก TDR Automotive Intelligence · เปิดเมื่อข้อมูลงวดแรกผ่านการยืนยัน</div>
    </div>
  );
}
