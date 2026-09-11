import Link from "next/link";
import styles from "./pricing.module.css";

const comparison = [
  { label: "แคทตาล็อกรถยนต์ รุ่นย่อย ราคา และสเปกพื้นฐาน", free: "yes", pro: "yes", enterprise: "yes" },
  { label: "เทียบรถ", free: "yes", pro: "yes", enterprise: "yes" },
  { label: "บทวิเคราะห์พื้นฐาน", free: "yes", pro: "yes", enterprise: "yes" },
  { label: "ยอดจดทะเบียนรายรุ่น", free: "no", pro: "yes", enterprise: "yes" },
  { label: "ส่วนแบ่งตลาด (Market Share)", free: "no", pro: "yes", enterprise: "yes" },
  { label: "การเปลี่ยนแปลงตลาด (MoM / YoY)", free: "no", pro: "yes", enterprise: "yes" },
  { label: "ดูตามแบรนด์ รุ่น เซกเมนต์ ตัวถัง ระบบขับเคลื่อน", free: "no", pro: "yes", enterprise: "yes" },
  { label: "แนวโน้มย้อนหลัง 3 / 6 / 12 เดือน และ YTD", free: "no", pro: "yes", enterprise: "yes" },
  { label: "ส่งออกข้อมูล (CSV)", free: "no", pro: "yes", enterprise: "yes" },
  { label: "ติดตามตารางเปิดตัวรถใหม่ล่วงหน้า", free: "no", pro: "soon", enterprise: "soon" },
  { label: "หลายบัญชีสำหรับทีม", free: "no", pro: "no", enterprise: "custom" },
  { label: "ขอบเขตข้อมูล / รายงานสำหรับองค์กร", free: "no", pro: "no", enterprise: "custom" },
];

type State = "yes" | "no" | "soon" | "custom";

function Cell({ state }: { state: State }) {
  if (state === "yes") return <span className={styles.yes}>✓</span>;
  if (state === "soon") return <span className={styles.soon}>เร็วๆ นี้</span>;
  if (state === "custom") return <span className={styles.custom}>ตามข้อตกลง</span>;
  return <span className={styles.no}>—</span>;
}

function Bullet({ children, muted = false }: { children: React.ReactNode; muted?: boolean }) {
  return <li className={muted ? styles.mutedFeature : undefined}><span>{muted ? "○" : "✓"}</span>{children}</li>;
}

