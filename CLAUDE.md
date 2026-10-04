# TDR Automotive Intelligence — กฎสำหรับ Claude ในโปรเจกต์นี้
ก่อนเปิดหรือนำเข้าข้อมูลใน `data/packages/` หรือไฟล์ `TDR_FULL_*.zip` ให้อ่าน `.claude/skills/tdr-package-import/SKILL.md` ก่อนทุกครั้ง แล้วทำตามขั้นนำเข้าและกฎการแสดงผลในนั้น

Vehicle identity and market engine work follows docs/vehicle-db/VEHICLE_DB_V3.md.

งาน UI overhaul / พัฒนาหน้า / design graft ตาม `design/GRAFT_PLAN.md` (รวมส่วน UI ของแถว `feat/*` เช่น Intelligence, Analysis) ให้อ่าน `.claude/skills/tdr-design-graft/SKILL.md` ก่อน — ใช้อ่านเฉพาะแถว/หัวข้อที่เกี่ยวข้องและยึด `design/GRAFT_PLAN.md` เป็นหลัก ไม่ลดหรือเปลี่ยนข้อกำหนดใด ๆ · ไม่ใช้กับงาน backend / schema / data / payment / import ที่แถว feature ต้องทำ และไม่จำกัดงานเหล่านั้น (ถ้าแถวระบุให้พึ่ง `docs/vehicle-db/*` หรือเอกสารอื่น ให้อ่านตามปกติ)
