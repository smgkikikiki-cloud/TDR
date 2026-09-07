import { Children, isValidElement, ReactNode } from "react";

export function Field({ label, name, defaultValue, type = "text", required = false, placeholder }: { label: string; name: string; defaultValue?: string | number | null; type?: string; required?: boolean; placeholder?: string }) {
  return <label className="adminField"><span>{label}</span><input name={name} type={type} defaultValue={defaultValue ?? ""} required={required} placeholder={placeholder}/></label>;
}
export function TextArea({ label, name, defaultValue }: { label: string; name: string; defaultValue?: string | null }) {
  return <label className="adminField adminFieldWide"><span>{label}</span><textarea name={name} rows={5} defaultValue={defaultValue ?? ""}/></label>;
}
/** A value the record already holds but the option list no longer offers — a
 *  retired option, or one written straight into the database — has to stay
 *  selectable. Without it the field renders blank and the next save silently
 *  clears whatever was there. The model editors keep their own Select, so this
 *  lives on its own and every one of them calls it. */
export function legacyOption(defaultValue: unknown, children: ReactNode) {
  const current = defaultValue == null ? "" : String(defaultValue);
  if (!current) return null;
  const offered = new Set<string>();
  for (const child of Children.toArray(children)) {
    if (!isValidElement(child)) continue;
    const props = child.props as { value?: unknown; children?: unknown };
    offered.add(String(props.value ?? props.children ?? ""));
  }
  if (offered.has(current)) return null;
  return <option value={current}>{current} (ค่าเดิมในฐานข้อมูล)</option>;
}

export function Select({ label, name, defaultValue, children, required = false }: { label: string; name: string; defaultValue?: string | number | null; children: ReactNode; required?: boolean }) {
  return <label className="adminField"><span>{label}</span><select name={name} defaultValue={defaultValue ?? ""} required={required}>{legacyOption(defaultValue, children)}{children}</select></label>;
}
export function CheckGroup({ label, name, values, options }: { label: string; name: string; values?: string[] | null; options: { value: string; label: string; hint?: string }[] }) {
  const selected = new Set(values ?? []);
  return <fieldset className="adminCheckGroup adminFieldWide"><legend>{label}</legend><div className="adminCheckGrid">{options.map(o => <label className="adminCheckItem" key={o.value}><input type="checkbox" name={name} value={o.value} defaultChecked={selected.has(o.value)}/><span><b>{o.label}</b>{o.hint ? <small>{o.hint}</small> : null}</span></label>)}</div></fieldset>;
}
