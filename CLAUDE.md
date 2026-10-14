# TDR Automotive Intelligence — กฎสำหรับ Claude ในโปรเจกต์นี้ 

## LOCKED contract for Codex / Claude / any code agent (2026-10-14)

Before any data, website market, price, trim or spec task, open `docs/portfolio/TDR_DATA_INFRA_COMPLETION_CONTRACT.md`, `docs/portfolio/data-infra.requirements.json`, `docs/portfolio/TDR_DATA_INFRA_EXECUTION_PLAN.md`, `docs/portfolio/TDR_DATA_INFRA_ACCEPTANCE_LEDGER.json` and `AGENTS.md`; report its requirement IDs, test/evidence and domain permission boundary. No false DONE, no silent deferral and no changes of completion criteria without owner-approved amendment. Read these in addition to the Master Roadmap / domain state rules. The contract does not authorize production changes or execution.

## Portfolio Master Roadmap v1.0 — บังคับอ่านก่อนเริ่มงานทุกครั้ง

ก่อน Claude Code จะวางแผน แก้โค้ด ส่ง Review หรือรับคำสั่งต่อจาก Enforcer ต้องอ่าน **`AGENTS.md` ก่อน** แล้วอ่าน **`docs/portfolio/TDR_MASTER_ROADMAP_V1.md`** และ **`docs/portfolio/portfolio.plan.json`** เพื่อทราบขอบเขตโครงการ, Dependency G0–G5, งานที่ได้รับอนุมัติจริง และข้อห้ามด้านการ Execute. ถ้าทำงานเกี่ยวกับ Engine ต้องอ่าน `docs/portfolio/ENGINE_VALIDITY_AND_DEPENDENCIES.md`, `docs/portfolio/DOMAIN_BOUNDARIES.md` รวมถึง Contract ของ Engine นั้นโดยเฉพาะ

ให้ยึด `docs/WORK_STATE.md` และ Roadmap ประจำ Domain ในเรื่อง Gate/Production/Identity/Writer/Design **เหนือข้อสรุปภาพรวม** ห้ามใช้แผนใหญ่เปิด Ice R6/R7/R8, สร้าง Writer, Merge หรือ Deploy เอง และห้ามถือว่าเอกสารสูตรที่ยังรอทดสอบเป็นสูตรที่อนุมัติแล้ว

ทุก Task Packet ต้องระบุ `roadmap_version=1.0`, commit ที่อ่าน, เอกสารอ้างอิง, scope ของไฟล์, เงื่อนไข stop และการทดสอบ. ก่อน Enforcer dispatch ให้ผ่านการตรวจเชิง Deterministic จาก `orchestration/preflight.mjs`; การตอบว่าอ่านแล้วไม่ใช่หลักฐานการผ่าน Gate. ณ วันที่อนุมัติ Roadmap ระบบ Night Shift ยังปิด `execution.enabled=false` และ Queue ว่าง. ห้ามเปิดจากการตีความ Prompt.

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
