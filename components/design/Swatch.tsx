export type SwatchFill =
  | "map-1" | "map-2" | "map-3" | "map-4" | "map-5"
  | "div-1" | "div-2" | "div-3" | "div-4" | "div-5"
  | "cat-1" | "cat-2" | "cat-3" | "cat-4" | "cat-5";

/** Colour swatch. It always carries the --border-strong outline, so pale map and diverging fills
 *  (under 3:1 against the page) stay visible in light and dark. */
export function Swatch({ fill, square }: { fill: SwatchFill; square?: boolean }) {
  return <i className={`tdr-swatch${square ? " tdr-swatch--square" : ""} tdr-fill-${fill}`} aria-hidden="true" />;
}

/** Legend row(s): a swatch and a text label each, so colour is never the only carrier. */
export function Legend({ items, square }: { items: { fill: SwatchFill; label: string }[]; square?: boolean }) {
  return (
    <ul className="tdr-legend">
      {items.map((item) => <li key={item.fill}><Swatch fill={item.fill} square={square} />{item.label}</li>)}
    </ul>
  );
}
