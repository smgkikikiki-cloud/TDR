/** "BREAKING" marker for a story published in the last 24 hours. The blink is CSS-only,
 *  off under prefers-reduced-motion (the dot stays solid). Never colour alone: it carries a word. */
export function BreakingBadge() {
  return <span className="tdr-news__live" lang="en"><i aria-hidden="true" />BREAKING</span>;
}
