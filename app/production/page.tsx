import Link from "next/link";
import { getPlantsWithStats, getProductionPrograms } from "@/lib/data";

/** "ผลิตในไทย" and "โรงงาน" were two views of one join, so they are one page.
 *  By plant answers "อยู่ตรงไหน ผลิตรุ่นอะไร"; by model answers the same join
 *  from the other end. Both read the helpers the two old pages already used. */
export default async function ProductionPage({ searchParams }: { searchParams: Promise<{ view?: string }> }) {
  const sp = await searchParams;
  const byModel = sp.view === "model";
  const [plants, programs] = await Promise.all([getPlantsWithStats(), getProductionPrograms(300)]);

  const active = (plants as any[]).filter((p) => (p.active_programs || []).length);
  const idle = (plants as any[]).filter((p) => !(p.active_programs || []).length);
  const provinces = new Set((plants as any[]).map((p) => p.province).filter(Boolean));
  const modelIds = new Set((programs as any[]).map((r) => r.models?.id).filter(Boolean));

  const byProvince = new Map<string, any[]>();
  for (const p of active) {
    const key = p.province || "ไม่ระบุจังหวัด";
    byProvince.set(key, [...(byProvince.get(key) || []), p]);
  }
  const provinceRows = [...byProvince.entries()].sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0], "th"));

  return <>
    <div className="sfStrip sfBleed">
      <div className="sfStripItem"><b className="sfNum">{modelIds.size.toLocaleString()}</b><span>รุ่นที่ผลิตในไทย</span></div>
      <div className="sfStripItem"><b className="sfNum">{plants.length.toLocaleString()}</b><span>โรงงานในฐานข้อมูล</span></div>
      <div className="sfStripItem"><b className="sfNum">{provinces.size.toLocaleString()}</b><span>จังหวัด</span></div>
      <div className="sfStripNote">นับจากโครงการผลิตที่ TDR ยืนยันโรงงานแล้ว ไม่ใช่ค่าประมาณกำลังการผลิตของทั้งประเทศ</div>
    </div>

    <section className="sfPageHead">
      <div>
        <div className="sfEyebrow">THAILAND PRODUCTION</div>
        <h1>รถที่ผลิตในประเทศไทย</h1>
        <p>โรงงานอยู่จังหวัดไหน ประกอบรุ่นอะไรบ้าง และรุ่นนั้นอยู่ตรงไหนของแคตตาล็อก — ข้อมูลชุดเดียวกับหน้ารถ มองจากฝั่งการผลิต</p>
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
        provinceRows.length ? (
          <div className="sfProvinceList">
            {provinceRows.map(([province, rows]) => (
              <section key={province}>
                <div className="sfProvinceHead">
                  <h2>{province}</h2>
                  <span className="sfNum">{rows.length} โรงงาน</span>
                </div>
                {rows.map((p: any) => {
                  const models = (p.active_programs || []).map((x: any) => x.models).filter(Boolean);
                  const seen = new Set<string>();
                  const unique = models.filter((m: any) => !seen.has(m.id) && seen.add(m.id));
                  return (
                    <div className="sfPlantRow" key={p.id}>
                      <div className="sfPlantHead">
                        <Link href={`/plants/${p.slug}`}>{p.name_th}</Link>
                        {p.capacity_annual ? <em>กำลังผลิตที่ประกาศ {Number(p.capacity_annual).toLocaleString()} คัน/ปี</em> : <em className="sfMissing">ไม่มีข้อมูลกำลังผลิต</em>}
                      </div>
                      {unique.length ? (
                        <div className="sfModelChips">
                          {unique.map((m: any) => (
                            <Link key={m.id} href={`/models/${m.slug}`}>{[m.brands?.name_th, m.name_th].filter(Boolean).join(" ")}</Link>
                          ))}
                        </div>
                      ) : <p className="sfMissing">ยังไม่ระบุรุ่นที่ผลิต</p>}
                    </div>
                  );
                })}
              </section>
            ))}
            {idle.length ? (
              <section>
                <div className="sfProvinceHead">
                  <h2>โรงงานที่ยังไม่ผูกโครงการผลิต</h2>
                  <span className="sfNum">{idle.length} โรงงาน</span>
                </div>
                <div className="sfModelChips">
                  {idle.map((p: any) => <Link key={p.id} href={`/plants/${p.slug}`}>{p.name_th}{p.province ? ` · ${p.province}` : ""}</Link>)}
                </div>
              </section>
            ) : null}
          </div>
        ) : <div className="sfEmpty"><b>ยังไม่มีโรงงานในฐานข้อมูล</b><span>เมื่อบันทึกโรงงานและโครงการผลิตแล้ว รายการจะขึ้นที่นี่</span></div>
      )}
    </div>
  </>;
}
