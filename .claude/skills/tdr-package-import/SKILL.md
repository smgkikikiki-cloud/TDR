---
name: tdr-package-import
description: ใช้ทุกครั้งที่ได้รับหรือทำงานกับ TDR Full Package (ไฟล์ TDR_FULL_<งวด>_v<n>_M<master>.zip) หรือข้อมูลยอดจดทะเบียน ล้อ/ยาง ระบบขับเคลื่อน ของ TDR Automotive Intelligence — ตรวจ นำเข้า จัดไฟล์/เวอร์ชัน อ่าน CHANGELOG และกฎการแสดงผลบนเว็บ
---

# นำเข้า TDR Full Package (ฝั่งแพลตฟอร์ม)

อ่านไฟล์นี้ก่อนเปิดข้อมูลใด ๆ ในแพ็กเกจ · ข้อมูลในแพ็กเกจเป็นตัวเลขที่คำนวณแล้ว ห้ามคำนวณยอดใหม่เองจากแหล่งอื่น

## 1. โครง Full Package
- `panels/` 6 แพ็กเกจ (แต่ละ zip มี `manifest.json` · `panel.json` · `method.md` · `data/*.csv`)
- `CHANGELOG.csv` การเปลี่ยนแปลงตั้งแต่เวอร์ชันที่นำเข้าครั้งก่อน · `full_package.json` ดัชนี md5 · `README_นำเข้า.md`

| ต้องการดู | แพ็กเกจ · ไฟล์ | คอลัมน์ |
|---|---|---|
| จังหวัด × แบรนด์ × เชื้อเพลิง (ยอดจริง) | reg_province · data/reg_province.csv | period, province, reg_type, brand, fuel_group, reg_count |
| **จังหวัด × แบรนด์ × รุ่น (ยอดจริง)** | **reg_trend** · data/reg_trend.csv | period, province, reg_type, brand, model_group_id, model_name, reg_count |
| รุ่น × ระบบขับเคลื่อน (2567-01 →) | reg_powertrain · data/reg_powertrain.csv | period, province, reg_type, brand, model_group_id, model_name, fuel_group, reg_est, reg_min, reg_max, certainty |
| ขอบล้อ | rim_province · data/rim_province.csv | period, province, reg_type, brand, rim_bucket, reg_est |
| เบอร์ยาง (+ coverage.csv) | tyre_province · data/tyre_province.csv | period, province, reg_type, brand, tyre_size, rim_inch, reg_est |
| เซกเมนต์/ตัวถังของรุ่น | dims · dims/model_group.csv | model_group_id, model_name, brand, reg_total_all, segment, body |

งวดเขียน พ.ศ. `YYYY-MM` · เชื่อมรุ่นข้ามแพ็กเกจด้วย `model_group_id`

## 2. ขั้นนำเข้า
1. ตรวจ md5 ตาม `full_package.json` และ `status` ต้องเป็น "พร้อมส่ง" (ไฟล์ชื่อมี `_ร่าง` = ห้ามขึ้นเว็บจริง)
2. `python validate_package.py panels/*.zip` ต้องผ่านทุกไฟล์ — ใช้ validate_package.py ที่แนบมาใน zip เสมอ (แทนเวอร์ชันเก่าใน repo)
   ล้อ/ยาง: เผยแพร่ตั้งแต่ `period_from` ใน manifest ของ tyre_province (ปีแรกที่ครอบคลุม ≥ 95% ต่อเนื่อง) — ถ้าเอกสารอื่นขัดกัน ให้ยึด manifest (รวม confirmed_by 2 ชื่อ)
3. นำเข้าแบบ **แทนทั้งชุด**: ลบข้อมูลเดิมแล้วนำเข้าทั้ง 6 แพ็กเกจ (ตัวเลขย้อนหลังเปลี่ยนได้ทุกงวด)
4. ตรวจหลังนำเข้า: ยอดรายเดือน reg_province = reg_trend · ผลรวม reg_powertrain ต่อ (period, province, reg_type, model_group_id) = reg_trend (±0.5)
5. บันทึก `master_version` ที่นำเข้า แล้วแจ้ง Ice

## 3. อ่าน CHANGELOG
- Major = ตัวเลขที่เผยแพร่แล้วเปลี่ยน → ขึ้นหมายเหตุบนหน้าที่เกี่ยวข้อง
- entity = crosswalk → model_group_id ของรุ่นเปลี่ยน ให้ย้ายประวัติ/บุ๊กมาร์ก/ลิงก์ไปรหัสใหม่ ตาม **`id_changes.csv`** ใน zip (ไม่ต้องเทียบเส้นกราฟเอง)
  - คอลัมน์: old_model_group_id, new_model_group_id, reg_moved_all_periods, share_of_old_pct, type
  - type: เปลี่ยนรหัส = รหัสเดิมย้ายทั้งหมดไปรหัสใหม่ · รวม = หลายรหัสเดิมรวมเป็นรหัสใหม่เดียว (รหัสเดิมเลิกใช้) · แยก = รหัสเดิมยังอยู่ แต่บางส่วน (share_of_old_pct) แยกไปรหัสใหม่
  - รหัสเดิมที่ไม่อยู่ใน dims ชุดใหม่ = เลิกใช้ → redirect ไป new_model_group_id · ยอดย้อนหลังให้ใช้ข้อมูลชุดใหม่ทั้งชุด (นำเข้าแบบแทนทั้งชุด) ไม่ต้องคำนวณย้ายยอดเอง
  - ตารางชื่อดิบกรมขนส่ง → รหัสรุ่น เป็นตัวจับคู่ของ Ice ไม่อยู่ในแพ็กเกจ
