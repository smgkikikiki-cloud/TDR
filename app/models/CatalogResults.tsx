"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import styles from "./catalog.module.css";

type CatalogModel = {
  id: string;
  slug: string;
  brand: string;
  name: string;
  imageUrl: string | null;
  bodyLabel: string | null;
  powertrainLabel: string | null;
  seats: number | string | null;
  productionType: string | null;
  verifiedCurrent: boolean;
  priceLabel: string | null;
};

function compareHref(ids: string[]) {
  const params = new URLSearchParams();
  ids.forEach((id) => params.append("models", id));
  return `/compare?${params.toString()}`;
}

function ModelCard({ model, selected, selectionFull, onToggle }: { model: CatalogModel; selected: boolean; selectionFull: boolean; onToggle: () => void }) {
  const disabled = selectionFull && !selected;
  return <article className={styles.card}>
    <Link href={`/models/${model.slug}`} className={styles.visualLink}>
      {model.imageUrl ? <img src={model.imageUrl} alt={model.name} /> : <div className={styles.placeholder}><small>{model.brand.toUpperCase()}</small><b>{model.name}</b></div>}
      {!model.verifiedCurrent ? <span className={styles.statusFlag}>อยู่ระหว่างตรวจสอบ</span> : null}
    </Link>
    <div className={styles.cardBody}>
      <div className={styles.brand}>{model.brand}</div>
      <Link href={`/models/${model.slug}`} className={styles.titleLink}><h3>{model.name}</h3></Link>
      {model.priceLabel ? <div className={styles.price}>{model.priceLabel}</div> : <div className={styles.priceMissing}>{model.verifiedCurrent ? "ยังไม่ประกาศราคา" : "ยังไม่แสดงราคาปัจจุบัน"}</div>}
      <div className={styles.meta}>
        {model.bodyLabel ? <span>{model.bodyLabel}</span> : null}
        {model.powertrainLabel ? <span>{model.powertrainLabel}</span> : null}
        {model.seats ? <span>{model.seats} ที่นั่ง</span> : null}
        {model.productionType ? <span>{model.productionType === "CBU" ? "นำเข้า (CBU)" : model.productionType === "CKD" || model.productionType === "SKD" ? "ประกอบไทย" : model.productionType}</span> : null}
      </div>
      {!model.verifiedCurrent ? <p className={styles.statusNote}>ข้อมูลสถานะการจำหน่ายอยู่ระหว่างตรวจสอบ จึงยังไม่แสดงราคาเป็นข้อมูลปัจจุบัน</p> : null}
      <div className={styles.actions}>
        <Link className={styles.detailButton} href={`/models/${model.slug}`}>ดูรายละเอียด</Link>
        <button type="button" aria-pressed={selected} disabled={disabled} className={`${styles.compareButton} ${selected ? styles.compareButtonSelected : ""}`} onClick={onToggle}>
          {selected ? "✓ เลือกแล้ว" : disabled ? "เต็ม 4 รุ่น" : "+ เทียบ"}
        </button>
      </div>
    </div>
  </article>;
}

export function CatalogResults({ models, marketHref = "/market" }: { models: CatalogModel[]; marketHref?: string }) {
  const [selected, setSelected] = useState<string[]>([]);
  const byId = useMemo(() => new Map(models.map((model) => [model.id, model])), [models]);
  function toggle(id: string) {
    setSelected((current) => current.includes(id) ? current.filter((item) => item !== id) : current.length >= 4 ? current : [...current, id]);
  }
  const first = models.slice(0, 8);
  const rest = models.slice(8);
  const selectionFull = selected.length >= 4;
  const renderCard = (model: CatalogModel) => <ModelCard key={model.id} model={model} selected={selected.includes(model.id)} selectionFull={selectionFull} onToggle={() => toggle(model.id)} />;
  return <>
    <div className={styles.grid}>{first.map(renderCard)}</div>
    {models.length ? <section className={styles.bridge}><div className={styles.bridgeCopy}><div className={styles.bridgeIcon}>▥</div><div><b>อยากรู้ว่ารุ่นไหนนำตลาดในกลุ่มนี้?</b><p>ดูยอดจดทะเบียน ส่วนแบ่งตลาด และแนวโน้มแบบเจาะลึกด้วย Market Intelligence</p></div></div><Link href={marketHref}>เปิด Market Intelligence →</Link></section> : null}
    {rest.length ? <div className={styles.grid}>{rest.map(renderCard)}</div> : null}
    {selected.length ? <aside className={styles.tray} aria-label="รถที่เลือกไว้เปรียบเทียบ"><div className={styles.trayInner}>
      <div className={styles.trayCount}>{selected.length} / 4 รุ่นที่เลือก</div>
      <div className={styles.trayModels}>{selected.map((id) => { const model = byId.get(id); if (!model) return null; return <div className={styles.trayModel} key={id}>{model.imageUrl ? <img className={styles.trayThumb} src={model.imageUrl} alt="" /> : null}<span>{model.brand} {model.name}</span><button type="button" aria-label={`เอา ${model.name} ออกจากรายการ`} onClick={() => toggle(id)}>×</button></div>; })}{selected.length < 4 ? <span className={styles.trayAdd}>+ เพิ่มรถ</span> : null}</div>
      <span className={styles.compareHint}>{selected.length < 2 ? "เลือกอย่างน้อย 2 รุ่น" : "เลือก Trim จริงในขั้นถัดไป"}</span>
      {selected.length >= 2 ? <Link className={styles.trayCta} href={compareHref(selected)}>ไปหน้าเปรียบเทียบ →</Link> : <span className={`${styles.trayCta} ${styles.trayCtaDisabled}`} aria-disabled="true">ไปหน้าเปรียบเทียบ →</span>}
    </div></aside> : null}
  </>;
}
