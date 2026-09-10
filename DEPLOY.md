# Deploy path

แนะนำ Vercel + Supabase เพราะเร็วสุดสำหรับ V0 นี้

1. Push repo ขึ้น GitHub
2. Import repo เข้า Vercel
3. ใส่ Environment Variables ตาม `.env.example`
   - `ADMIN_SESSION_SECRET` ต้องตั้ง และยาวอย่างน้อย 16 ตัวอักษร ถ้าไม่ตั้ง หน้า `/admin` จะเข้าไม่ได้เลย (ตั้งใจให้ fail ปิด ไม่มีค่า default)
     สร้างค่าแบบสุ่มด้วย `openssl rand -hex 32` แล้ววางใน Vercel → Project Settings → Environment Variables
     (Production, และ Preview ด้วยถ้าทดสอบ admin บน preview) — อย่า commit ค่านี้ไว้ในโค้ดหรือไฟล์ `.env.example`
   - ตั้ง `TDR_ADMIN_PASSWORD` (รหัสเดียวใช้ร่วมกัน) หรือ `TDR_ADMIN_USERS` (แยกรหัสรายคน ให้ session รู้ว่าใครแก้)
4. Deploy
5. ชี้ custom domain ของ TDR มาที่ Vercel

Production deployment ของ Vercel ผูกกับ `main`; push เข้า `main` จะเป็นตัว trigger production build/deploy.

อย่า expose `SUPABASE_SECRET_KEY` หรือ legacy `SUPABASE_SERVICE_ROLE_KEY` ฝั่ง browser
ให้ตั้งเฉพาะ server/runtime และตรวจว่า key เป็นของ project เดียวกับ `SUPABASE_URL`
