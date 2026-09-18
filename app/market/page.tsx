import Link from "next/link";
import { getPublicMarket, PUBLIC_BRAND_LIMIT } from "@/lib/public-market";
import { MarketCharts } from "./MarketCharts";
import { groupedNumber } from "@/components/charts/format";

export const dynamic = "force-dynamic";

/**
 * Layer 2, in public: the shape of the Thai market for the latest published
 * month, at brand grain.
 *
 * Deliberately a window, not the shop. The month is the newest one, not one
 * the reader chose; the grain is the brand, never the model; the ranking stops
 * at eight and folds the rest into one slice. Choosing the window, the
 * dimension and the filters, reading it per model, going back further, and
 * taking it away as a file are what an account is for, and they are unchanged.
 */
export default async function MarketPage() {
  const market = await getPublicMarket();

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
        <MarketCharts market={market} />

        <section className="marketTableWrap" aria-label="ตารางส่วนแบ่งตลาดรายแบรนด์">
          {/* The table is not a duplicate of the donut: three of the palette's
              hues sit below 3:1 against this surface, and exact figures beside
              the chart are the relief that requires. */}
          <table className="marketTable">
            <thead><tr><th>#</th><th>แบรนด์</th><th>จดทะเบียน</th><th>ส่วนแบ่ง</th></tr></thead>
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
                  <td><b>แบรนด์อื่น</b></td>
                  <td>{groupedNumber(market.others.registrations)}</td>
                  <td>{groupedNumber(market.others.sharePct, 2)}%</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </section>

        <section className="marketMore">
          <div>
            <b>หน้านี้แสดงงวดล่าสุด ระดับแบรนด์ {PUBLIC_BRAND_LIMIT} อันดับแรก</b>
            <span>เลือกช่วงเวลาเอง ดูรายรุ่น แยกตามเซกเมนต์/ประเภทจดทะเบียน ย้อนหลังมากกว่านี้ และดาวน์โหลด อยู่ในบัญชีสมาชิก</span>
          </div>
          <Link className="sfBtn" href="/member/market">เปิดมุมมองเต็ม</Link>
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
