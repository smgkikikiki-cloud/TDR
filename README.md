# TDR Automotive Intelligence

TDR is the single product and repository for Thailand automotive market data,
industry context and paid analytics.

## Data boundary

- `automotive/` is the canonical vehicle engine: brand/model/generation,
  MarketTrim, exact powertrain, specifications, fitment, source evidence,
  Price Ledger and campaigns.
- Supabase public projections serve the current immutable vehicle release.
- TDR editorial UUIDs link images, descriptions, news and production programs;
  they do not redefine vehicle facts.
- registrations remain a separate input. Missing registration data never
  removes or creates a MarketTrim.
- catalog, specifications, list prices and campaign conditions are public;
  registration/sales visualisations and analytic tools require entitlement.

## Write once / publish everywhere

Edit or approve vehicle facts in `automotive/`, run the tests, and merge the
change. GitHub Actions builds one versioned release and calls the
service-role-only `publish_vehicle_release` RPC. The RPC validates row counts,
writes all projections, and flips the active release atomically. Rollback is a
pointer change to a prior release.

```bash
cd automotive
python -m pytest -q
python -m tdr_bridge.release \
  --inventory integration_data/tdr_2026-09-09.json \
  --overrides integration_data/crosswalk_overrides.json \
  --out integration_data/release_2026.json
```

See `docs/consolidation/masterplan.md` and `automotive/tdr_bridge/README.md`.
