# Deploy path

แนะนำ Vercel + Supabase เพราะเร็วสุดสำหรับ V0 นี้

1. Push repo ขึ้น GitHub
2. Import repo เข้า Vercel
3. ใส่ Environment Variables ตาม `.env.example`
4. Deploy
5. ชี้ custom domain ของ TDR มาที่ Vercel

อย่า expose `SUPABASE_SERVICE_ROLE_KEY` ฝั่ง browser — โค้ด V0 ใช้มันเฉพาะ server action ใน admin เท่านั้น
