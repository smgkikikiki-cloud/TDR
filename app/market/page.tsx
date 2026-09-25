import Link from "next/link";
import { getPublicMarket, PUBLIC_BRAND_LIMIT } from "@/lib/public-market";
import { MarketCharts } from "./MarketCharts";
import { groupedNumber } from "@/components/charts/format";

export const dynamic = "force-dynamic";

/**
 * Public market snapshot: the latest published month at brand grain.
 *
 * Merely opening or refreshing /market never spends quota. Anonymous readers
 * can always see this default snapshot. Changing dimension/window/filter,
 * comparing periods, drilling down to model grain, and other analysis actions
 * live in /member/market, where the member policy is enforced server-side.
 */
export default async function MarketPage() {
  const market = await getPublicMarket("brand");
  const dimensionLabel = "แบรนด์";

  return <div className="marketPage">
    <section className="sfPageHead">
      <div>
        <div className="sfEyebrow">ข้อมูลตลาดรถยนต์</div>
        <h1>ยอดจดทะเบียนรถยนต์ในประเทศไทย</h1>
      </div>
      {market ? (
        <div className="sfPageHeadAside">
          <div className="sfEyebrow ink">งวดล่าสุด</div>
          <b className="sfNum">{market.period}</b>
          <span>{groupedNumber(market.totalRegistrations)} คัน</span>
        </div>
      ) : null}
    </section>

    {market ? (
      <>
        <MarketCharts market={market} title={dimensionLabel} />

        <section className="marketTableWrap" aria-label="ตารางส่วนแบ่งตลาดรายแบรนด์">
          <table className="marketTable">
            <thead><tr><th>#</th><th>{dimensionLabel}</th><th>จดทะเบียน</th><th>ส่วนแบ่ง</th></tr></thead>
            <tbody>
              {market.brands.map((brand, index) => (
                <tr key={brand.key}>
                  <td>{index + 1}</td>
                  <td><b>{brand.label}</b></td>
                  <td>{groupedNumber(brand.registrations)}</td>
                  <td>{groupedNumber(brand.sharePct, 2)}%</td>
                </tr>
              ))}
              {market.others ? (
                <tr className="marketTableOthers">
                  <td>—</td>
                  <td><b>อื่นๆ</b></td>
                  <td>{groupedNumber(market.others.registrations)}</td>
                  <td>{groupedNumber(market.others.sharePct, 2)}%</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </section>

        <section className="marketMore">
          <div>
            <b>หน้านี้เป็น snapshot สาธารณะของงวดล่าสุด {PUBLIC_BRAND_LIMIT} อันดับแรก</b>
            <span>การเปลี่ยนมุมมอง ช่วงเวลา เปรียบเทียบช่วง กรองข้อมูล และดูรายรุ่น เริ่มในบัญชีสมาชิก</span>
          </div>
          <Link className="sfBtn" href="/member/market">เริ่มวิเคราะห์ตลาด</Link>
        </section>

        <p className="marketNote">
          ตัวเลขคือยอดจดทะเบียนรถใหม่จากกรมการขนส่งทางบก ไม่ใช่ยอดขายของผู้ผลิต
          แบรนด์ที่จับคู่กับแคตตาล็อกไม่ได้จะไม่ถูกนับในส่วนแบ่ง
        </p>
      </>
    ) : (
      <section className="sfEmpty">
        <b>ยังไม่มีงวดข้อมูลที่เผยแพร่ได้</b>
        <span>เมื่อมีงวดใหม่เข้าระบบ หน้านี้จะแสดงทันทีโดยไม่ต้องแก้อะไร</span>
      </section>
    )}
  </div>;
}
