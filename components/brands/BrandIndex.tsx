"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Table, TextInput } from "@/components/design";
import { BlockEmpty } from "@/components/models/states";
import { JUMP_LETTERS, filterBrands, groupByInitial, type BrandRow } from "@/lib/brands";
import { formatNumber } from "@/lib/design/format";
import { bahtRangeText } from "@/lib/models/list";

/** The brand index (P05): a filter box, an A–Z jump bar and one table, grouped by initial letter. Brands are text, never
 *  logos. The rows come from the server (brands with at least one current model); filtering is client-side and only
 *  hides rows, so the jump bar always reflects what is on screen. */
export function BrandIndex({ rows }: { rows: BrandRow[] }) {
  const [query, setQuery] = useState("");
  const shown = useMemo(() => filterBrands(rows, query), [rows, query]);
  const groups = useMemo(() => groupByInitial(shown), [shown]);
  const present = new Set(groups.map((g) => g.letter));

  return (
    <>
      <div className="tdr-brands-tools">
        <div className="tdr-brands-filter" role="search">
          <label htmlFor="brand-filter" className="tdr-brands-filter__label">กรองแบรนด์</label>
          <TextInput id="brand-filter" type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="พิมพ์ชื่อแบรนด์" autoComplete="off" />
        </div>
        <span className="tdr-brands-count" role="status">แสดง {formatNumber(shown.length)} จาก {formatNumber(rows.length)} แบรนด์</span>
      </div>

      <nav className="tdr-brands-jump" aria-label="ข้ามไปตามตัวอักษร">
        {JUMP_LETTERS.map((l) => present.has(l)
          ? <a key={l} href={`#brand-${l === "#" ? "other" : l}`}>{l}</a>
          : <span key={l} aria-disabled="true">{l}</span>)}
      </nav>

      {groups.length ? (
        <Table caption="แบรนด์รถในตลาดไทย">
          <thead>
            <tr><th scope="col">แบรนด์</th><th scope="col" className="tdr-num">จำนวนรุ่น</th><th scope="col" className="tdr-num">ช่วงราคา</th><th scope="col"><span className="tdr-brands-sr">ดูรุ่น</span></th></tr>
          </thead>
          {groups.map((g) => (
            <tbody key={g.letter} id={`brand-${g.letter === "#" ? "other" : g.letter}`}>
              <tr className="tdr-brands-letter"><th scope="rowgroup" colSpan={4}>{g.letter}</th></tr>
              {g.rows.map((r) => {
                const range = bahtRangeText(r.min, r.max);
                return (
                  <tr key={r.slug}>
                    <th scope="row"><Link href={`/brands/${r.slug}`}>{r.name}</Link></th>
                    <td className="tdr-num">{formatNumber(r.count)}</td>
                    <td className="tdr-num">{range || <span className="tdr-brands-miss">ยังไม่ประกาศราคา</span>}</td>
                    <td className="tdr-brands-go"><Link href={`/brands/${r.slug}`} aria-label={`ดูรุ่นของ ${r.name}`}>→</Link></td>
                  </tr>
                );
              })}
            </tbody>
          ))}
        </Table>
      ) : (
        <BlockEmpty title="ไม่พบแบรนด์ที่ตรงกับคำค้น" text="ลองพิมพ์ชื่อแบรนด์ให้สั้นลง หรือเว้นคำค้นให้ว่างเพื่อดูทุกแบรนด์" />
      )}
    </>
  );
}
