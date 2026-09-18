/**
 * Where an ECO Sticker record lives on the regulator's own site.
 *
 * The ECO Sticker programme is the evidence behind every trim identity the
 * review bench decides on, and a decision is only reviewable if the person
 * making it can open the record. Kept in one place, and matched by a check,
 * because a reviewer following a link that silently stopped working would
 * believe they had checked something they had not.
 *
 * This is the same URL vehreg/ecosticker_export.py builds for a fact's
 * source_ref, so a spec fact and a review row point a reader at one page.
 */
export const ECO_STICKER_DETAIL_BASE = "https://car.ecosticker.go.th/landing-page/detail";

export function ecoStickerUrl(sourceId: string): string {
  return `${ECO_STICKER_DETAIL_BASE}/${encodeURIComponent(sourceId)}`;
}
