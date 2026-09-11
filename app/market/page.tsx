import Link from "next/link";
import styles from "./market-public.module.css";

const shareRows = Array.from({ length: 5 }, (_, index) => index + 1);
const movementRows = Array.from({ length: 5 }, (_, index) => index + 1);
const trendBars = [24, 35, 31, 44, 52, 47, 63, 58, 76, 69, 86, 78];
const segmentRows = ["B-Segment", "C-Segment", "Pickup", "SUV", "MPV", "อื่นๆ"];

const capabilities = [
  { label: "ฐานข้อมูลรถ / รุ่นย่อย / ราคา / สเปกพื้นฐาน", free: true, pro: true },
  { label: "เทียบรถ", free: true, pro: true },
  { label: "ยอดจดทะเบียนรายรุ่น", free: false, pro: true },
  { label: "ส่วนแบ่งตลาด (Market Share)", free: false, pro: true },
  { label: "การเปลี่ยนแปลง (MoM / YoY)", free: false, pro: true },
  { label: "ดูตามแบรนด์ รุ่น เซกเมนต์ ตัวถัง ระบบขับเคลื่อน", free: false, pro: true },
  { label: "แนวโน้มย้อนหลัง (3 / 6 / 12 เดือน, YTD)", free: false, pro: true },
  { label: "เปรียบเทียบกับช่วงก่อนหน้า", free: false, pro: true },
  { label: "ส่งออกข้อมูล (CSV)", free: false, pro: true },
  { label: "บทวิเคราะห์พิเศษจาก TDR", free: false, pro: true },
  { label: "ติดตามตารางเปิดตัวรถใหม่ล่วงหน้า", free: false, pro: "soon" as const },
];

function LockIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect x="5" y="10" width="14" height="10" rx="2" />
      <path d="M8 10V7a4 4 0 0 1 8 0v3" />
    </svg>
  );
}

function TrustIcon({ type }: { type: "signal" | "pulse" | "database" }) {
  if (type === "signal") {
    return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 20v-6M12 20V9M19 20V4" /></svg>;
  }
  if (type === "pulse") {
    return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M13 2 5 13h6l-1 9 9-13h-6z" /></svg>;
  }
  return <svg viewBox="0 0 24 24" aria-hidden="true"><ellipse cx="12" cy="5" rx="7" ry="3" /><path d="M5 5v6c0 1.7 3.1 3 7 3s7-1.3 7-3V5M5 11v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6" /></svg>;
}

function Check() {
  return <span className={styles.check} aria-label="มี">✓</span>;
}

function Dash() {
  return <span className={styles.dash} aria-label="ไม่มี">—</span>;
}

