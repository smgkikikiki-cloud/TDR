# TDR Automotive Intelligence — กฎสำหรับ Claude ในโปรเจกต์นี้
ก่อนเปิดหรือนำเข้าข้อมูลใน `data/packages/` หรือไฟล์ `TDR_FULL_*.zip` ให้อ่าน `.claude/skills/tdr-package-import/SKILL.md` ก่อนทุกครั้ง แล้วทำตามขั้นนำเข้าและกฎการแสดงผลในนั้น

Vehicle identity and market engine work follows docs/vehicle-db/VEHICLE_DB_V3.md.

งาน UI overhaul / พัฒนาหน้า / design graft ตาม `design/GRAFT_PLAN.md` (รวมส่วน UI ของแถว `feat/*` เช่น Intelligence, Analysis) ให้อ่าน `.claude/skills/tdr-design-graft/SKILL.md` ก่อน — ใช้อ่านเฉพาะแถว/หัวข้อที่เกี่ยวข้องและยึด `design/GRAFT_PLAN.md` เป็นหลัก ไม่ลดหรือเปลี่ยนข้อกำหนดใด ๆ · ไม่ใช้กับงาน backend / schema / data / payment / import ที่แถว feature ต้องทำ และไม่จำกัดงานเหล่านั้น (ถ้าแถวระบุให้พึ่ง `docs/vehicle-db/*` หรือเอกสารอื่น ให้อ่านตามปกติ)

## Ice Market Track — fixed local execution order

งาน Ice Full Package / market engine / crosswalk / market cutover ทุกครั้งต้องอ่านตามลำดับนี้ก่อนแก้โค้ด:

1. `docs/WORK_STATE.md`
2. `docs/market-track/ROADMAP.md`
3. `.claude/skills/tdr-package-import/SKILL.md` เมื่อแตะ package/panel/import/release metadata
4. ส่วนที่เกี่ยวข้องของ `docs/vehicle-db/VEHICLE_DB_V3.md` และ `docs/vehicle-db/SERVING_CONTRACT.md`

`docs/market-track/ROADMAP.md` เป็นลำดับ gate ที่ห้ามข้ามสำหรับ Market Track. ทำเฉพาะ CURRENT_GATE เท่านั้น และหยุดเมื่อเจอ hard gate/stop condition.

แพ็กเกจ M6.0 ที่ owner ให้ตรวจวันที่ 2026-10-06 เป็น **trial / fixture-only** จนกว่า owner จะระบุชัดว่ามี final package ใหม่ ห้ามใช้ trial package ทำ production import, production crosswalk match/approval หรือ live cutover แม้ไฟล์จะมี `status = พร้อมส่ง` และ sign-off ครบ.

ใน Claude Code local ให้ใช้ `/market-next` เพื่อบังคับอ่าน state + roadmap แล้วทำเฉพาะ gate ถัดไป. หลังจบ gate ต้องอัปเดต `docs/WORK_STATE.md` ใน session เดียวกัน.
