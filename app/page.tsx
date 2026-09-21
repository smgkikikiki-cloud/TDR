import Link from "next/link";
import { getCanonicalBrands, getCanonicalModels } from "@/lib/canonical-data";
import { bodyLabel } from "@/lib/body-labels";
import { displayName, initials } from "@/lib/display-name";
import { resolveBrandLogo } from "@/lib/brand-logo-fallback";
import { getPublishedResearchArticles } from "@/lib/research";
import { getHomeMarket } from "@/lib/home-market";
import { PLAN_CATALOG } from "@/lib/plans";
import { HomeMarketLine } from "@/components/HomeMarketLine";
import { groupedNumber } from "@/components/charts/format";

export const dynamic = "force-dynamic";

function baht(min: any, max: any) {
  const f = (n: number) => groupedNumber(Number(n));
  if (!min && !max) return null;
  return min && max && min !== max ? `฿${f(min)}–฿${f(max)}` : `฿${f(min || max)}`;
}

function modelScore(r: any): number {
  const price = r.retail_price_min || r.retail_price_max ? 4 : 0;
  const powertrain = (r.powertrains || []).length ? 2 : 0;
  const body = r.body_type ? 2 : 0;
  const image = r.image_url ? 2 : 0;
  const mass = String(r.market_position || "").toLowerCase() === "mass" ? 2 : 0;
  const local = r.production_type === "CKD" || r.production_type === "SKD" ? 1 : 0;
  return price + powertrain + body + image + mass + local;
}

function monthLabel(period: string, short = false) {
  const match = String(period || "").match(/^(\d{4})-(\d{2})/);
  if (!match) return period;
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, 1));
  return new Intl.DateTimeFormat("th-TH", {
    month: short ? "short" : "long",
    year: short ? "2-digit" : "numeric",
    timeZone: "UTC",
  }).format(date);
}

function normalizedBrandKey(value: unknown) {
  return String(value || "").normalize("NFKD").toLowerCase().replace(/[^a-z0-9ก-๙]+/g, "");
}

function textInitials(value: string) {
  const words = String(value || "").trim().split(/\s+/).filter(Boolean);
  if (!words.length) return "TDR";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return `${words[0][0] || ""}${words[1][0] || ""}`.toUpperCase();
}

const BODY_ENTRIES = [
  ["PICKUP", "กระบะ"],
  ["CROSSOVER", "ครอสโอเวอร์ / SUV"],
  ["SEDAN", "ซีดาน"],
  ["PPV", "PPV"],
  ["MPV", "MPV"],
  ["HATCHBACK", "แฮทช์แบ็ก"],
] as const;

function ModelPreview({ model }: { model: any }) {
  const brand = displayName(model.brands);
  return (
    <article className="homeCompareCar">
      <div className="homeCompareShot">
        {model.image_url
          ? <img src={model.image_url} alt={`${brand} ${displayName(model)}`} />
          : <><small>{brand || "TDR"}</small><b>{displayName(model)}</b></>}
      </div>
      <div className="homeCompareCopy">
        <small>{brand}</small>
        <h3>{displayName(model)}</h3>
        <p>{[
          (model.powertrains || []).join(" / "),
          bodyLabel(model.body_type),
          model.production_type,
        ].filter(Boolean).join(" · ")}</p>
        <strong>{baht(model.retail_price_min, model.retail_price_max) || "ยังไม่ประกาศราคา"}</strong>
      </div>
    </article>
  );
}