export default function PublicMarketPage() {
  return (
    <div className={styles.page}>
      <section className={styles.hero}>
        <div className={styles.heroCopy}>
          <div className={styles.eyebrow}>MARKET INTELLIGENCE</div>
          <h1>ตลาดรถไทยในมุมที่ลึกกว่า</h1>
          <p>ยอดจดทะเบียน ส่วนแบ่งตลาด การเปลี่ยนแปลงรายรุ่น และแนวโน้มตลาดจากข้อมูลจดทะเบียนจริง เชื่อมโยงกับฐานข้อมูลรถของ TDR</p>
        </div>

        <div className={styles.trustGrid} aria-label="จุดเด่นของข้อมูล">
          <article>
            <TrustIcon type="signal" />
            <div><strong>ข้อมูลเชื่อถือได้</strong><span>อ้างอิงข้อมูลจดทะเบียนจริง</span></div>
          </article>
          <article>
            <TrustIcon type="pulse" />
            <div><strong>อัปเดตต่อเนื่อง</strong><span>ติดตามข้อมูลตลาดรายเดือน</span></div>
          </article>
          <article>
            <TrustIcon type="database" />
            <div><strong>เชื่อมโยงฐานข้อมูลรถ</strong><span>ใช้ Vehicle Master ชุดเดียวกัน</span></div>
          </article>
        </div>
      </section>

      <section className={styles.workspace} aria-label="ตัวอย่าง Market Intelligence">
        <div className={styles.filterBar} aria-hidden="true">
          <label><span>ช่วงเวลา</span><div>ช่วงข้อมูลล่าสุด <b>⌄</b></div></label>
          <label><span>เปรียบเทียบกับ</span><div>ก่อนหน้า 3 เดือน <b>⌄</b></div></label>
          <label><span>มุมมอง</span><div>แบรนด์ <b>⌄</b></div></label>
          <label><span>ประเภทรถ</span><div>ทั้งหมด <b>⌄</b></div></label>
          <label><span>ระบบขับเคลื่อน</span><div>ทั้งหมด <b>⌄</b></div></label>
          <button type="button" disabled><span>⌕</span> ดูข้อมูล</button>
        </div>

        <div className={styles.dashboard} aria-hidden="true">
          <article className={styles.metricCard}>
            <div className={styles.cardTitle}>ยอดจดทะเบียนรวม <span>ⓘ</span></div>
            <div className={styles.bigMasked}>•••••• <small>คัน</small></div>
            <div className={styles.deltaMasked}>▲ ••••</div>
            <p>เทียบกับช่วงก่อนหน้า</p>
          </article>

          <article className={`${styles.dataCard} ${styles.shareCard}`}>
            <div className={styles.cardTitle}>ส่วนแบ่งตลาด (Top 5)</div>
            <div className={styles.previewRows}>
              {shareRows.map((rank) => (
                <div className={styles.previewRow} key={rank}>
                  <span>{rank}</span>
                  <i className={styles.textMask} />
                  <em><b style={{ width: `${88 - rank * 10}%` }} /></em>
                  <i className={styles.valueMask} />
                </div>
              ))}
            </div>
          </article>

          <article className={`${styles.dataCard} ${styles.movementCard}`}>
            <div className={styles.cardTitle}>การเปลี่ยนแปลง (MoM)</div>
            <div className={styles.switcher}><b>เพิ่มขึ้นสูงสุด</b><span>ลดลงสูงสุด</span></div>
            <div className={styles.movementRows}>
              {movementRows.map((rank) => (
                <div key={rank}><span>{rank}</span><i className={styles.textMask} /><strong className={rank === 3 ? styles.down : styles.up}>{rank === 3 ? "▼" : "▲"} •••</strong></div>
              ))}
            </div>
          </article>

          <article className={`${styles.dataCard} ${styles.trendCard}`}>
            <div className={styles.cardTitle}>แนวโน้มยอดจดทะเบียน</div>
            <div className={styles.trendPlot}>
              {trendBars.map((height, index) => <i key={index} style={{ height: `${height}%` }} />)}
            </div>
            <div className={styles.axis}><span>ย้อนหลัง</span><span>ล่าสุด</span></div>
          </article>

          <article className={`${styles.dataCard} ${styles.powertrainCard}`}>
            <div className={styles.cardTitle}>สัดส่วนตามระบบขับเคลื่อน</div>
            <div className={styles.donutWrap}>
              <div className={styles.donut} />
              <div className={styles.legend}>
                {['ICE', 'HEV', 'BEV', 'PHEV', 'อื่นๆ'].map((label) => <span key={label}><i />{label}<b>•••</b></span>)}
              </div>
            </div>
          </article>

          <article className={`${styles.dataCard} ${styles.segmentCard}`}>
            <div className={styles.cardTitle}>ยอดจดทะเบียนตามเซกเมนต์</div>
            <div className={styles.segmentRows}>
              {segmentRows.map((label, index) => <div key={label}><span>{label}</span><em><b style={{ width: `${72 - index * 7}%` }} /></em><i className={styles.valueMask} /></div>)}
            </div>
          </article>
        </div>

        <div className={styles.lockLayer}>
          <div className={styles.lockCard}>
            <div className={styles.lockIcon}><LockIcon /></div>
            <h2>ปลดล็อก Market Intelligence</h2>
            <p>เข้าถึงตัวเลขทั้งหมด กราฟแนวโน้ม และข้อมูลเชิงลึก</p>
            <Link className={styles.primary} href="/reports">ดูแพ็กเกจ</Link>
            <Link className={styles.login} href="/member/login">มีบัญชีแล้ว? เข้าสู่ระบบ</Link>
          </div>
        </div>
      </section>

      <section className={styles.proSection}>
        <div className={styles.proHead}>
          <div>
            <div className={styles.eyebrow}>TDR PRO</div>
            <h2>ใช้ข้อมูลตลาดเป็นเครื่องมือทำงาน</h2>
            <p>มากกว่าแค่ตัวเลข แต่คือความได้เปรียบในการตัดสินใจสำหรับคนที่ทำงานในอุตสาหกรรมยานยนต์</p>
          </div>
          <div className={styles.proActions}>
            <Link className={styles.primaryAction} href="/reports">ดูแพ็กเกจ <span>→</span></Link>
            <Link href="/reports#tdr-compare">ดูรายละเอียดแพ็กเกจ →</Link>
          </div>
        </div>

        <div className={styles.matrixWrap}>
          <table className={styles.matrix}>
            <thead>
              <tr><th>ความสามารถ</th><th>Free</th><th>Market Intelligence (TDR Pro)</th></tr>
            </thead>
            <tbody>
              {capabilities.map((item) => (
                <tr key={item.label}>
                  <td>{item.label}</td>
                  <td>{item.free ? <Check /> : <Dash />}</td>
                  <td>{item.pro === "soon" ? <span className={styles.soon}>เร็วๆ นี้</span> : item.pro ? <Check /> : <Dash />}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className={styles.orgBanner}>
        <div className={styles.orgIcon} aria-hidden="true">▣</div>
        <div>
          <h2>ร่วมเป็นส่วนหนึ่งขององค์กรที่ใช้ TDR</h2>
          <p>ผู้จำหน่ายรถยนต์ ธนาคาร สถาบันการเงิน บริษัทวิจัย และองค์กรชั้นนำ เลือกใช้ TDR เพื่อเข้าใจตลาดก่อนใคร</p>
        </div>
        <Link href="/reports#tdr-contact">ดูแพ็กเกจองค์กร <span>→</span></Link>
      </section>
    </div>
  );
}
