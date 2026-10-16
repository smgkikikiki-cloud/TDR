import { getPublicMarket, PUBLIC_BRAND_LIMIT, type PublicMarket } from "@/lib/public-market";
import { getPublicMarketIce } from "@/lib/ice-public-market";
import { MarketCharts } from "./MarketCharts";
import { groupedNumber } from "@/components/charts/format";
import { Button, Card, Delta, Flag, KpiCard, LockedBlock, PageHead, Table, TierBadge } from "@/components/design";
import "./market.css";

export const dynamic = "force-dynamic";

/**
 * Public market snapshot: the latest published month at brand grain.
 *
 * Merely opening or refreshing /market never spends quota. Anonymous readers
 * can always see this default snapshot. Changing dimension/window/filter,
 * comparing periods, drilling down to model grain, and other analysis actions
 * live in /member/market, where the member policy is enforced server-side.
 *
 * Presentation only (design graft, tokens + shared components): the data path below is unchanged.
 */
export default async function MarketPage() {
  // R8 controlled cutover only. Default remains the existing public market.
  // Preview may show real Ice brand-only numbers for non-production QA.
  // Production MUST await approved R6/R7 and owner R8 cutover permission.
  const iceLive = process.env.VERCEL_ENV === "preview"
    || process.env.TDR_ICE_R8_LIVE_CUTOVER === "approved";
  const dimensionLabel = "แบรนด์";

  let market: PublicMarket | null = null;
  let failed = false;
  try {
    market = iceLive ? await getPublicMarketIce("brand") : await getPublicMarket("brand");
  } catch {
    failed = true;
  }

  return <div className="designPage tdr-market">
    <div className="tdr-wrap">
      <PageHead
        eyebrow="ข้อมูลตลาดรถยนต์"
        title="ยอดจดทะเบียนรถยนต์ในประเทศไทย"
        lead={`ส่วนแบ่งตลาดรายแบรนด์ ${PUBLIC_BRAND_LIMIT} อันดับแรกของงวดล่าสุด จากข้อมูลจดทะเบียนรถใหม่`}
        aside={market ? <Flag kind="source">ที่มา: กรมการขนส่งทางบก</Flag> : undefined}
      />

      {failed ? (
        <Card tone="dashed" className="tdr-market-state">
          <div role="alert">
            <b className="tdr-card__title">ข้อมูลตลาด</b>
            <p>โหลดข้อมูลไม่สำเร็จ · <a href="/market">ลองอีกครั้ง</a></p>
          </div>
        </Card>
      ) : market ? <MarketBody market={market} dimensionLabel={dimensionLabel} iceLive={iceLive} /> : (
        <Card tone="dashed" className="tdr-market-state">
          <b className="tdr-card__title">ยังไม่มีงวดข้อมูลที่เผยแพร่ได้</b>
          <p>เมื่อมีงวดใหม่เข้าระบบ หน้านี้จะแสดงทันทีโดยไม่ต้องแก้อะไร</p>
        </Card>
      )}
    </div>
  </div>;
}

