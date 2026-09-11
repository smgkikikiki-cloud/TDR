# Pricefeed OEM source expansion — 2026-09

Data-only expansion of `vehreg/data/2026/market/pricefeed/{sources,targets}.json`,
aimed at the models blocking verified canonical `LIST_PRICE` coverage that carry
the most Thai registration volume. No Python, TypeScript, workflow, Supabase
schema, canonical model, PriceLedger, or MarketTrim file was touched.

## How the priority list was built

`/admin/prices/coverage` (`lib/price-coverage-worklist.ts`) ranks canonical
models by 3-month registration volume against a live Supabase project this
research pass had no credentials for. The same underlying registration source
and canonical catalog are available locally, so priority was derived from
that instead: the vehicle-market-master warehouse's own `data/vehreg.sqlite3`
(real DLT registrations through 2026-08, CORE scope) was queried for the
highest-volume brand/model pairs over the last three settled months, then
each was matched to its exact canonical model id by reading the corresponding
`vehreg/data/2026/models/<brand>.json` file — no id was guessed.

## What was added

| | |
|---|---|
| New OEM sources | 13 (Toyota, Isuzu, Honda, Mitsubishi, Nissan, Mazda, BYD, MG, GWM, Changan/Deepal share one domain, GAC Aion, Zeekr, Chery) |
| New targets | 45, all `tier: A`, `adapter: manual` (no automated parser exists for any of these yet — every one is a human-review evidence page, same posture as the pre-existing generic `official_oem` source) |
| Canonical models covered | 38 |
| Every URL | Fetched live and confirmed reachable (HTTP 200) at research time; re-verified a second time after a first pass caught one URL (a Toyota Hilux trim page) going from 200 to a Location-less 301 between the two checks — swapped for a working sibling trim page rather than left broken |
| Every `model_hint` | Cross-checked against the actual `vehreg/data/2026/models/*.json` files, not the model's display name |

## Price text: present vs. absent, reported honestly per target

Roughly two-thirds of the new targets have the price stated directly in the
page's own static HTML (Toyota, Isuzu, Honda, Mitsubishi, Nissan, GWM, GAC
Aion, Chery, and one Omoda page — see caveat below). The rest load fine but
render price client-side, so a plain fetch sees no price text at all:
Mazda's two pages, BYD's four pages, Changan/Deepal's two pages, and Zeekr's
page. Each of those targets says so explicitly in its own `notes` field —
they are registered because they're the correct official page and are still
useful for confirming a model's current existence/spec claims, but none of
them should be treated as `LIST_PRICE` evidence until fetched with a
rendering step, which is outside this PR's scope (no code was changed).

One MG target (`mg_th_zs_ev`) contains a ฿9,000 figure that is a maintenance
package cap, not a vehicle price — flagged directly in its notes so an
automated extractor doesn't mistake it for `LIST_PRICE`.

## Domain-identity findings worth a human decision

- **Isuzu**: `isuzu.co.th` is real but is the corporate/holding site with no
  model or price pages. The actual consumer sales site is `isuzu-tis.com`
  (Tri Petch Isuzu Sales, Isuzu's exclusive Thai distributor) — used as the
  registered source. Flag if the registry is ever expected to require a
  literal `isuzu.co.th` domain match.
- **GAC Aion**: the brand's older domain `aionauto.com` now 301-redirects to
  a relocation notice naming `gacgroup.com` as the new official site.
  Registered `gacgroup.com`.
- **Omoda vs. Chery**: confirmed these are two separate Thailand domains —
  `omodajaecoo.co.th` (Omoda + Jaecoo, already a registered source) and
  `chery-thailand.com` (Chery only). One Omoda C5 target was added reusing
  the existing `official_jaecoo_th` source rather than creating a new one.
- **Deepal**: has no separate Thailand domain; it lives under Changan's own
  site at `changan.co.th/en/deepal/...`. One shared source was registered
  for both brands.

## Models where no usable official Thailand price source could be found

- **`geely.geely_ex2` / `geely.geely_ex5`** — no OEM-run Thailand domain
  exists yet. `global.geely.com` serves a generic overseas page only
  ("contact your local authorized dealership"); the only Thailand-specific
  EX2/EX5 pages live on `thonburineustern.com`, the authorized distributor,
  not Geely itself, which fails this pass's "official OEM site" bar. Media
  coverage says a "Geely Auto Thailand" entity/rebrand is planned for H2
  2026 — worth re-checking then.
- **`gwm.ora_good_cat`** — GWM discontinued the Ora Good Cat in Thailand in
  early 2026 (~20,827 units sold since Oct 2021, per contemporary Thai press
  coverage of the discontinuation); the site now shows "Ora 5" in that slot
  instead. This reads as a canonical-catalog staleness question, not a
  source-registry gap — flagged for the catalog owner, not touched here.
- **`ford.everest` / `ford.ranger_double_cab`** — `ford.co.th` returned
  HTTP 403 on every path tried, including the bare root, which is
  consistent with a bot-block rather than the pages being down. No target
  was registered rather than pointing at an unreachable URL.

## Fetch-layer notes for whoever builds the next adapter

- `mazda.co.th`, `byd.com`, and `changan.co.th` render price client-side; a
  plain HTTP GET (which is what `price_fetch.py` does today) will not see a
  price on those domains regardless of source tier.
- `omodajaecoo.co.th` returned HTTP 403 to at least one automated fetch
  attempt during this research pass but loaded fine (200) with a standard
  browser `User-Agent` and contained real price data (confirmed
  independently: an embedded JSON blob with `"sub_model_name":"OMODA C5 EV
  MAX+","price":"709000"`). If `price_fetch.py`'s own User-Agent
  (`tdr-automotive/price-intelligence-1.0 ...`) also gets blocked there,
  that's a fetch-layer issue worth a separate look — it is not evidence the
  page or the existing JAECOO source is broken.
- `byd.com` intermittently reset connections under rapid repeated requests
  from the same client during this research pass; spacing out requests
  resolved it. Likely simple rate-limiting, not a block.

## Explicitly not done in this pass

- No canonical model file, PriceLedger observation, MarketTrim, Python
  module, TypeScript file, workflow, or Supabase migration was touched.
- No price was written or claimed as verified — every target only says what
  evidence a human reviewer should expect to find on the page.
- No ECO Sticker recommended price was imported as MSRP.
- No trim was fabricated from a page title; trims mentioned in target notes
  (e.g. Hilux cab variants, Triton cab configurations) come from the actual
  page text seen during research, not inferred from the URL.