export default function PricingPage() {
  return (
    <div className={styles.page}>
      <section className={styles.hero}>
        <div className={styles.heroCopy}>
          <div className={styles.eyebrow}>PRICING</div>
          <h1>ข้อมูลตลาดรถ ที่คุณใช้ตัดสินใจได้จริง</h1>
          <p>เลือกตั้งแต่ข้อมูลรถและเครื่องมือพื้นฐานแบบฟรี ไปจนถึง Market Intelligence สำหรับดูยอดจดทะเบียน ส่วนแบ่งตลาด และแนวโน้มย้อนหลัง</p>
          <div className={styles.trustRow}>
            <div><b>ข้อมูลจดทะเบียน</b><span>เชื่อมกับข้อมูลตลาดที่ TDR รองรับ</span></div>
            <div><b>อัปเดตต่อเนื่อง</b><span>ออกแบบสำหรับการติดตามรายเดือน</span></div>
            <div><b>ฐานข้อมูลรถชุดเดียวกัน</b><span>เชื่อม Market Intelligence กับ Vehicle Master</span></div>
          </div>
        </div>
        <div className={styles.heroVisual} aria-hidden="true">
          <div className={styles.skyline}><i /><i /><i /><i /></div>
          <div className={styles.road}>
            {Array.from({ length: 5 }, (_, index) => <span key={index}><b /></span>)}
          </div>
          <strong>มากกว่าตัวเลข<br />คือมุมมองที่ตัดสินใจได้</strong>
        </div>
      </section>

      <section className={styles.plans} aria-label="แพ็กเกจ TDR">
        <article className={styles.planCard}>
          <div className={styles.planTop}>
            <div><h2>Free</h2><p>เริ่มต้นใช้งาน</p></div>
          </div>
          <div className={styles.price}><strong>฿0</strong><span>/ เดือน</span></div>
          <p className={styles.planDescription}>เข้าถึงฐานข้อมูลรถและเครื่องมือหลักสำหรับผู้ใช้งานทั่วไป</p>
          <Link className={styles.freeCta} href="/models">เริ่มใช้งานฟรี</Link>
          <ul>
            <Bullet>แคทตาล็อกรถยนต์</Bullet>
            <Bullet>เทียบรถ</Bullet>
            <Bullet>บทวิเคราะห์พื้นฐาน</Bullet>
            <Bullet muted>ยอดจดทะเบียนรายรุ่น</Bullet>
            <Bullet muted>ส่วนแบ่งตลาด</Bullet>
            <Bullet muted>แนวโน้มตลาดย้อนหลัง</Bullet>
            <Bullet muted>ส่งออกข้อมูล CSV</Bullet>
          </ul>
        </article>

        <article className={`${styles.planCard} ${styles.proCard}`}>
          <div className={styles.recommended}>แนะนำ</div>
          <div className={styles.planTop}>
            <div><h2>Market Intelligence<br />(TDR Pro)</h2><p>สำหรับคนที่ต้องการข้อมูลเชิงลึก</p></div>
          </div>
          <div className={styles.price}><strong>฿990</strong><span>/ เดือน</span></div>
          <div className={styles.annual}>หรือ <b>฿8,790 / ปี</b> <span>ประหยัด 26%</span></div>
          <p className={styles.planDescription}>เครื่องมือวิเคราะห์ตลาดสำหรับติดตามอันดับ ส่วนแบ่ง และความเคลื่อนไหวของตลาดรถไทย</p>
          <Link className={styles.proCta} href="/member/login?mode=signup">สมัครสมาชิก</Link>
          <ul>
            <Bullet>ทุกฟีเจอร์ใน Free</Bullet>
            <Bullet>ยอดจดทะเบียนรายรุ่น</Bullet>
            <Bullet>ส่วนแบ่งตลาด (Market Share)</Bullet>
            <Bullet>การเปลี่ยนแปลงตลาด (MoM / YoY)</Bullet>
            <Bullet>ดูตามแบรนด์ รุ่น เซกเมนต์ ตัวถัง และระบบขับเคลื่อน</Bullet>
            <Bullet>แนวโน้มย้อนหลัง 3 / 6 / 12 เดือน และ YTD</Bullet>
            <Bullet>ส่งออกข้อมูล CSV</Bullet>
            <li className={styles.soonFeature}><span>◉</span>ติดตามตารางเปิดตัวรถใหม่ล่วงหน้า <em>เร็วๆ นี้</em></li>
          </ul>
        </article>

        <article className={styles.planCard}>
          <div className={styles.planTop}>
            <div><h2>Enterprise</h2><p>สำหรับองค์กร</p></div>
          </div>
          <div className={`${styles.price} ${styles.enterprisePrice}`}><strong>ติดต่อทีมงาน</strong></div>
          <p className={styles.planDescription}>แพ็กเกจสำหรับทีมที่ต้องการสิทธิ์หลายบัญชี ขอบเขตข้อมูล หรือรูปแบบรายงานที่กำหนดร่วมกัน</p>
          <a className={styles.enterpriseCta} href="mailto:thdevelopmentreport@gmail.com">ติดต่อเรา</a>
          <ul>
            <Bullet>ทุกฟีเจอร์ใน TDR Pro</Bullet>
            <Bullet>กำหนดจำนวนบัญชีสำหรับทีม</Bullet>
            <Bullet>กำหนดขอบเขตข้อมูลและรายงานตามองค์กร</Bullet>
            <Bullet>ประสานงานกับทีม TDR โดยตรง</Bullet>
          </ul>
          <div className={styles.emailBlock}>
            <span>อีเมลติดต่อ</span>
            <a href="mailto:thdevelopmentreport@gmail.com">thdevelopmentreport@gmail.com</a>
          </div>
        </article>
      </section>

      <section className={styles.comparison} id="compare">
        <div className={styles.sectionHead}>
          <div className={styles.eyebrow}>COMPARE</div>
          <h2>เปรียบเทียบฟีเจอร์</h2>
        </div>
        <div className={styles.tableWrap}>
          <table>
            <thead><tr><th>ฟีเจอร์</th><th>Free</th><th>Market Intelligence (TDR Pro)</th><th>Enterprise</th></tr></thead>
            <tbody>
              {comparison.map((row) => (
                <tr key={row.label}>
                  <td>{row.label}</td>
                  <td><Cell state={row.free as State} /></td>
                  <td><Cell state={row.pro as State} /></td>
                  <td><Cell state={row.enterprise as State} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
