import type { ReactNode } from "react";

export type FlagKind = "estimate" | "new" | "source" | "soon" | "delayed";
const FLAG_CLASS: Record<FlagKind, string> = {
  estimate: "tdr-flag--estimate",
  new: "tdr-flag--new",
  source: "tdr-flag--source",
  soon: "tdr-flag--soon",
  delayed: "tdr-flag--delayed",
};

/** Data flag. The wording comes from the page (e.g. "ประมาณการ · ครอบคลุม 92%"); this component adds none. */
export function Flag({ kind, children }: { kind: FlagKind; children: ReactNode }) {
  return <span className={`tdr-flag ${FLAG_CLASS[kind]}`}>{children}</span>;
}
