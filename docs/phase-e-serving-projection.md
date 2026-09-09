# Phase E — Canonical → serving projection

The canonical Vehicle Master remains authoritative. Supabase `models`, `model_powertrains`, `trims`, and `trim_powertrains` are serving projections plus TDR-only editorial fields.

## Grain ownership

- `models` projects canonical Model plus safe single-current-Generation facts used by the model page.
- `model_powertrains` projects canonical Variant rows. It must not be populated from MarketTrim identity.
- `trims` projects canonical MarketTrim rows.
- `trim_powertrains` links each projected MarketTrim to the projected canonical Variant named by the trim's `variant` field.
- `trims.price_baht` is a serving cache only and may contain only the current canonical `LIST_PRICE` selected by `PriceLedger.current_list_price()`. ECO Sticker, estimated, dealer, campaign, introductory, and finance prices must never be promoted here.

## Crosswalk rule

A legacy TDR model is eligible for projection only when `canonical_object_map` contains a `verified` mapping from that exact `models.id` UUID to a canonical `model` ID. Names, slugs and fuzzy matching are not authority.

The publisher refuses to project an unverified target and refuses to guess child identity. Canonical Variant and MarketTrim IDs are deterministic and are stored on serving rows.

## Editorial preservation

Projection must not overwrite TDR-only presentation/editorial fields such as `slug`, `image_url`, `consumer_description`, `featured`, or `market_position` unless a later explicit ownership decision moves them into Vehicle Master.

## Mixed production routes

Model-level `production_type` / `production_country` are projected only when all non-empty canonical Variants agree. Mixed CBU/CKD or mixed-origin models project `null` at model grain; route-specific truth remains on Variant/MarketTrim-level canonical facts until a dedicated serving representation exists.

## Reconciliation

For a verified model, the publisher upserts children by stable canonical IDs and deletes only stale children that were previously marked as Vehicle-Master projections. It never deletes unowned/manual legacy children silently.

A projection hash makes exact replays idempotent. The apply step is service-role only and must be transactional.
