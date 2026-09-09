# P1 — Source / Target Registry

Status: implementation contract for Price Intelligence P1.

## Why two concepts

A **source** answers who is speaking. A **target** answers which page/feed we are watching and what role that document plays.

Do not collapse them.

The same manufacturer can publish a current model page, a promotion index, a launch release and an old blog article. They are all first-party evidence, but their temporal meaning is different. Conversely, a target role must never upgrade a Tier-B media outlet into Tier-A authority.

## Source identity

The existing `vehreg.pricefeed.Source` remains the authority registry used by pricefeed consensus. P1 adds richer `SourceProfile` metadata without breaking the current loader or WordPress harvester.

New automation must use specific source ids such as:

- `official_jaecoo_th`
- later `official_toyota_th`, `official_honda_th`, etc.

`official_oem` remains only as a legacy provenance id for historical rows. It has no active P1 fetch targets and must not be used by new automated evidence.

## Target identity

A `SourceTarget` has:

- stable target id
- source id
- HTTPS URL
- role
- optional adapter override
- optional polling override
- enabled flag
- optional canonical `model_hint`

`model_hint` is discovery context only. It never bypasses canonical model/trim matching.

Supported P1 roles:

- `CURRENT_MODEL_PAGE`
- `PRICE_LIST`
- `PROMOTION_INDEX`
- `PROMOTION`
- `PRESS_RELEASE`
- `LAUNCH_PAGE`
- `BLOG`
- `DISCOVERY_FEED`

## Discovery roots vs documents

The registry is not a catalog of every article ever published.

Stable roots belong in `targets.json`. For example, the OMODA & JAECOO Thailand promotion index is a `PROMOTION_INDEX`. P2 may discover promotion detail links from that page and save them as immutable `SourceDocument` evidence without permanently adding every discovered detail page to the static registry.

A specific detail page may still be pinned as a target when it is useful for a controlled pilot or requires dedicated monitoring.

## Pilot configuration

P1 registers `official_jaecoo_th` as the first specific Tier-A OEM source and three JAECOO 5 roots/evidence pages:

1. current JAECOO 5 EV model page;
2. Thailand promotion index;
3. the 2 September 2026 JAECOO 5 buyer-guide page used by the pilot.

Headlightmag and AutoLife Thailand remain Tier-B sources and receive explicit `DISCOVERY_FEED` targets using their existing WordPress adapters.

## Invariants

1. Source authority and target role are separate.
2. New automation uses specific OEM identities, never generic `official_oem`.
3. Historical provenance is not rewritten merely to migrate source configuration.
4. Targets must use absolute HTTPS URLs.
5. Unknown sources, duplicate target ids and unknown roles fail validation.
6. Per-target adapter/poll settings may override source defaults.
7. Disabled targets are retained in configuration but excluded from active fetch sets.
8. A model hint never changes source tier and never bypasses trim matching.
9. Loading the P1 registry performs no network access and writes no price data.
10. P1 changes no price lifecycle semantics frozen in P0.

## P2 contract

P2 adapters consume `SourceTargetRegistry` and return fetched documents. They must not write `PriceLedger`. A target's role travels with the resulting evidence so later reconciliation can distinguish current pages from promotions, launch material and historical editorial pages.