- Minor = เพิ่มข้อมูล ตัวเลขเดิมไม่เปลี่ยน

## 4. กฎการแสดงผล (ห้ามละเมิด)
- ชื่อดัชนี: "TDR Wheel & Tyre Index" · "TDR Powertrain Index" · ห้ามใช้คำว่า "ประมาณการ"
- ห้ามเอ่ยชื่อแหล่งข้อมูลสเปก · ห้ามบอกว่าข้อมูลล้อ/ยางมาจากกรมการขนส่งทางบก
- ยอดจดทะเบียน (reg_count) อ้าง "กรมการขนส่งทางบก" ได้ · จังหวัดที่จด ≠ จังหวัดที่ใช้งาน (กรุงเทพฯ ~58%) ใส่หมายเหตุเสมอ
- เปอร์เซ็นต์เปลี่ยนแปลงแสดงเมื่อฐาน ≥ 30 คัน · reg_powertrain `certainty`: exact = แน่นอน · family = รุ่นพี่น้องสเปกเครื่องยนต์เหมือนกัน ยอดรวมตระกูลแน่นอน (แสดง reg_est ได้ ใส่หมายเหตุ "แบ่งระหว่างรุ่นในตระกูลโดย TDR") · range = แสดงช่วง reg_min–reg_max
- ใช้โลโก้ TDR เสมอ · ทำตาม `access` และ `free_scope` ใน panel.json (free/pro/enterprise)

## 6. จัดไฟล์และเวอร์ชัน (ใช้โครงเดียวกับฝั่ง Ice)
```
data/packages/
  ล่าสุด.json                      ← period, version, master_version, folder, md5, imported_at
  <งวด>/v<n>_M<ver>/               ← Full Package ที่ใช้งาน (zip เดิม + แตกไฟล์ไว้ข้างกัน)
  <งวด>/เวอร์ชันเก่า/v<n>_M<ver>_เก่า/ ← รุ่นก่อนของงวดเดียวกัน (ไม่ลบ)
  ประวัติการนำเข้า.csv              ← วันที่, งวด, version, master_version, md5, ผลตรวจ, ผู้นำเข้า (UTF-8 BOM)
  บันทึกการย้ายไฟล์.csv              ← ที่เดิม, ที่ใหม่, เหตุผล, วันที่ (UTF-8 BOM)
.claude/skills/tdr-package-import/   ← สกิลนี้ (แทนด้วยไฟล์จาก สำหรับ_AI/ ทุกรอบ)
CLAUDE.md · AGENTS.md (รากของ repo)
```

### 6.1 อัปเกรดโครงไฟล์ครั้งแรก (ทำครั้งเดียว)
1. สำรวจ repo: หาไฟล์ TDR_FULL_*.zip, panels/*.zip, CSV ที่แตกไว้, สคริปต์นำเข้า, ไฟล์ตั้งค่าที่อ้างพาธข้อมูล (เช่น .env, config, โค้ด import)
2. ทำ **แผนย้าย** เป็นตาราง (ที่เดิม → ที่ใหม่ · เหตุผล · โค้ดที่ต้องแก้พาธ) ส่งให้กี้อนุมัติ — **ยังไม่ย้ายจนกว่ากี้สั่ง**
3. เมื่ออนุมัติ: ย้ายด้วย git mv / mv เท่านั้น **ห้ามลบ** · ชื่อซ้ำให้เติมเวลาท้ายชื่อ ห้ามเขียนทับ · บันทึกทุกไฟล์ลง บันทึกการย้ายไฟล์.csv
4. แก้พาธในโค้ด/ตั้งค่าให้ชี้ `data/packages/ล่าสุด.json` แทนการเขียนชื่อไฟล์ตายตัว
5. รันนำเข้าซ้ำ แล้วเทียบยอดรวมก่อน/หลังต้องเท่ากัน · commit แยกเป็น "จัดโครงไฟล์ TDR" (ไม่ปนกับงานอื่น)

### 6.2 ทุกครั้งที่ได้ Full Package ใหม่
1. วาง zip ที่ `data/packages/<งวด>/v<n>_M<ver>/` แล้วแตกไฟล์ข้างกัน
2. ถ้างวดเดียวกันมีเวอร์ชันเดิม → ย้ายโฟลเดอร์เดิมลง `<งวด>/เวอร์ชันเก่า/<ชื่อเดิม>_เก่า/`
3. แทน `.claude/skills/tdr-package-import/`, `CLAUDE.md`, `AGENTS.md` ด้วยไฟล์ใน `สำหรับ_AI/`
4. ตรวจความต่อเนื่อง: `changelog_since` ใน full_package.json ต้องเท่ากับ master_version ใน ล่าสุด.json เดิม — ไม่เท่า = ข้ามเวอร์ชัน แจ้ง Ice ก่อนนำเข้า
5. นำเข้าตามข้อ 2 → อัปเดต ล่าสุด.json + ประวัติการนำเข้า.csv → แจ้ง Ice: งวด · v · master_version · ผลตรวจ

## 5. ห้าม
- ห้ามแก้ตัวเลขในแพ็กเกจ · พบผิดให้แจ้ง Ice พร้อมแถวตัวอย่าง (Ice แก้ที่ต้นทางแล้วออกเวอร์ชันใหม่)
- ห้ามเผยแพร่ไฟล์ CSV ดิบเกินสิทธิ์ใน panel.json
