# Official vehicle media ingestion

Official imagery is a Vehicle Master attachment, not a second vehicle catalogue.
The crawler reads canonical Generation identity, discovers assets only from
configured OEM-owned domains, scores candidates, downloads stable copies, and
publishes approved metadata to Supabase.

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

The publisher uploads the content-addressed binaries to the public
`vehicle-media` bucket, upserts `vehicle_media_assets`, and records the default
Generation binding in `vehicle_media_bindings`.

Public RLS only exposes rows whose metadata status is `approved`. Canonical model
bundles expose `hero_image_url` and `media[]`; review rows therefore remain out of
normal product queries until approved.
