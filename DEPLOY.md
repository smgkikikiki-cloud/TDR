# Deploy path

แนะนำ Vercel + Supabase เพราะเร็วสุดสำหรับ V0 นี้

1. Push repo ขึ้น GitHub
2. Import repo เข้า Vercel
3. ใส่ Environment Variables ตาม `.env.example`
   - `ADMIN_SESSION_SECRET` ต้องตั้ง และยาวอย่างน้อย 16 ตัวอักษร ถ้าไม่ตั้ง หน้า `/admin` จะเข้าไม่ได้เลย (ตั้งใจให้ fail ปิด ไม่มีค่า default)
   - ตั้ง `TDR_ADMIN_PASSWORD` (รหัสเดียวใช้ร่วมกัน) หรือ `TDR_ADMIN_USERS` (แยกรหัสรายคน ให้ session รู้ว่าใครแก้)
4. Deploy
5. ชี้ custom domain ของ TDR มาที่ Vercel

อย่า expose `SUPABASE_SERVICE_ROLE_KEY` ฝั่ง browser — โค้ด V0 ใช้มันเฉพาะ server action ใน admin เท่านั้น
