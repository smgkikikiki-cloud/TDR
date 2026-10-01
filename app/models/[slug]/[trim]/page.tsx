import Link from "next/link";
import { notFound } from "next/navigation";
import { Button, Chip, KpiCard, Table } from "@/components/design";
import { SiblingSelect } from "@/components/models/SiblingSelect";
import { SourceBadge } from "@/components/models/SourceBadge";
import { BlockEmpty } from "@/components/models/states";
import { getCanonicalModelBundle } from "@/lib/canonical-data";
import { loadSpecFieldRegistry } from "@/lib/spec-field-registry";
import { type FreeCompareTrim } from "@/lib/free-compare";
import { trimLocalId } from "@/lib/trim-editor-state";
import { displayName } from "@/lib/display-name";
import { bodyLabel } from "@/lib/body-labels";
import { familyOfBody } from "@/lib/body-families";
import { POWERTRAIN_LABEL, bahtRangeText } from "@/lib/models/list";
import { formatThaiDate, keyFacts, trimSpecGroups } from "@/lib/models/trim-specs";

export const dynamic = "force-dynamic";

/** The trim's own page (P04): everything the catalogue knows about one car, in seven groups, each row with its source.
 *  Fields with no fact are absent rather than printed as blanks, and a group with no rows is absent too. Labels and
 *  order come from the canonical spec registry; values and qualifier contexts are the comparison's own. */
