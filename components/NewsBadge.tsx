/** Red blinking "breaking news" marker. The blink is CSS-only and is switched off
 *  for readers who ask for reduced motion (the dot stays solid red). */
export function BreakingBadge() {
  return <span className="newsBreaking"><i aria-hidden="true" />BREAKING</span>;
}
