import Link from "next/link";
import { getEvents } from "@/lib/data";
import { getCanonicalModels } from "@/lib/canonical-data";
import { displayName } from "@/lib/display-name";
import styles from "./home-saas.module.css";

export const dynamic = "force-dynamic";

function baht(min: unknown, max: unknown) {
  const low = Number(min || 0);
  const high = Number(max || 0);
  if (!low && !high) return null;
  const f = (n: number) => n.toLocaleString("th-TH");
  if (low && high && low !== high) return `฿${f(low)}–${f(high)}`;
  return `฿${f(low || high)}`;
}

function vehicleMeta(model: any) {
  return [
    Array.isArray(model.powertrains) ? model.powertrains.join(" / ") : null,
    model.production_country || null,
    model.production_type || null,
  ].filter(Boolean).join(" · ");
}

function MarketPreview() {
  return (
    <div className={styles.preview} aria-label="ตัวอย่าง Market Intelligence">
      <div className={styles.previewTop}>
        <div>
          <strong>Market Intelligence</strong>
          <span>ภาพรวมตลาดรถยนต์ประเทศไทย</span>
        </div>
        <button type="button" disabled>ส่งออกข้อมูล</button>
      </div>
      <div className={styles.previewFilters} aria-hidden="true">
        <div><small>เดือน</small><b>เลือกรอบข้อมูล</b></div>
        <div><small>ช่วงเวลา</small><b>เดือน / 3M / 6M / 12M / YTD</b></div>
        <div><small>มิติข้อมูล</small><b>แบรนด์ / รุ่น / Segment</b></div>
      </div>
      <div className={styles.previewTabs} aria-hidden="true">
        <b>ส่วนแบ่งตลาด</b><span>ยอดจดทะเบียน</span><span>การเปลี่ยนแปลง</span><span>แนวโน้มรายเดือน</span>
      </div>
      <div className={styles.previewTable} aria-hidden="true">
        <div className={`${styles.previewRow} ${styles.previewHead}`}>
          <span>อันดับ</span><span>ตลาด</span><span>ยอดจดทะเบียน</span><span>ส่วนแบ่งตลาด</span><span>การเปลี่ยนแปลง</span>
        </div>
        {Array.from({ length: 8 }, (_, index) => (
          <div className={styles.previewRow} key={index}>
            <span>{index + 1}</span>
            <i className={styles.nameBar} />
            <i className={styles.valueBar} />
            <i className={styles.shareBar} />
            <i className={styles.moveBar} />
          </div>
        ))}
      </div>
      <div className={styles.previewLock}>
        <div className={styles.previewLockCard}>
          <div className={styles.lockMark}>▣</div>
          <strong>ปลดล็อก Market Intelligence</strong>
          <span>เข้าถึงตัวเลขทั้งหมด กราฟแนวโน้ม และข้อมูลสำหรับตัดสินใจ</span>
          <Link href="/pricing">ดูแพ็กเกจ</Link>
          <Link className={styles.previewLogin} href="/member/login">มีบัญชีแล้ว? เข้าสู่ระบบ</Link>
        </div>
      </div>
    </div>
  );
}

function VehicleCard({ model }: { model: any }) {
  const brand = displayName(model.brands);
  const price = baht(model.retail_price_min, model.retail_price_max);
  return (
    <Link className={styles.vehicleCard} href={`/models/${model.slug}`}>
      <div className={styles.vehicleVisual}>
        {model.image_url ? <img src={model.image_url} alt="" /> : <><small>{brand || "TDR"}</small><b>{displayName(model)}</b></>}
      </div>
      <strong>{[brand, displayName(model)].filter(Boolean).join(" ")}</strong>
      <span>{vehicleMeta(model) || "ข้อมูลรุ่นใน Vehicle Master"}</span>
      <em>{price || "ยังไม่มีราคาที่ตรวจสอบได้"}</em>
    </Link>
  );
}