function MarketBody({ market, dimensionLabel, iceLive }: { market: PublicMarket; dimensionLabel: string; iceLive: boolean }) {
  const top = market.brands[0];
  const previous = market.trend.find((t) => t.period === market.previousPeriod)?.total ?? null;
  const changePct = previous != null && previous > 0 ? ((market.totalRegistrations - previous) / previous) * 100 : null;
  const namedShare = market.brands.reduce((sum, brand) => sum + brand.sharePct, 0);

  return (
    <>
      <section className="tdr-kpis tdr-market-kpis" aria-label="ตัวเลขสำคัญของงวดล่าสุด">
        <KpiCard
          label={`ยอดจดทะเบียนงวด ${market.period}`} value={market.totalRegistrations} unit="คัน" size="lg"
          delta={market.previousPeriod ? <Delta value={changePct} unit="%" base={previous} /> : undefined}
          note={market.previousPeriod ? `เทียบ ${market.previousPeriod}` : undefined} />
        {top ? <KpiCard label={`${dimensionLabel}อันดับ 1`} value={top.label} note={`${groupedNumber(top.sharePct, 1)}% ของยอดรวม · ${groupedNumber(top.registrations)} คัน`} /> : null}
        <KpiCard label={`${market.brands.length} อันดับแรกรวมกัน`} value={groupedNumber(namedShare, 1)} unit="%" note={market.others ? `อื่นๆ ${groupedNumber(market.others.sharePct, 1)}%` : undefined} />
      </section>

      <MarketCharts market={market} title={dimensionLabel} />

      <section className="tdr-market-table" aria-label="ตารางส่วนแบ่งตลาดรายแบรนด์">
        <Table caption={`ส่วนแบ่งตลาดรายแบรนด์ งวด ${market.period}`}>
          <thead><tr><th scope="col" className="tdr-num">#</th><th scope="col">{dimensionLabel}</th><th scope="col" className="tdr-num">จดทะเบียน (คัน)</th><th scope="col" className="tdr-num">ส่วนแบ่ง</th></tr></thead>
          <tbody>
            {market.brands.map((brand, index) => (
              <tr key={brand.key}>
                <td className="tdr-num">{index + 1}</td>
                <th scope="row">{brand.label}</th>
                <td className="tdr-num">{groupedNumber(brand.registrations)}</td>
                <td className="tdr-num">{groupedNumber(brand.sharePct, 2)}%</td>
              </tr>
            ))}
            {market.others ? (
              <tr className="tdr-market-table__others">
                <td className="tdr-num">—</td>
                <th scope="row">อื่นๆ</th>
                <td className="tdr-num">{groupedNumber(market.others.registrations)}</td>
                <td className="tdr-num">{groupedNumber(market.others.sharePct, 2)}%</td>
              </tr>
            ) : null}
          </tbody>
        </Table>
      </section>

      <section className="tdr-market-pro" aria-labelledby="market-pro-title">
        <h2 id="market-pro-title" className="tdr-market-h2">ลึกกว่านี้ในบัญชีสมาชิก</h2>
        <p className="tdr-market-pro__lead">หน้านี้แสดงเฉพาะภาพรวมระดับแบรนด์ของงวดล่าสุด มุมมองต่อไปนี้ต้องมีบัญชี และยังไม่ได้แสดงตัวเลขจริงบนหน้าสาธารณะ</p>
        <div className="tdr-market-pro__grid">
          <LockedBlock tier="pro" height={96} message="ยอดจดทะเบียนรายรุ่น สำหรับสมาชิก Pro" />
          <LockedBlock tier="pro" height={96} message="เทียบช่วงเดียวกันของปีก่อน และย้อนหลัง 6/12 เดือน สำหรับสมาชิก Pro" />
          <LockedBlock tier="pro" height={96} message="กรองตามแบรนด์ เซกเมนต์ และตัวถัง สำหรับสมาชิก Pro" />
        </div>
        <p className="tdr-market-note">ยังไม่มีข้อมูลรายจังหวัดในระบบ จึงไม่แสดงมุมมองนี้</p>
      </section>

      <section className="tdr-market-plans" aria-labelledby="market-plans-title">
        <h2 id="market-plans-title" className="tdr-market-h2">เลือกระดับการใช้งาน</h2>
        <div className="tdr-market-plans__grid">
          <Card as="article" className="tdr-market-plan">
            <TierBadge tier="free" />
            <b className="tdr-card__title">ดูภาพรวมตลาด</b>
            <ul>
              <li>snapshot งวดล่าสุด ระดับแบรนด์ ไม่ต้องมีบัญชี</li>
              <li>สมัครสมาชิกฟรีเพื่อวิเคราะห์เพิ่ม (วันละ 5 ครั้ง ย้อนหลัง 12 เดือน)</li>
            </ul>
            <Button variant="accent" href="/member/market">เริ่มวิเคราะห์ตลาด</Button>
          </Card>
          <Card as="article" className="tdr-market-plan" tone="raised">
            <TierBadge tier="pro" />
            <b className="tdr-card__title">วิเคราะห์เต็มรูปแบบ</b>
            <ul>
              <li>รายรุ่น กรองข้อมูล เทียบปีต่อปี ย้อนหลังทั้งคลัง</li>
              <li>ส่งออกข้อมูลได้ไม่จำกัด ไม่มีลายน้ำ</li>
            </ul>
            <Button variant="secondary" href="/pricing">ดูแผน Pro</Button>
          </Card>
          <Card as="article" className="tdr-market-plan">
            <TierBadge tier="enterprise" />
            <b className="tdr-card__title">สำหรับทีมและองค์กร</b>
            <ul>
              <li>ใช้งานร่วมกันหลายคนในองค์กร</li>
              <li>ปรับตามโจทย์จริง คุยกับทีมงานก่อน</li>
            </ul>
            <Button variant="contact" href="/contact">ติดต่อทีมงาน</Button>
          </Card>
        </div>
      </section>

      <p className="tdr-market-source">
        ที่มา: ข้อมูลจดทะเบียนรถใหม่จากกรมการขนส่งทางบก · รวบรวมและวิเคราะห์โดย TDR Automotive Intelligence ·
        ตัวเลขคือยอดจดทะเบียน ไม่ใช่ยอดขายของผู้ผลิต ·{" "}
        {iceLive
          ? "ข้อมูลนี้นับทุกแบรนด์ตามทะเบียนจริง แม้ยังจับคู่กับแคตตาล็อก TDR ไม่ได้"
          : "แบรนด์ที่จับคู่กับแคตตาล็อกไม่ได้จะไม่ถูกนับในส่วนแบ่ง"}
      </p>
    </>
  );
}
