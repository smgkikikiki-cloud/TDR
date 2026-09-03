import { loginAction } from "@/app/admin/actions";

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const params = await searchParams;
  return <div className="adminLoginPage">
    <form action={loginAction} className="adminLoginCard">
      <div className="adminBrand">TDR <b>AUTO</b></div>
      <h1>เข้าสู่ระบบ Editor</h1>
      <p>หลังบ้านสำหรับแก้ไขฐานข้อมูลและข่าวของ TDR Automotive Intelligence</p>
      {params.error ? <div className="adminError">รหัสผ่านไม่ถูกต้อง</div> : null}
      <label><span>Admin password</span><input name="password" type="password" required autoFocus/></label>
      <button type="submit" className="adminPrimary">เข้าสู่ระบบ</button>
    </form>
  </div>;
}
