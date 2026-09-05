import Link from "next/link";
import { getPlantsWithStats, getProductionPrograms } from "@/lib/data";

const num = (n: any) => Number(n).toLocaleString();

/** Plants read down the page by maker: Toyota's sites together, then Honda's,
 *  and so on, biggest declared capacity first. Contract assemblers and any
 *  plant with no maker_group fall into the last group, which is where they
 *  belong without needing an "importance" flag nobody maintains. */
const OTHER = "__other__";

export default async function ProductionPage({ searchParams }: { searchParams: Promise<{ view?: string }> }) {
  const sp = await searchParams;
  const byModel = sp.view === "model";
  const [plants, programs] = await Promise.all([getPlantsWithStats(), getProductionPrograms(300)]);

  // This page is a catalogue of what Thailand builds now, not an archive of what
  // it used to. A plant whose status is no longer active drops off it entirely,
  // rather than being listed with a caveat nobody asked for. The status is still
  // read, so a plant that closes disappears on the next load instead of quietly
  // going on counting toward capacity.
  const rows = (plants as any[])
    .filter((p) => String(p.status || "active").toLowerCase() === "active")
    .map((p) => {
      const seen = new Set<string>();
      const models = (p.active_programs || [])
        .map((x: any) => x.models)
        .filter((m: any) => m && !seen.has(m.id) && seen.add(m.id));
      return { ...p, models };
    });

  const provinces = new Set(rows.map((p) => p.province).filter(Boolean));
  const modelIds = new Set((programs as any[]).map((r) => r.models?.id).filter(Boolean));
  const declared = rows.filter((p) => Number(p.capacity_annual) > 0);
  const declaredTotal = declared.reduce((s, p) => s + Number(p.capacity_annual), 0);

  const byMaker = new Map<string, any[]>();
  for (const p of rows) {
    const key = (p.maker_group || "").trim() || OTHER;
    byMaker.set(key, [...(byMaker.get(key) || []), p]);
  }
  const capOf = (list: any[]) => list.reduce((s, p) => s + (Number(p.capacity_annual) || 0), 0);
  const plantOrder = (a: any, b: any) =>
    (Number(b.capacity_annual) || 0) - (Number(a.capacity_annual) || 0)
    || b.models.length - a.models.length
    || String(a.name_th).localeCompare(String(b.name_th), "th");

  const makerGroups = [...byMaker.entries()]
    .map(([maker, list]) => ({ maker, list: [...list].sort(plantOrder), capacity: capOf(list) }))
    .sort((a, b) => {
      if (a.maker === OTHER) return 1;
      if (b.maker === OTHER) return -1;
      return b.capacity - a.capacity || b.list.length - a.list.length || a.maker.localeCompare(b.maker, "th");
    });

  return <>
    <div className="sfStrip sfBleed">
      <div className="sfStripItem"><b className="sfNum">{num(modelIds.size)}</b><span>รุ่นที่ผลิตในไทย</span></div>
      <div className="sfStripItem"><b className="sfNum">{num(rows.length)}</b><span>โรงงานในฐานข้อมูล</span></div>
      <div className="sfStripItem"><b className="sfNum">{num(provinces.size)}</b><span>จังหวัด</span></div>
      <div className="sfStripItem">
        {declaredTotal ? <><b className="sfNum">{num(declaredTotal)}</b><span>กำลังผลิตที่ประกาศรวม (คัน/ปี)</span></>
          : <><b className="sfNum">—</b><span>กำลังผลิตที่ประกาศ</span></>}
      </div>
      <div className="sfStripNote">
        นับเฉพาะโรงงานที่อยู่ในฐานข้อมูล TDR{declared.length && declared.length < rows.length ? ` · กำลังผลิตรวมจาก ${declared.length} โรงงานที่ประกาศตัวเลขไว้` : ""} ไม่ใช่กำลังผลิตของทั้งประเทศ
      </div>
    </div>

    <section className="sfPageHead">
      <div>
        <div className="sfEyebrow">THAILAND PRODUCTION</div>
        <h1>โรงงานประกอบรถยนต์ในไทย</h1>
        <p>ค่ายไหนมีโรงงานที่ไหน กำลังผลิตเท่าไหร่ และประกอบรุ่นอะไรบ้าง กดที่ชื่อรุ่นเพื่อไปดูข้อมูลรถรุ่นนั้น</p>
      </div>
      <div className="sfViewToggle">
        <Link className={byModel ? undefined : "on"} href="/production">ตามโรงงาน</Link>
        <Link className={byModel ? "on" : undefined} href="/production?view=model">ตามรุ่น</Link>
      </div>
    </section>

    <div className="sfCatalog sfBleed">
      {byModel ? (
        programs.length ? (
          <div className="sfProgramList">
            {(programs as any[]).map((r: any) => (
              <article key={r.id}>
                <div>
                  {r.models?.slug
                    ? <Link className="sfProgramModel" href={`/models/${r.models.slug}`}>{[r.models.brands?.name_th, r.models.name_th].filter(Boolean).join(" ")}</Link>
                    : <span className="sfMissing">ไม่พบรุ่นที่ผูกไว้</span>}
                  <p>{[r.models?.body_type, r.models?.segment].filter(Boolean).join(" · ") || ""}</p>
                </div>
                <div className="sfProgramPlant">
                  {r.plants?.slug
                    ? <Link href={`/plants/${r.plants.slug}`}>{r.plants.name_th}</Link>
                    : <span className="sfMissing">ยังไม่ระบุโรงงาน</span>}
                  {r.plants?.province ? <em>{r.plants.province}</em> : null}
                </div>
              </article>
            ))}
          </div>
        ) : <div className="sfEmpty"><b>ยังไม่มีโครงการผลิตในฐานข้อมูล</b><span>เมื่อบันทึกโครงการผลิตแล้ว รายการจะขึ้นที่นี่</span></div>
      ) : (
        makerGroups.length ? (
          <div className="sfMakerList">
            {makerGroups.map(({ maker, list, capacity }) => {
              const withCap = list.filter((p: any) => Number(p.capacity_annual) > 0).length;
              return (
                <section key={maker} className={maker === OTHER ? "sfMakerGroup minor" : "sfMakerGroup"}>
                  <div className="sfMakerHead">
                    <h2>{maker === OTHER ? "ผู้รับจ้างประกอบและโรงงานอื่น" : maker}</h2>
                    <span>
                      {list.length} โรงงาน
                      {capacity ? ` · รวมที่ประกาศ ${num(capacity)} คัน/ปี${withCap < list.length ? ` (จาก ${withCap} โรงงาน)` : ""}` : ""}
                    </span>
                  </div>
                  {list.map((p: any) => (
                    <div className="sfPlantRow" key={p.id}>
                      <div className="sfPlantHead">
                        <div className="sfPlantName">
                          <Link href={`/plants/${p.slug}`}>{p.name_th}</Link>
                          {p.province ? <span>{[p.district, p.province].filter(Boolean).join(" · ")}</span> : <span className="sfMissing">ไม่ระบุที่ตั้ง</span>}
                        </div>
                        <div className="sfPlantCap">
                          {Number(p.capacity_annual) > 0
                            ? <><b className="sfNum">{num(p.capacity_annual)}</b><em>คัน/ปี · กำลังผลิตที่ประกาศ</em></>
                            : <span className="sfMissing">ไม่มีข้อมูลกำลังผลิต</span>}
                        </div>
                      </div>
                      {p.models.length ? (
                        <div className="sfModelChips">
                          {p.models.map((m: any) => (
                            <Link key={m.id} href={`/models/${m.slug}`}>{[m.brands?.name_th, m.name_th].filter(Boolean).join(" ")}</Link>
                          ))}
                        </div>
                      ) : <p className="sfMissing">ยังไม่ระบุรุ่นที่ผลิตในโรงงานนี้</p>}
                    </div>
                  ))}
                </section>
              );
            })}
          </div>
        ) : <div className="sfEmpty"><b>ยังไม่มีโรงงานในฐานข้อมูล</b><span>เมื่อบันทึกโรงงานและโครงการผลิตแล้ว รายการจะขึ้นที่นี่</span></div>
      )}
    </div>
  </>;
}
