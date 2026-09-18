import Link from "next/link";
import { notFound } from "next/navigation";
import { getCanonicalModelBundle } from "@/lib/canonical-data";
import { loadSpecFieldRegistry } from "@/lib/spec-field-registry";
import { specGroupsForTrim, type CompareSpecField, type FreeCompareTrim } from "@/lib/free-compare";
import { trimLocalId } from "@/lib/trim-editor-state";
import { displayName } from "@/lib/display-name";
import { bodyLabel } from "@/lib/body-labels";
import { groupedNumber } from "@/components/charts/format";

export const dynamic = "force-dynamic";

function baht(value: unknown) {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? `฿${groupedNumber(n)}` : null;
}

/** The trim's own page: everything the catalogue knows about one car.
 *
 *  A model page can only ever summarise its trims -- it has four of them and
 *  a hundred fields each. This is where a reader ends up when they have
 *  decided which one they are actually looking at, and it shows the
 *  comparable-spec ledger in the same groups, with the same headings and the
 *  same formatting, as the comparison does. Fields with no fact are absent
 *  rather than printed as blanks: a hundred rows of "—" is not information.
 */
export default async function TrimDetail({ params }: {
  params: Promise<{ slug: string; trim: string }>;
}) {
  const { slug, trim: trimSegment } = await params;
  const model: any = await getCanonicalModelBundle(slug);
  if (!model) notFound();

  const trims = (model.trims || []) as any[];
  const trim = trims.find((row) => trimLocalId(row.canonical_id || row.id) === trimSegment);
  if (!trim) notFound();

  const fields = loadSpecFieldRegistry(new Date().getFullYear()) as unknown as CompareSpecField[];
  const groups = specGroupsForTrim(trim as FreeCompareTrim, fields);
  const knownFields = groups.reduce((total, group) => total + group.rows.length, 0);

  const brand = displayName(model.brands);
  const modelName = displayName(model);
  const price = baht(trim.price_baht);
  const discontinued = String(trim.status || "current").toLowerCase() === "discontinued";
  const offers = (trim.campaign_quote?.campaign_options || [])
    .filter((offer: any) => offer?.status_as_of === "ACTIVE");

  return <div className="trimPage">
    <nav className="sfCrumbs" aria-label="เส้นทาง">
      <Link href="/models">ฐานข้อมูลรถยนต์</Link>
      <span aria-hidden="true">/</span>
      {model.brands?.slug ? <Link href={`/brands/${model.brands.slug}`}>{brand}</Link> : <span>{brand}</span>}
      <span aria-hidden="true">/</span>
      <Link href={`/models/${slug}`}>{modelName}</Link>
      <span aria-hidden="true">/</span>
      <b>{trim.name}</b>
    </nav>

    <section className="trimHero">
      <div>
        <div className="sfEyebrow">{[brand, modelName].filter(Boolean).join(" ")}</div>
        <h1>{trim.name}</h1>
        <div className="trimHeroTags">
          {trim.powertrain ? <span>{trim.powertrain}</span> : null}
          {model.body_type ? <span>{bodyLabel(model.body_type)}</span> : null}
          {model.segment ? <span>Segment {model.segment}</span> : null}
          {discontinued ? <span className="trimTagMuted">เลิกจำหน่ายแล้ว</span> : null}
        </div>
      </div>
      <div className="trimHeroPrice">
        {price
          ? <><small>ราคาปัจจุบัน</small><strong>{price}</strong></>
          : <><small>ราคา</small><strong className="sfMissing">ยังไม่มีราคาที่ตรวจสอบได้</strong></>}
        <Link className="trimCompareCta" href={`/compare?trims=${encodeURIComponent(trim.canonical_id || trim.id)}`}>
          เทียบรุ่นย่อยนี้ →
        </Link>
      </div>
    </section>

    {offers.length ? (
      <section className="trimOffers">
        <h2>แคมเปญที่มีผลอยู่</h2>
        {offers.map((offer: any) => (
          <div className="trimOffer" key={`${offer.campaign_id}:${offer.option_id}`}>
            <div>
              <b>{offer.option_label || offer.campaign_name}</b>
              <small>{offer.conditions?.text || "ตรวจสอบเงื่อนไขกับผู้จำหน่าย"}{offer.valid_to ? ` · ถึง ${offer.valid_to}` : ""}</small>
            </div>
            <b>{baht(offer.amount_thb) || (baht(offer.discount_thb) ? `ลด ${baht(offer.discount_thb)}` : "มีแคมเปญ")}</b>
          </div>
        ))}
      </section>
    ) : null}

    {groups.length ? (
      <section className="trimSpecs">
        <div className="sfZoneHead">
          <div><div className="sfEyebrow">สเปก</div><h2>ข้อมูลจำเพาะ</h2></div>
          <span>{knownFields} รายการ</span>
        </div>
        {groups.map((group) => (
          <div className="trimSpecGroup" key={group.title}>
            <h3>{group.title}</h3>
            <dl>
              {group.rows.map((row) => (
                <div key={row.key}><dt>{row.label}</dt><dd>{row.value}</dd></div>
              ))}
            </dl>
          </div>
        ))}
      </section>
    ) : (
      <section className="trimSpecs">
        <div className="sfEmpty">
          <b>ยังไม่มีสเปกที่ตรวจสอบแล้วสำหรับรุ่นย่อยนี้</b>
          <span>รุ่นย่อยนี้อยู่ในฐานข้อมูลแล้ว แต่ยังไม่มีค่าสเปกที่ยืนยันที่มาได้</span>
        </div>
      </section>
    )}

    <section className="trimSiblings">
      <div className="sfZoneHead">
        <div><div className="sfEyebrow">รุ่นย่อยอื่น</div><h2>{modelName}</h2></div>
        <span>{trims.length} รุ่นย่อย</span>
      </div>
      <div className="trimSiblingList">
        {trims.map((row: any) => {
          const id = trimLocalId(row.canonical_id || row.id);
          const active = id === trimSegment;
          return (
            <Link key={row.canonical_id || row.id}
                  className={active ? "trimSibling on" : "trimSibling"}
                  href={`/models/${slug}/${encodeURIComponent(id)}`}
                  aria-current={active ? "page" : undefined}>
              <b>{row.name}</b>
              <span>{baht(row.price_baht) || "ไม่ระบุราคา"}</span>
            </Link>
          );
        })}
      </div>
    </section>
  </div>;
}
