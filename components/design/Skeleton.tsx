/** Loading placeholder with the block's final dimensions (no spinners, PAGES §0). Decorative: hidden from assistive tech;
 *  give the surrounding region aria-busy while it shows. */
export function Skeleton({ height = 24, width = "100%", radius }: { height?: number; width?: number | string; radius?: "pill" }) {
  return <span className={radius === "pill" ? "tdr-skeleton tdr-skeleton--pill" : "tdr-skeleton"} aria-hidden="true" style={{ height, width }} />;
}
