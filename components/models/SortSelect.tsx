"use client";

import { SORTS, type SortValue } from "@/lib/models/list";

/** Sort control of /models. A GET form, so the URL stays the single source of state (`sort=`; `page` restarts):
 *  the select submits on change, and without JavaScript a submit button appears instead. Hidden inputs carry
 *  every other current param. */
export function SortSelect({ value, params }: { value: SortValue; params: Record<string, string> }) {
  return (
    <form className="tdr-models-sort" action="/models" method="get">
      {Object.entries(params).map(([key, v]) => <input key={key} type="hidden" name={key} value={v} />)}
      <label>
        <span>เรียง</span>
        <select className="tdr-select" name="sort" defaultValue={value} onChange={(event) => event.currentTarget.form?.requestSubmit()}>
          {SORTS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
        </select>
      </label>
      <noscript><button type="submit" className="tdr-btn tdr-btn--secondary">เรียง</button></noscript>
    </form>
  );
}
