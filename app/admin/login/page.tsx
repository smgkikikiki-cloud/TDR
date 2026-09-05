import { loginAction } from "@/app/admin/actions";
import { hasSessionSecret } from "@/lib/admin-auth";

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const params = await searchParams;
  const misconfigured = params.error === "config" || !hasSessionSecret();
  return <div className="adminLoginPage">
    <form action={loginAction} className="adminLoginCard">
      <div className="adminBrand">TDR <b>AUTO</b></div>
      <h1>เข้าสู่ระบบ Editor</h1>
      <p>หลังบ้านสำหรับแก้ไขฐานข้อมูลและข่าวของ TDR Automotive Intelligence</p>
      {misconfigured
        ? <div className="adminError">เซิร์ฟเวอร์ยังไม่ได้ตั้งค่า <b>ADMIN_SESSION_SECRET</b> (ต้องยาวอย่างน้อย 16 ตัวอักษร) จึงเข้าสู่ระบบไม่ได้</div>
        : params.error ? <div className="adminError">ชื่อผู้แก้ไขหรือรหัสผ่านไม่ถูกต้อง</div> : null}
      <label><span>ชื่อผู้แก้ไข</span><input name="name" autoComplete="username" autoFocus /></label>
      <label><span>รหัสผ่าน</span><input name="password" type="password" autoComplete="current-password" required /></label>
      <button type="submit" className="adminPrimary" disabled={misconfigured}>เข้าสู่ระบบ</button>
    </form>
  </div>;
}