export default async function Home() {
  const [models, events] = await Promise.all([getCanonicalModels(600), getEvents(3)]);
  const catalogue = (models as any[]).filter((row) => String(row.status || "").toUpperCase() !== "HISTORICAL");
  const cards = catalogue.slice(0, 5);

  return (
    <div className={styles.home}>
      <section className={styles.hero}>
        <div className={styles.heroCopy}>
          <div className={styles.eyebrow}>TDR AUTOMOTIVE INTELLIGENCE</div>
          <h1>ติดตามตลาดรถยนต์ไทย<br />จากข้อมูลจดทะเบียนรายเดือน</h1>
          <p>ยอดจดทะเบียน ส่วนแบ่งตลาด แนวโน้ม และการเปลี่ยนแปลงรายแบรนด์ รุ่น และเซกเมนต์ เชื่อมกับฐานข้อมูลรถยนต์ของ TDR</p>
          <div className={styles.heroActions}>
            <Link className={styles.primaryButton} href="/market">เปิด Market Intelligence →</Link>
            <Link className={styles.secondaryButton} href="/models">ดูฐานข้อมูลรถยนต์</Link>
          </div>
          <div className={styles.trustRow}>
            <div><b>ข้อมูลจดทะเบียนรายเดือน</b><span>ติดตามยอดและส่วนแบ่งตลาดตามช่วงเวลา</span></div>
            <div><b>วิเคราะห์หลายมิติ</b><span>แบรนด์ รุ่น เซกเมนต์ ตัวถัง และระบบขับเคลื่อน</span></div>
            <div><b>เชื่อมกับ Vehicle Master</b><span>อ้างอิงรุ่นและโครงสร้างรถจากฐานข้อมูล TDR</span></div>
          </div>
        </div>
        <MarketPreview />
      </section>

      <section className={styles.tools}>
        <div className={styles.sectionHead}>
          <h2>เครื่องมือและฐานข้อมูล</h2>
          <span>ค้นหา เปรียบเทียบ และวิเคราะห์ข้อมูลรถยนต์ในระบบ TDR</span>
        </div>
        <div className={styles.toolGrid}>
          <Link className={`${styles.toolCard} ${styles.marketTool}`} href="/market">
            <span className={styles.badge}>PRO</span>
            <div className={styles.toolIcon}>▥</div>
            <h3>Market Intelligence</h3>
            <p>ดูยอดจดทะเบียน ส่วนแบ่งตลาด อันดับ และการเคลื่อนไหวของตลาดรถไทย พร้อมเชื่อมกับ Vehicle Master ของ TDR</p>
            <b>เปิดเครื่องมือ →</b>
            <small>ยอดจดทะเบียน · ส่วนแบ่งตลาด · แนวโน้ม · Movement</small>
          </Link>

          <Link className={styles.toolCard} href="/compare">
            <span className={`${styles.badge} ${styles.freeBadge}`}>FREE</span>
            <div className={styles.toolIcon}>⚖</div>
            <h3>เทียบรถ</h3>
            <p>เปรียบเทียบรุ่นย่อย ราคา ขนาด Powertrain กำลัง และระยะทางที่ผู้ผลิตประกาศในตารางเดียว</p>
            <b>เทียบรถ →</b>
            <small>ราคา · ขนาดตัวถัง · Powertrain · Range</small>
          </Link>

          <Link className={styles.toolCard} href="/models">
            <span className={`${styles.badge} ${styles.freeBadge}`}>FREE</span>
            <div className={styles.toolIcon}>◫</div>
            <h3>แคทตาล็อกรถยนต์</h3>
            <p>ค้นหารุ่นและรุ่นย่อยใน Vehicle Master พร้อมราคา ระบบขับเคลื่อน และข้อมูลการผลิตที่มีแหล่งอ้างอิง</p>
            <b>ค้นหารถ →</b>
            <small>รุ่นย่อย · ราคา · Powertrain · การผลิต</small>
          </Link>
        </div>
      </section>

      <section className={styles.secondarySection}>
        <div className={styles.sectionHead}>
          <h2>รถในฐานข้อมูล</h2>
          <Link href="/models">ดูรถทั้งหมด →</Link>
        </div>
        {cards.length ? <div className={styles.vehicleGrid}>{cards.map((model) => <VehicleCard key={model.id} model={model} />)}</div> : <div className={styles.empty}>ยังไม่มีรถใน active canonical release</div>}
      </section>

      <section className={styles.secondarySection}>
        <div className={styles.sectionHead}>
          <h2>บทวิเคราะห์ล่าสุด</h2>
          <Link href="/news">ดูบทวิเคราะห์ทั้งหมด →</Link>
        </div>
        {events.length ? (
          <div className={styles.articleGrid}>
            {(events as any[]).map((event) => (
              <Link className={styles.articleCard} href="/news" key={event.id}>
                <time>{event.event_date}</time>
                <strong>{event.title_th}</strong>
                <span>{event.summary_th || event.source_name || "อ่านรายละเอียด"}</span>
                <b>→</b>
              </Link>
            ))}
          </div>
        ) : <div className={styles.empty}>ยังไม่มีบทวิเคราะห์ที่เผยแพร่ในฐานข้อมูล</div>}
      </section>
    </div>
  );
}
