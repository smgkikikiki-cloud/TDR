import { useId } from "react";
import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";

/** Label + control + hint + error. The control is passed a matching id and aria wiring through `render`. */
export function Field({ label, hint, error, render }: {
  label: string; hint?: string; error?: string;
  render: (ids: { id: string; "aria-describedby"?: string; "aria-invalid"?: true }) => ReactNode;
}) {
  const id = useId();
  const describedBy = [hint ? `${id}-hint` : "", error ? `${id}-error` : ""].filter(Boolean).join(" ") || undefined;
  return (
    <div className="tdr-field">
      <label className="tdr-field__label" htmlFor={id}>{label}</label>
      {render({ id, "aria-describedby": describedBy, "aria-invalid": error ? true : undefined })}
      {hint ? <span className="tdr-field__hint" id={`${id}-hint`}>{hint}</span> : null}
      {error ? <span className="tdr-field__error" id={`${id}-error`}>! {error}</span> : null}
    </div>
  );
}

export function TextInput(props: InputHTMLAttributes<HTMLInputElement>) {
  const { className, ...rest } = props;
  return <input {...rest} className={["tdr-input", className].filter(Boolean).join(" ")} />;
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  const { className, ...rest } = props;
  return <select {...rest} className={["tdr-select", className].filter(Boolean).join(" ")} />;
}
