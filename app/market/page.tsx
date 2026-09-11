import Link from "next/link";
import styles from "./market-public.module.css";

const rows = Array.from({ length: 8 }, (_, index) => index + 1);

export default function PublicMarketPage() {
  return (
    <div className={styles.page}>
      <header className={styles.intro}>
        <div className={styles.eyebrow}>TDR REPORT · SALES INTELLIGENCE</div>
        <h1>Market Intelligence</h1>
        <p>สำรวจยอดจดทะเบียน ส่วนแบ่งตลาด อันดับ และการเคลื่อนไหวของตลาดรถไทยใน workspace เดียว</p>
      </header>

      <section className={styles.workspace} aria-label="ตัวอย่าง Market Intelligence">
        <div className={styles.workspaceHead}>
          <div>
            <span>MARKET WORKSPACE</span>
            <strong>ภาพรวมตลาดรถยนต์ประเทศไทย</strong>
          </div>
          <button type="button" disabled>ส่งออกข้อมูล</button>
        </div>

        <div className={styles.filters} aria-hidden="true">
          <div><small>เดือน</small><b>เลือกช่วงข้อมูล</b><span>⌄</span></div>
          <div><small>ช่วงเวลา</small><b>เดือน / 3M / 6M / 12M / YTD</b><span>⌄</span></div>
          <div><small>มิติข้อมูล</small><b>แบรนด์ / รุ่น / Segment / Powertrain</b><span>⌄</span></div>
        </div>

        <div className={styles.tabs} aria-hidden="true">
          <b>ส่วนแบ่งตลาด</b>
          <span>ยอดจดทะเบียน</span>
          <span>การเปลี่ยนแปลง</span>
          <span>แนวโน้มรายเดือน</span>
        </div>

        <div className={styles.tablePreview} aria-hidden="true">
          <div className={`${styles.row} ${styles.tableHead}`}>
            <span>อันดับ</span><span>ตลาด</span><span>ยอดจดทะเบียน</span><span>ส่วนแบ่งตลาด</span><span>การเปลี่ยนแปลง</span>
          </div>
          {rows.map((rank) => (
            <div className={styles.row} key={rank}>
              <span className={styles.rank}>{rank}</span>
              <span className={styles.nameSkeleton} />
              <span className={styles.valueSkeleton} />
              <span className={styles.shareSkeleton}><i style={{ width: `${88 - rank * 7}%` }} /></span>
              <span className={styles.moveSkeleton} />
            </div>
          ))}
        </div>

        <div className={styles.lockLayer}>
          <div className={styles.lockCard}>
            <div className={styles.lockIcon} aria-hidden="true">⌁</div>
            <h2>ปลดล็อก Market Intelligence</h2>
            <p>เข้าถึงตัวเลขทั้งหมด กราฟแนวโน้ม การเปรียบเทียบช่วงเวลา และข้อมูลสำหรับตัดสินใจ</p>
            <Link className={styles.primary} href="/reports">ดูแพ็กเกจ</Link>
            <Link className={styles.login} href="/member/login">มีบัญชีแล้ว? เข้าสู่ระบบ</Link>
          </div>
        </div>
      </section>
    </div>
  );
}
