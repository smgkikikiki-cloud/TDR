/** A campaign id nothing else can collide with.
 *
 *  The whole canonical trim id goes in, so two models that both sell a
 *  "Premium" cannot end up sharing one promotion -- a grade name is not
 *  unique across a brand, let alone across the catalogue, and two campaigns
 *  landing on one id would merge two different offers into one. Punctuation
 *  is folded to the safe token charset the input pipeline validates ids
 *  against.
 *
 *  Same trim and same start date give the same id, so re-saving a promotion
 *  updates it instead of forking a second one. */
export function campaignIdFor(trimId: string, startDate: string): string {
  const scope = trimId.replace(/[^A-Za-z0-9_.:-]+/g, "-");
  return `${scope}.campaign.${startDate}`;
}
