import Link from "next/link";

const reportSegments = [
  { segment: "B-SUV", title: "โครงสร้างตลาดตามแหล่งผลิต", note: "ผลิตไทย / CBU / ประเทศต้นทาง" },
  { segment: "C-SUV", title: "ส่วนแบ่งตลาดและการพึ่งพารถนำเข้า", note: "ยอดจดทะเบียนรายเดือนและสัดส่วนตามรุ่น" },
  { segment: "C-Sedan", title: "ส่วนแบ่งตามแบรนด์และ Powertrain", note: "ICE / HEV / PHEV / BEV" },
  { segment: "MPV", title: "ฐานการผลิต ASEAN และตลาดไทย", note: "ผลิตไทย / อินโดนีเซีย / ประเทศอื่น" },
  { segment: "Pickup", title: "ส่วนแบ่งรุ่นและฐานการผลิต", note: "ยอดจดทะเบียน การผลิต และการส่งออกที่เปิดเผย" },
  { segment: "Premium", title: "CBU / CKD และประเทศต้นทาง", note: "โครงสร้างตลาดรถพรีเมียมในประเทศไทย" },
];

function LockedChart({ index }: { index: number }) {
  return (
    <div className={`reportChart reportChart${(index % 3) + 1}`} aria-hidden="true">
      <div className="reportPie" />
      <div className="reportLegend">
        <span><i />••••••••</span>
        <span><i />••••••</span>
        <span><i />••••••••••</span>
      </div>
    </div>
  );
}

export default function ReportsPage() {
  return (
    <div className="reportsPage">
      <section className="reportsHero">
        <div>
          <div className="eyebrow">TDR REPORT</div>
          <h1>ตลาดรถไทย<br />ในแบบที่ตัวเลขเล่าเรื่องได้</h1>
          <p>
            รายงานเชิงลึกจากฐานข้อมูล TDR Automotive Intelligence — แยกตาม Segment,
            แหล่งผลิต, Powertrain และโครงสร้างตลาด พร้อมบทวิเคราะห์จาก Thailand Development Report
          </p>
        </div>
        <aside className="reportAccessBox">
          <small>MEMBER PREVIEW</small>
          <strong>ส่วนข้อมูลเชิงลึกกำลังเตรียมเปิดให้สมาชิก</strong>
          <p>ตอนนี้เปิดให้ดูโครงสร้างรายงานก่อน ตัวเลขเต็ม กราฟ และบทวิเคราะห์จะอยู่ใน TDR Report</p>
          <span>PAYWALL · COMING LATER</span>
        </aside>
      </section>

      <section className="reportFeature">
        <div className="reportFeatureCopy">
          <span className="reportTag">FEATURED REPORT</span>
          <h2>ตลาด C-SUV ไทยกำลังมาจากไหน?</h2>
          <p>
            เปรียบเทียบรถผลิตในประเทศกับ CBU แยกตามประเทศต้นทาง พร้อมสัดส่วนตลาดรายรุ่น
            และการเปลี่ยนแปลงตามช่วงเวลา
          </p>
          <div className="reportMeta">อัปเดตตามข้อมูลจดทะเบียนล่าสุด · TDR classification</div>
        </div>
        <div className="lockedReport">
          <div className="lockedContent">
            <div className="bigReportPie" />
            <div className="blurMetric"><b>••%</b><span>CBU จากประเทศต้นทางหลัก</span></div>
            <div className="blurMetric"><b>••%</b><span>ผลิตในประเทศไทย</span></div>
          </div>
          <div className="lockOverlay">
            <span>FULL DATA</span>
            <strong>ตัวเลขและกราฟฉบับเต็มสำหรับสมาชิก</strong>
            <small>ระบบสมาชิกจะเปิดภายหลัง</small>
          </div>
        </div>
      </section>

      <section className="reportsSection">
        <div className="reportsSectionHead">
          <div><small>MARKET BY SEGMENT</small><h2>รายงานแยกตาม Segment</h2></div>
          <p>โครงรายงานจะขยายตามฐานข้อมูลจริง โดยไม่บังคับให้ทุก Segment มี metric เหมือนกันทั้งหมด</p>
        </div>
        <div className="reportGrid">
          {reportSegments.map((item, index) => (
            <article className="reportCard" key={item.segment}>
              <div className="reportCardTop"><b>{item.segment}</b><span>LOCKED</span></div>
              <LockedChart index={index} />
              <h3>{item.title}</h3>
              <p>{item.note}</p>
              <div className="reportCardLock">ข้อมูลเต็มและบทวิเคราะห์ · สำหรับสมาชิกในอนาคต</div>
            </article>
          ))}
        </div>
      </section>

      <section className="analysisTeaser">
        <div>
          <small>TDR ANALYSIS</small>
          <h2>ไม่ใช่แค่กราฟ แต่คือสิ่งที่กราฟกำลังบอกเกี่ยวกับอุตสาหกรรม</h2>
        </div>
        <div className="analysisBlur">
          <p>การเปลี่ยนโครงสร้างของตลาดในช่วงที่ผ่านมาไม่ได้เกิดจากยอดขายของแบรนด์ใดแบรนด์หนึ่งเพียงอย่างเดียว แต่สะท้อนถึง...</p>
          <p>เมื่อแยกข้อมูลตามฐานการผลิต ภาพที่ปรากฏต่างจากการแบ่งตลาดตามสัญชาติของแบรนด์อย่างมีนัยสำคัญ...</p>
          <p>ผลกระทบต่อฐานการผลิตในประเทศไทยจึงต้องพิจารณาร่วมกับ...</p>
        </div>
        <div className="analysisLock">บทวิเคราะห์ฉบับเต็มจะเปิดใน TDR Report</div>
      </section>

      <section className="reportFreeBridge">
        <div><small>PUBLIC DATABASE</small><h2>ข้อมูลรถและฐานการผลิตทั่วไปยังเปิดดูได้ฟรี</h2></div>
        <div className="reportLinks">
          <Link href="/models">ดูรถทั้งหมด →</Link>
          <Link href="/plants">ดูฐานการผลิต →</Link>
          <Link href="/news">ข่าวอุตสาหกรรม →</Link>
        </div>
      </section>
    </div>
  );
}
