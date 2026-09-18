import Link from "next/link";
import { headers } from "next/headers";
import { getPublicMarket, isPublicDimension, PUBLIC_BRAND_LIMIT, PUBLIC_DIMENSIONS } from "@/lib/public-market";
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
export default async function MarketPage({ searchParams }: {
  searchParams: Promise<{ by?: string }>;
}) {
  const { by } = await searchParams;
  const dimension = isPublicDimension(by) ? by : "brand";
  // middleware.ts counts the anonymous day's views and leaves what is left
  // here. A signed-in reader is never counted, so the header is absent.
  const remaining = (await headers()).get("x-tdr-market-remaining");
  const locked = remaining !== null && Number(remaining) <= 0;
  const market = await getPublicMarket(dimension);
  const dimensionLabel = PUBLIC_DIMENSIONS.find((item) => item.value === dimension)!.label;

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

    {/* What the market is cut BY is open; which slice of it you look at is
        not. Links rather than a control, so each cut is its own address. */}
    <nav className="marketCuts" aria-label="มุมมองตลาด">
      {PUBLIC_DIMENSIONS.map((item) => (
        <Link key={item.value} href={item.value === "brand" ? "/market" : `/market?by=${item.value}`}
              className={item.value === dimension ? "on" : undefined}
              aria-current={item.value === dimension ? "page" : undefined}>
          {item.label}
        </Link>
      ))}
    </nav>

    {locked ? (
      <section className="marketLock">
        <div className="marketLockBody" aria-hidden="true">
          {market ? <MarketCharts market={market} title={dimensionLabel} /> : null}
        </div>
        <div className="marketLockCard">
          <b>ดูฟรีได้วันละ 1 ครั้ง · วันนี้ใช้ไปแล้ว</b>
          <span>สมัครบัญชีฟรีเพื่อดูได้ทุกวัน เปลี่ยนมุมมองได้ 5 ครั้งต่อวัน และดาวน์โหลดได้เดือนละครั้ง</span>
          <Link className="sfBtn" href="/member/login?next=%2Fmarket">สมัครฟรี / เข้าสู่ระบบ</Link>
        </div>
      </section>
    ) : market ? (
      <>
        <MarketCharts market={market} title={dimensionLabel} />

        <section className="marketTableWrap" aria-label="ตารางส่วนแบ่งตลาดรายแบรนด์">
          {/* The table is not a duplicate of the donut: three of the palette's
              hues sit below 3:1 against this surface, and exact figures beside
              the chart are the relief that requires. */}
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
            <b>หน้านี้แสดงงวดล่าสุด {PUBLIC_BRAND_LIMIT} อันดับแรกของแต่ละมุมมอง</b>
            <span>เลือกช่วงเวลาเอง (rolling 3/6/12, YTD) เทียบปีต่อปี ดูรายรุ่น กรองตามแบรนด์/segment/ตัวถัง/ประเภทจดทะเบียน ย้อนหลังมากกว่านี้ และดาวน์โหลด อยู่ในบัญชีสมาชิก</span>
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
