# Official vehicle media ingestion

Official imagery is a Vehicle Master attachment, not a second vehicle catalogue.
The crawler reads canonical Generation identity, discovers assets only from
configured OEM-owned domains, scores candidates, downloads stable copies, and
publishes approved metadata to Supabase.

## Architecture boundary

Vehicle identity, retail MarketTrim identity, prices, specs, campaigns and
lifecycle remain owned by the Git-backed Vehicle Master and reach production
through the immutable `release_enriched` -> `canonical_*_projection` ->
`current_*` release path. Official media does **not** define or mutate any of
those facts.

Media is a serving attachment sidecar. Its public binaries live in Supabase
Storage and its serving metadata lives in `vehicle_media_assets` /
`vehicle_media_bindings`. The application joins that sidecar onto the active
canonical release by stable Generation ID.

That split has one mandatory safety rule: an approved media row may be published
only when its `vehicle_id` exists in `current_vehicle_generations`, i.e. in the
currently active immutable canonical release. `scripts/publish-official-media.ts`
checks this before the first Storage or metadata write and fails closed if any
approved target is absent. A stale branch, typoed ID, renamed generation or
legacy-only identity therefore cannot create a new canonical-looking media
attachment in production.

The reverse dependency is forbidden: media rows never feed canonical identity,
lifecycle or retail reconciliation, and an OEM image discovery result is never
evidence that a model/trim is current. Current/withdrawn/orderable decisions
must come from the canonical product/reconciliation path. If a later release
removes a Generation, its old sidecar media may remain stored for audit/history,
but the `current_*` application join no longer exposes it as a current vehicle.

Source adapters, exact source-page hints and any curated direct-asset hints are
Git-reviewed code/data. Scratch crawl manifests and downloaded cache files stay
gitignored; production metadata is a projection of an approved run rather than
a second vehicle master.

## Identity and inheritance

The default `visual_key` is the canonical Generation ID. All MarketTrims under
that generation inherit the same media set. A later trim-specific binding can
point at another visual key when a wheel package, body kit, or exterior treatment
materially changes the appearance.

Canonical slots are intentionally small:

- `hero`
- `front_3q`
- `rear_3q`
- `side`
- `dashboard`
- `interior`
- `cargo`
- `detail`

## Source adapters

The first adapters cover Toyota, Honda, BYD, MG, and GWM. Every adapter declares
an explicit official-domain allowlist. Page discovery will not follow links
outside that allowlist. Image CDN URLs may be downloaded when they were discovered
inside an allowed OEM page; provenance always records the source page and original
image URL.

## Candidate scoring

The deterministic score records its reasons. Current signals are official-domain
provenance, model name, generation code, Thai-market source, source dimensions,
filename match, and page hero metadata. Thumbnails, logos/icons, and accessory
imagery are penalized.

- score >= 85: `approved`
- score 60..84: `review`
- score < 60: rejected before download

## Run a pilot

From `automotive/vehicle_master`:

```bash
python scripts/ingest_official_media.py \
  --year 2026 \
  --brands toyota honda byd mg gwm \
  --limit 30
```

The run writes scratch output under `integration_data/official_media/` and binary
files under `data/media/cache/`. Both are gitignored. Binary paths are
content-addressed with SHA-256.

## Publish to the website

From repository root, with `SUPABASE_SECRET_KEY` (or the legacy service-role key)
and Supabase URL configured:

```bash
npm run media:publish -- --year 2026
```

The publisher first verifies every approved Generation against
`current_vehicle_generations`, then uploads the content-addressed binaries to the
public `vehicle-media` bucket, upserts `vehicle_media_assets`, and records the
default Generation binding in `vehicle_media_bindings`.

Public RLS only exposes rows whose metadata status is `approved`. Canonical model
bundles expose `hero_image_url` and `media[]`; review rows therefore remain out of
normal product queries until approved.