export default async function TrimDetail({ params }: { params: Promise<{ slug: string; trim: string }> }) {
  const { slug, trim: trimSegment } = await params;
  const model: any = await getCanonicalModelBundle(slug);
  if (!model) notFound();

  const trims = (model.trims || []) as any[];
  const trim = trims.find((row) => trimLocalId(row.canonical_id || row.id) === trimSegment);
  if (!trim) notFound();

  const fields = loadSpecFieldRegistry(new Date().getFullYear());
  const groups = trimSpecGroups(trim as FreeCompareTrim, fields);
  const facts = keyFacts({ ...(trim as FreeCompareTrim), model_seats: (trim as any).model_seats ?? model.seats }, fields);
  const rowCount = groups.reduce((n, g) => n + g.rows.length, 0);

  const brand = displayName(model.brands);
  const modelName = displayName(model);
  const price = bahtRangeText(trim.price_baht, null);
  const offers = (trim.campaign_quote?.campaign_options || []).filter((offer: any) => offer?.status_as_of === "ACTIVE");
  const ends = offers.map((o: any) => String(o.valid_to || "")).filter(Boolean).sort()[0];
  const body = familyOfBody(model.body_type)?.label || bodyLabel(model.body_type);
  const chips = [
    trim.powertrain ? POWERTRAIN_LABEL[trim.powertrain] || trim.powertrain : null,
    body,
    model.segment && String(model.segment).toUpperCase() !== "UNKNOWN" ? `Segment ${model.segment}` : null,
  ].filter(Boolean) as string[];

  // The source list: every distinct source behind a row shown above, with its links.
  const sources = new Map<string, { urls: Set<string>; rows: number }>();
  for (const group of groups) for (const row of group.rows) {
    const entry = sources.get(row.source.label) || { urls: new Set<string>(), rows: 0 };
    if (row.sourceUrl) entry.urls.add(row.sourceUrl);
    entry.rows += 1;
    sources.set(row.source.label, entry);
  }

  const siblings = trims.map((row) => ({
    href: `/models/${slug}/${encodeURIComponent(trimLocalId(row.canonical_id || row.id))}`,
    label: [row.name, bahtRangeText(row.price_baht, null)].filter(Boolean).join(" · "),
  }));
  const here = `/models/${slug}/${encodeURIComponent(trimSegment)}`;

  return <div className="tdr-wrap tdr-models-detail">
    <nav className="tdr-models-crumbs" aria-label="เส้นทาง">
      <ol>
        <li><Link href="/models">Vehicle Database</Link></li>
        {model.brands?.slug ? <li><Link href={`/brands/${model.brands.slug}`}>{brand}</Link></li> : brand ? <li>{brand}</li> : null}
        <li><Link href={`/models/${slug}`}>{modelName}</Link></li>
        <li aria-current="page">{trim.name}</li>
      </ol>
    </nav>

    <section className="tdr-models-trimhead" aria-labelledby="trim-h1">
      <div>
        <div className="tdr-eyebrow">{[brand, modelName].filter(Boolean).join(" ")}</div>
        <h1 id="trim-h1" className="tdr-models-h1">{trim.name}</h1>
        {chips.length ? <div className="tdr-chips">{chips.map((c) => <Chip key={c}>{c}</Chip>)}</div> : null}
      </div>
      <div className="tdr-models-trimhead__price">
        {price
          ? <><small>ราคาปัจจุบัน</small><strong className="tdr-models-mono">{price}</strong></>
          : <><small>ราคา</small><strong className="tdr-models-miss">ยังไม่มีราคาที่ตรวจสอบได้</strong></>}
        {offers.length ? <span className="tdr-models-promo">ราคาโปรโมชัน{ends ? ` · ถึง ${formatThaiDate(ends) || ends}` : ""}</span> : null}
        <Button variant="secondary" href={`/compare?trims=${encodeURIComponent(trim.canonical_id || trim.id)}`}>เพิ่มเข้าเทียบ</Button>
      </div>
    </section>

    {facts.length ? (
      <div className="tdr-models-facts" role="list" aria-label="ข้อมูลสำคัญ">
        {facts.map((f) => <div role="listitem" key={f.key}><KpiCard label={f.label} value={f.value} /></div>)}
      </div>
    ) : null}

    <section className="tdr-models-blk" aria-labelledby="trim-specs">
      <div className="tdr-models-sechead">
        <div><div className="tdr-eyebrow">สเปก</div><h2 id="trim-specs">ข้อมูลจำเพาะ</h2></div>
        {rowCount ? <span className="tdr-models-mono">{rowCount} รายการ</span> : null}
      </div>
      {groups.length ? groups.map((group) => (
        <div className="tdr-models-specgroup" key={group.title}>
          <h3>{group.title}</h3>
          <Table caption={group.title}>
            <tbody>
              {group.rows.map((row) => (
                <tr key={row.key}>
                  <th scope="row">{row.label}</th>
                  <td>{row.value}</td>
                  <td className="tdr-models-srccell"><SourceBadge label={row.source.label} known={row.source.known} observedAt={row.observedAt} /></td>
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
      )) : (
        <BlockEmpty title="ยังไม่มีสเปกที่ตรวจสอบแล้วสำหรับรุ่นย่อยนี้" text="รุ่นย่อยนี้อยู่ในฐานข้อมูลแล้ว แต่ยังไม่มีค่าสเปกที่ยืนยันที่มาได้" />
      )}
    </section>

    {siblings.length > 1 ? (
      <section className="tdr-models-blk" aria-labelledby="trim-siblings">
        <div className="tdr-models-sechead">
          <div><div className="tdr-eyebrow">รุ่นย่อยอื่น</div><h2 id="trim-siblings">{modelName}</h2></div>
          <span className="tdr-models-mono">{siblings.length} รุ่นย่อย</span>
        </div>
        <SiblingSelect siblings={siblings} currentHref={here} />
      </section>
    ) : null}

    <section className="tdr-models-blk" aria-labelledby="trim-sources">
      <div className="tdr-models-sechead"><div><h2 id="trim-sources">ที่มา</h2></div></div>
      <ul className="tdr-models-sources">
        {price ? <li><b>ราคา</b> Price Ledger ของ TDR (ราคาขายปลีกที่ประกาศ)</li> : null}
        {[...sources.entries()].map(([label, { urls, rows }]) => (
          <li key={label}>
            <b>{label}</b>
            <span className="tdr-models-muted">{rows} รายการ</span>
            {[...urls].map((u, i) => {
              let host = u;
              try { host = new URL(u).hostname.replace(/^www\./, ""); } catch { /* keep the raw text */ }
              return <a key={u} href={u} target="_blank" rel="noreferrer">{host} ↗{urls.size > 1 ? ` (${i + 1})` : ""}</a>;
            })}
          </li>
        ))}
        {!price && !sources.size ? <li className="tdr-models-muted">ยังไม่มีข้อมูลที่มาสำหรับรุ่นย่อยนี้</li> : null}
      </ul>
    </section>
  </div>;
}
