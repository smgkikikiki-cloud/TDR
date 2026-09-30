import { formatDelta, type DeltaDirection, type DeltaUnit } from "@/lib/design/format";

const DIRECTION_CLASS: Record<DeltaDirection, string> = {
  up: "tdr-delta--up",
  down: "tdr-delta--down",
  zero: "tdr-delta--na",
  na: "tdr-delta--na",
};

/** A change with its arrow and sign ("▲ +1.2 pp", "▼ −0.8 pp"); "–" when it must not be shown.
 *  Formatting lives in lib/design/format.ts so the arrow and sign cannot be left out. */
export function Delta({ value, unit, base, digits }: { value: number | null | undefined; unit?: DeltaUnit; base?: number | null; digits?: number }) {
  const view = formatDelta(value, { unit, base, digits });
  return <span className={`tdr-delta ${DIRECTION_CLASS[view.direction]}`}>{view.text}</span>;
}
