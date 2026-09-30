import type { ReactNode } from "react";

/** Page title block: eyebrow, H1, lead, and an optional aside (actions, KPIs). Text comes from the page. */
export function PageHead({ eyebrow, eyebrowLang = "th", title, lead, aside }: {
  eyebrow?: string; eyebrowLang?: "th" | "en"; title: ReactNode; lead?: ReactNode; aside?: ReactNode;
}) {
  return (
    <div className={aside ? "tdr-pagehead" : "tdr-pagehead tdr-pagehead--single"}>
      <div>
        {eyebrow ? <div className="tdr-eyebrow" lang={eyebrowLang}>{eyebrow}</div> : null}
        <h1 className="tdr-pagehead__title">{title}</h1>
        {lead ? <p className="tdr-pagehead__lead">{lead}</p> : null}
      </div>
      {aside ? <div className="tdr-pagehead__aside">{aside}</div> : null}
    </div>
  );
}
