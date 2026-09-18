/** Same eight hues vehreg's own composition_pie() uses, so a number that
 *  moves between the two tools reads as the same color, not a re-learned one. */
export const CATEGORICAL: readonly string[] = [
  "#2a78d6", "#eb6834", "#1baf7a", "#eda100",
  "#e87ba4", "#008300", "#4a3aa7", "#e34948",
];

export function colorFor(index: number): string {
  return CATEGORICAL[index % CATEGORICAL.length];
}
