import type { Metadata } from "next";
import { notFound } from "next/navigation";
import "./gallery.css";
import { ChipDemo } from "./ChipDemo";
import {
  Button, Card, CardHead, Chip, ConfidenceMeter, Delta, Field, Flag, KpiCard, Legend, LockedBlock,
  PageHead, Select, StageBar, Swatch, Table, TextInput, TierBadge,
} from "@/components/design";

export const metadata: Metadata = { title: "Design components", robots: { index: false, follow: false } };

/** Preview-only gallery of the shared design components (PR 4). All values are dummy and must never be
 *  copied into a page. It is hidden on the production deployment. */
export default function DesignComponentsGallery() {
  if (process.env.VERCEL_ENV === "production") notFound();
  return (
    <div className="designPage">
      <div className="tdr-wrap tdr-gallery">
        <PageHead
          eyebrow="Design system"
          eyebrowLang="en"
          title="Shared components"
          lead="ค่าทั้งหมดในหน้านี้เป็นข้อมูลตัวอย่าง ห้ามคัดลอกไปใช้ในหน้าจริง"
        />

        <h2>Button</h2>
        <p className="tdr-gallery__note">หนึ่งปุ่มทึบสีแดง (accent) ต่อหน้าจอ · ปุ่มอื่นเป็นเส้นขอบ (ค่าเริ่มต้น) หรือ ghost · สีน้ำเงินทึบมีเฉพาะปุ่ม Contact ของ Enterprise</p>
        <div className="tdr-gallery__row">
          <Button variant="accent">Accent (max 1 per view)</Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="contact" href="/contact">Contact →</Button>
          <Button variant="secondary" disabled>Disabled</Button>
        </div>

        <h2>Chip</h2>
        <div className="tdr-gallery__row">
          <Chip>Toyota</Chip>
          <Chip count={318}>SUV</Chip>
          <Chip pressed count={53}>Selected</Chip>
          <Chip pressed={false}>Not selected</Chip>
          <Chip href="/models" aria-current="page">Link chip</Chip>
        </div>
        <p className="tdr-gallery__note">ปุ่มสลับ (toggle) ใช้งานได้จริง: onClick, disabled, aria-* · สถานะเป็นของผู้เรียกใช้ ไม่ใช่ของ Chip</p>
        <ChipDemo />

        <h2>TierBadge</h2>
        <p className="tdr-gallery__note">Free · Member · Pro · Enterprise เป็นป้ายคนละแบบ (รายงานระดับสมาชิกใช้ Member ไม่ใช่ Free)</p>
        <div className="tdr-gallery__row">
          <TierBadge tier="free" />
          <TierBadge tier="member" />
          <TierBadge tier="pro" />
          <TierBadge tier="enterprise" />
          <TierBadge tier="member" locked />
          <TierBadge tier="pro" locked />
        </div>

        <h2>Flag</h2>
        <div className="tdr-gallery__row">
          <Flag kind="estimate">ประมาณการ · ครอบคลุม 92%</Flag>
          <Flag kind="new">ใหม่</Flag>
          <Flag kind="source">ที่มา: ตัวอย่าง</Flag>
          <Flag kind="soon">เร็วๆ นี้</Flag>
          <Flag kind="delayed">เลื่อน</Flag>
        </div>

        <h2>Delta</h2>
        <p className="tdr-gallery__note">ลูกศรและเครื่องหมายเสมอ · % ต้องมีฐานอย่างน้อย 30 ไม่เช่นนั้นแสดง –</p>
        <div className="tdr-gallery__row">
          <Delta value={1.2} />
          <Delta value={-0.8} />
          <Delta value={0.02} />
          <Delta value={null} />
          <Delta value={12.5} unit="%" base={120} />
          <Delta value={12.5} unit="%" base={20} />
        </div>

        <h2>KpiCard</h2>
        <div className="tdr-kpis">
          <KpiCard label="ตัวอย่างตัวเลข" value={1432} unit="รุ่น" />
          <KpiCard label="ตัวอย่างพร้อมส่วนต่าง" value={61805} delta={<Delta value={1.4} />} note="เทียบเดือนก่อน" />
          <KpiCard label="แบบใหญ่" value={318} size="lg" />
        </div>

        <h2>Card</h2>
        <div className="tdr-grid">
          <Card>
            <CardHead title="Card" aside={<TierBadge tier="member" />} />
            <p className="tdr-gallery__note">กรอบเส้นขอบ ไม่มีเงา</p>
          </Card>
          <Card tone="raised"><CardHead title="Raised" /></Card>
          <Card tone="dashed"><CardHead title="Dashed (ว่าง / เร็วๆ นี้)" aside={<Flag kind="soon">เร็วๆ นี้</Flag>} /></Card>
          <Card href="/models"><CardHead title="Link card" /></Card>
        </div>

        <h2>LockedBlock</h2>
        <p className="tdr-gallery__note">ภาพตกแต่งคงที่ + ป้ายระดับ + ปุ่ม · ไม่มีค่าจริงใน DOM</p>
        <div className="tdr-grid">
          <LockedBlock tier="pro" message="ส่วนนี้สำหรับสมาชิก Pro" cta={{ label: "อัปเกรดเป็น Pro", href: "/pricing" }} />
          <LockedBlock tier="member" message="ส่วนนี้สำหรับสมาชิก" height={80} />
        </div>

        <h2>StageBar · ConfidenceMeter</h2>
        <div className="tdr-grid">
          <Card>
            <StageBar step={3} label="OEM ยืนยันแล้ว" />
            <ConfidenceMeter level={3} label="ความเชื่อมั่น: สูง" />
          </Card>
          <Card>
            <StageBar step={1} label="ข่าวลือ" />
            <ConfidenceMeter level={1} label="ความเชื่อมั่น: ต่ำ" />
          </Card>
        </div>

        <h2>Table</h2>
        <Table caption="ตัวอย่างตาราง">
          <thead>
            <tr><th scope="col">ความสามารถ</th><th scope="col">Free</th><th scope="col">Pro</th><th scope="col" className="tdr-num">จำนวน</th></tr>
          </thead>
          <tbody>
            <tr><td>Panel ย้อนหลัง</td><td>— ไม่มี</td><td>✓ มี</td><td className="tdr-num">1,432</td></tr>
            <tr><td>เทียบช่วงเวลา</td><td>— ไม่มี</td><td>✓ มี</td><td className="tdr-num">62</td></tr>
          </tbody>
        </Table>

        <h2>Form</h2>
        <div className="tdr-gallery__form">
          <Field label="อีเมล" hint="เราไม่ส่งสแปม" render={(a) => <TextInput type="email" placeholder="you@example.com" {...a} />} />
          <Field label="หัวข้อ" render={(a) => <Select {...a}><option>Enterprise</option><option>อื่นๆ</option></Select>} />
          <Field label="เบอร์โทร" error="รูปแบบไม่ถูกต้อง" render={(a) => <TextInput type="tel" defaultValue="08" {...a} />} />
        </div>

        <h2>Swatch · Legend (map, diverging, categories)</h2>
        <p className="tdr-gallery__note">ทุกช่องสีมีเส้นขอบ --border-strong เพื่อให้สีอ่อนยังเห็นชัดทั้งโหมดสว่างและมืด</p>
        <Legend items={[
          { fill: "map-1", label: "map 1" }, { fill: "map-2", label: "map 2" }, { fill: "map-3", label: "map 3" },
          { fill: "map-4", label: "map 4" }, { fill: "map-5", label: "map 5" },
        ]} />
        <Legend items={[
          { fill: "div-1", label: "− ลดมาก" }, { fill: "div-2", label: "div 2" }, { fill: "div-3", label: "div 3 (≈0)" },
          { fill: "div-4", label: "div 4" }, { fill: "div-5", label: "+ เพิ่มมาก" },
        ]} />
        <Legend square items={[
          { fill: "cat-1", label: "cat 1" }, { fill: "cat-2", label: "cat 2" }, { fill: "cat-3", label: "cat 3" },
          { fill: "cat-4", label: "cat 4" }, { fill: "cat-5", label: "cat 5" },
        ]} />
        <div className="tdr-gallery__row"><Swatch fill="div-4" /> <Swatch fill="map-1" /></div>
        <p className="tdr-gallery__note">ช่องแผนที่ (SVG) มีเส้นขอบ 1px คงที่แม้ภาพถูกย่อ/ขยาย</p>
        <svg viewBox="0 0 120 24" width="100%" height="64" role="img" aria-label="ตัวอย่างช่องแผนที่" style={{ maxWidth: 480 }}>
          <rect data-testid="region" className="tdr-region tdr-fill-div-4" x="2" y="2" width="36" height="20" />
          <rect className="tdr-region tdr-fill-map-1" x="42" y="2" width="36" height="20" />
          <rect className="tdr-region tdr-fill-div-3" x="82" y="2" width="36" height="20" />
        </svg>
      </div>
    </div>
  );
}
