"use client";

import { useRouter } from "next/navigation";
import { Field, Select } from "@/components/design";

export type Sibling = { href: string; label: string };

/** Switch between the other trims of the same model (P04). A select for JavaScript readers; the same links follow as
 *  a plain list inside <noscript>, so the switcher works without it. */
export function SiblingSelect({ siblings, currentHref }: { siblings: Sibling[]; currentHref: string }) {
  const router = useRouter();
  return (
    <>
      <Field label="เลือกรุ่นย่อยอื่นของรุ่นนี้" render={(ids) => (
        <Select {...ids} value={currentHref} onChange={(event) => router.push(event.target.value)}>
          {siblings.map((s) => <option key={s.href} value={s.href}>{s.label}</option>)}
        </Select>
      )} />
      <noscript>
        <ul>{siblings.map((s) => <li key={s.href}><a href={s.href}>{s.label}</a></li>)}</ul>
      </noscript>
    </>
  );
}