export default async function Home() {
  const [brands, models, market, research] = await Promise.all([
    getCanonicalBrands(150),
    getCanonicalModels(600),
    getHomeMarket(),
    getPublishedResearchArticles(4),
  ]);

  const current = (models as any[]).filter((r) => String(r.status || "current").toLowerCase() !== "discontinued");
  const compareModels = [...current].sort((a, b) => modelScore(b) - modelScore(a)).slice(0, 2);
  const currentBrands = new Set(current.map((r) => r.brands?.slug).filter(Boolean));
  const brandRows = (brands as any[]).filter((brand) => currentBrands.has(brand.slug)).slice(0, 12);
  const proFrom = Math.min(...PLAN_CATALOG.map((plan) => plan.priceThbPerMonth));
  const maxBrand = market?.brands?.[0]?.registrations || 1;
  const positiveMover = market?.movers?.find((row) => row.delta > 0) || null;

  const logoByBrandKey = new Map<string, string>();
  for (const brand of brands as any[]) {
    const logo = resolveBrandLogo(brand.slug, brand.logo_url);
    if (!logo) continue;
    for (const value of [brand.slug, brand.name_en, brand.name_th, displayName(brand), brand.id, brand.canonical_id, brand.editorial_id]) {
      const key = normalizedBrandKey(value);
      if (key) logoByBrandKey.set(key, logo);
    }
  }
  const marketLogo = (row: any) => logoByBrandKey.get(normalizedBrandKey(row.key))
    || logoByBrandKey.get(normalizedBrandKey(row.label))
    || null;

  return <div className="homeV2">
    <section className="homeHero">
      <div className="homeHeroCopy">
        <div className="sfEyebrow">TDR AUTOMOTIVE INTELLIGENCE</div>
        <h1>ข้อมูลตลาด<br />รถยนต์ไทย</h1>
        <div className="homeFactLine">ยอดจดทะเบียน · ราคา · รุ่นย่อย · สเปก · ส่วนแบ่งตลาด</div>

        <form className="homeSearch" action="/search" role="search">
          <svg width="19" height="19" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><circle cx="9" cy="9" r="6" /><path d="M13.5 13.5 17 17" /></svg>
          <input name="q" placeholder="ค้นหารุ่นรถหรือแบรนด์" aria-label="ค้นหารุ่นรถหรือแบรนด์" />
          <button type="submit">ค้นหา</button>
        </form>

        <div className="homeEntrances">
          <Link href="/market"><span>01</span><b>ข้อมูลตลาดรถยนต์</b><small>ยอดจดทะเบียนและส่วนแบ่งตลาด</small><i>→</i></Link>
          <Link href="/compare"><span>02</span><b>เปรียบเทียบรถ</b><small>เทียบข้อมูลตรงรุ่นย่อย</small><i>→</i></Link>
          <Link href="/models"><span>03</span><b>ฐานข้อมูลรถยนต์</b><small>{groupedNumber(current.length)} รุ่นที่ยังจำหน่าย</small><i>→</i></Link>
        </div>
      </div>

      <Link className="homeHeroMarket" href="/market" aria-label="เปิดข้อมูลตลาดรถยนต์">
        <div className="homeHeroMarketHead">
          <div><span>MARKET SNAPSHOT</span><b>ข้อมูลตลาดล่าสุด</b></div>
          <i>↗</i>
        </div>
        {market ? <>
          <div className="homeMarketTotal">
            <strong>{groupedNumber(market.totalRegistrations)}</strong>
            <span>คัน · {monthLabel(market.period)}</span>
          </div>
          <div className="homeHeroShareBlock">
            <span className="homeHeroShareLabel">ส่วนแบ่งแบรนด์อันดับต้น</span>
            <div className="homeHeroBrands">
              {market.brands.slice(0, 3).map((brand) => {
                const logo = marketLogo(brand);
                return <div className="homeHeroBrand" key={brand.key}>
                  <span className="homeHeroBrandLogo">
                    {logo ? <img src={logo} alt="" /> : <b>{textInitials(brand.label)}</b>}
                  </span>
                  <span className="homeHeroBrandCopy"><b>{brand.label}</b><em>{groupedNumber(brand.sharePct, 1)}%</em></span>
                </div>;
              })}
            </div>
          </div>
          {positiveMover ? <div className="homeHeroMover">
            <span>เพิ่มขึ้นจากเดือนก่อน</span>
            <b>{positiveMover.label}</b>
            <em>+{groupedNumber(positiveMover.delta)} คัน</em>
          </div> : null}
        </> : <div className="homeMarketUnavailable">ยังไม่มีงวดข้อมูลที่เผยแพร่ได้</div>}
      </Link>
    </section>

    <section className="homeMarketSection">
      <div className="homeSectionHead">
        <div><div className="sfEyebrow ink">MARKET INTELLIGENCE</div><h2>สำรวจตลาดรถยนต์ไทย</h2></div>
        <Link href="/market">เปิดข้อมูลตลาด →</Link>
      </div>

      {market ? (
        <Link className="homeMarketPreview" href="/market" aria-label="เปิด Market Intelligence">
          <div className="homeTrendPanel">
            <div className="homePanelHead">
              <div><span>MARKET SIZE TREND</span><b>ยอดจดทะเบียนรวมรายเดือน</b></div>
              <small>ย้อนหลัง {market.trend.length} เดือน</small>
            </div>
            <HomeMarketLine
              labels={market.trend.map((point) => monthLabel(point.period, true))}
              points={market.trend.map((point) => point.total)}
            />
          </div>

          <div className="homeRankingPanel">
            <div className="homePanelHead">
              <div><span>BRAND SHARE</span><b>{monthLabel(market.period)}</b></div>
              <small>{groupedNumber(market.totalRegistrations)} คัน</small>
            </div>
            <div className="homeRankBars">
              {market.brands.slice(0, 6).map((brand, index) => (
                <div className="homeRankRow" key={brand.key}>
                  <span>{index + 1}</span>
                  <b>{brand.label}</b>
                  <div><i style={{ width: `${Math.max(4, (brand.registrations / maxBrand) * 100)}%` }} /></div>
                  <em>{groupedNumber(brand.sharePct, 1)}%</em>
                </div>
              ))}
            </div>
            <div className="homeMarketOpen">ดูรายละเอียดและเลือกมุมมองตลาด <b>→</b></div>
          </div>
        </Link>
      ) : (
        <Link className="homeMarketPreview homeMarketEmpty" href="/market">ยังไม่มีงวดข้อมูลที่เผยแพร่ได้ <b>เปิดหน้าข้อมูลตลาด →</b></Link>
      )}
    </section>

    <section className="homeCompareSection">
      <div className="homeSectionHead">
        <div><div className="sfEyebrow ink">VEHICLE COMPARE</div><h2>เทียบรถตรงรุ่นย่อย</h2></div>
        <Link href="/compare">เริ่มเปรียบเทียบรถ →</Link>
      </div>
      <div className="homeCompareLayout">
        <div className="homeCompareCars">
          {compareModels.map((model) => <ModelPreview key={model.id} model={model} />)}
          {compareModels.length >= 2 ? <div className="homeCompareVs">VS</div> : null}
        </div>
        <div className="homeCompareFacts">
          <div><span>เลือกได้สูงสุด</span><strong>4</strong><small>รุ่นย่อยต่อครั้ง</small></div>
          <div><span>ไม่เข้าสู่ระบบ</span><strong>10</strong><small>ครั้ง / วัน</small></div>
          <Link href="/compare">เริ่มเปรียบเทียบ →</Link>
        </div>
      </div>
    </section>

    <section className="homeDatabaseSection">
      <div className="homeSectionHead">
        <div><div className="sfEyebrow ink">VEHICLE DATABASE</div><h2>ฐานข้อมูลรถยนต์ในประเทศไทย</h2></div>
        <Link href="/models">ดูฐานข้อมูลรถทั้งหมด →</Link>
      </div>

      <div className="homeDatabaseStats">
        <div><strong>{groupedNumber(current.length)}</strong><span>รุ่นที่ยังจำหน่าย</span></div>
        <div><strong>{groupedNumber(currentBrands.size)}</strong><span>แบรนด์</span></div>
        <div><strong>{groupedNumber(current.filter((r) => r.production_type === "CKD" || r.production_type === "SKD").length)}</strong><span>รุ่นประกอบในไทย</span></div>
      </div>

      <div className="homeBodyLinks">
        {BODY_ENTRIES.map(([value, label]) => {
          const count = current.filter((row) => row.body_type === value).length;
          return <Link key={value} href={`/models?body=${value}`}><b>{label}</b><span>{groupedNumber(count)}</span></Link>;
        })}
      </div>

      <div className="homeBrandRail">
        {brandRows.map((brand: any) => {
          const logo = resolveBrandLogo(brand.slug, brand.logo_url);
          return <Link key={brand.id} href={`/brands/${brand.slug}`}>
            {logo ? <img src={logo} alt="" /> : <span>{initials(brand)}</span>}
            <b>{displayName(brand)}</b>
          </Link>;
        })}
      </div>
    </section>

    <section className="homeAnalysisSection">
      <div className="homeSectionHead">
        <div><div className="sfEyebrow ink">TDR ANALYSIS</div><h2>บทวิเคราะห์ตลาดรถยนต์ไทย</h2></div>
        <Link href="/research">ดูบทวิเคราะห์ →</Link>
      </div>
      {research.length ? (
        <div className="homeAnalysisGrid">
          {research.map((piece) => (
            <Link href={`/research/${piece.slug}`} key={piece.id}>
              <time>{piece.publishedAt.slice(0, 10)}</time>
              <h3>{piece.titleTh}</h3>
              <p>{piece.summaryTh}</p>
            </Link>
          ))}
        </div>
      ) : (
        <div className="homeAnalysisReserved"><b>ยังไม่มีบทวิเคราะห์เผยแพร่</b></div>
      )}
    </section>

    <section className="homeCommercial">
      <div className="homeProBlock">
        <div className="sfEyebrow">TDR PRO</div>
        <h2>Market Intelligence แบบเต็ม</h2>
        <div className="homeProFacts">
          <span>รายรุ่น</span><span>Rolling 3 / 6 / 12</span><span>YTD</span><span>YoY</span><span>ตัวกรองตลาด</span>
        </div>
        <div className="homeProPrice">เริ่ม ฿{groupedNumber(proFrom)} / เดือน</div>
        <Link href="/pricing">ดูแพ็กเกจ →</Link>
      </div>
      <div className="homeEnterpriseBlock">
        <div className="sfEyebrow ink">ENTERPRISE</div>
        <h2>TDR Enterprise</h2>
        <div className="homeEnterpriseFacts">API / data integration · raw export · ทีมสนับสนุนเฉพาะ</div>
        <Link href="/pricing">รายละเอียด Enterprise →</Link>
      </div>
    </section>
  </div>;
}
