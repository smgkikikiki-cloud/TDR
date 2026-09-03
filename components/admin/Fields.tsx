import { ReactNode } from "react";

export function Field({ label, name, defaultValue, type = "text", required = false, placeholder }: { label: string; name: string; defaultValue?: string | number | null; type?: string; required?: boolean; placeholder?: string }) {
  return <label className="adminField"><span>{label}</span><input name={name} type={type} defaultValue={defaultValue ?? ""} required={required} placeholder={placeholder}/></label>;
}
export function TextArea({ label, name, defaultValue }: { label: string; name: string; defaultValue?: string | null }) {
  return <label className="adminField adminFieldWide"><span>{label}</span><textarea name={name} rows={5} defaultValue={defaultValue ?? ""}/></label>;
}
export function Select({ label, name, defaultValue, children, required = false }: { label: string; name: string; defaultValue?: string | number | null; children: ReactNode; required?: boolean }) {
  return <label className="adminField"><span>{label}</span><select name={name} defaultValue={defaultValue ?? ""} required={required}>{children}</select></label>;
}
export function CheckGroup({ label, name, values, options }: { label: string; name: string; values?: string[] | null; options: { value: string; label: string; hint?: string }[] }) {
  const selected = new Set(values ?? []);
  return <fieldset className="adminCheckGroup adminFieldWide"><legend>{label}</legend><div className="adminCheckGrid">{options.map(o => <label className="adminCheckItem" key={o.value}><input type="checkbox" name={name} value={o.value} defaultChecked={selected.has(o.value)}/><span><b>{o.label}</b>{o.hint ? <small>{o.hint}</small> : null}</span></label>)}</div></fieldset>;
}
