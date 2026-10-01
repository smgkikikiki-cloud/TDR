import Link from "next/link";
import { CompareToggle } from "@/components/models/CompareTray";
import { bodyLabel } from "@/lib/body-labels";
import { familyOfBody } from "@/lib/body-families";
import { displayName } from "@/lib/display-name";
import { POWERTRAIN_LABEL, bahtRangeText, pictureCredit, type ModelListRow } from "@/lib/models/list";

export type ModelCardRow = ModelListRow & {
  image_url?: string | null;
  image_source_url?: string | null;
  image_source_type?: string | null;
};

/** One model in a grid (P02, P03 related models, P06 brand pages). The picture appears only with a credit
 *  (official-site asset with a source page); otherwise the brand and model name sit on the placeholder.
 *  Every value shown is a stored one: a missing price or spec says so in words, never a dash. */
export function ModelCard({ r, trimCount, compare = true }: { r: ModelCardRow; trimCount?: number | null; compare?: boolean }) {
  const brand = displayName(r.brands);
  const name = displayName(r);
  const picture = pictureCredit(r);
  const body = familyOfBody(r.body_type)?.label || bodyLabel(r.body_type);
  const powertrains = (r.powertrains || []).map((p) => POWERTRAIN_LABEL[p] || p).join(" · ");
  const price = bahtRangeText(r.retail_price_min, r.retail_price_max);
  const local = r.production_type === "CKD" || r.production_type === "SKD";
  const ev = (r.powertrains || []).includes("BEV");
  const meta = [powertrains, r.seats ? `${r.seats} ที่นั่ง` : ""].filter(Boolean).join(" · ");
  return (
    <article className="tdr-models-card">
      <div className="tdr-models-card__img">
        {picture ? <img src={picture.src} alt={`${brand} ${name}`} loading="lazy" /> : <span>{brand}<br /><b>{name}</b></span>}
        {picture ? <small>ภาพ: {picture.host}</small> : null}
      </div>
      <div className="tdr-models-card__body">
        <div className="tdr-eyebrow">{brand}</div>
        <h3><Link className="tdr-models-card__link" href={`/models/${r.slug}`}>{name}</Link></h3>
        <p className="tdr-models-card__meta">
          {body ? <>{body} · </> : null}
          {meta || <span className="tdr-models-miss">{body ? "สเปกพื้นฐานยังไม่ครบ" : "ยังไม่มีข้อมูลสเปกพื้นฐาน"}</span>}
        </p>
        <div className="tdr-models-card__foot">
          {price ? <span className="tdr-models-price">{price}</span> : <span className="tdr-models-miss">ยังไม่ประกาศราคา</span>}
          {trimCount ? <span className="tdr-models-card__trims">{trimCount.toLocaleString("en-US")} รุ่นย่อย</span> : null}
        </div>
        {ev || local || r.production_type === "CBU" ? (
          <div className="tdr-models-card__tags">
            {ev ? <span className="tdr-models-tag tdr-models-tag--ev">EV</span> : null}
            {local ? <span className="tdr-models-tag tdr-models-tag--local">ประกอบในไทย</span> : r.production_type === "CBU" ? <span className="tdr-models-tag">นำเข้า CBU</span> : null}
          </div>
        ) : null}
      </div>
      {compare ? <CompareToggle model={{ id: r.id, name, brand }} /> : null}
    </article>
  );
}
