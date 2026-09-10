# TDR Automotive Intelligence

TDR is the single active repository for Thailand vehicle market data, industry context, and paid analytics.

## Canonical data boundary

- `automotive/vehicle_master/` owns Brand, Model, Generation, Variant, MarketTrim, exact powertrain, specifications, fitment, source evidence, Price Ledger, campaigns, ECO ingestion, and DLT resolution.
- Supabase serves an immutable, versioned projection of that canonical data to the Next.js application.
- Registration facts remain separate from MarketTrim. Missing registrations never hide a vehicle or create a trim.
- Catalog, specs, list prices, campaigns, and campaign conditions are public. Registration/sales visualizations and analytical tools require a TDR entitlement.
- TDR-only editorial and industry fields may link to a canonical vehicle through reviewed IDs, but cannot redefine market facts.

## Write once, publish everywhere

Vehicle facts are changed only inside `automotive/vehicle_master/`. On merge to `main`, the release workflow validates the engine, builds one deterministic release, publishes every projection in one transaction, then atomically moves the active-release pointer. All public catalog routes read those projections.

```bash
cd automotive/vehicle_master
python -m pytest -q
python -m tdr_bridge.release \
  --inventory integration_data/tdr_2026-09-09.json \
  --overrides integration_data/crosswalk_overrides.json \
  --revision "$(git rev-parse HEAD)" \
  --as-of "$(date -u +%F)" \
  --out /tmp/vehicle-release.json
python -m tdr_bridge.publish /tmp/vehicle-release.json
```

Publishing requires `SUPABASE_URL` (or `NEXT_PUBLIC_SUPABASE_URL`) plus
`SUPABASE_SECRET_KEY`; the legacy `SUPABASE_SERVICE_ROLE_KEY` remains a fallback.
The URL and key must belong to the same Supabase project. No secret belongs in git
or browser code.

## Repository status

`smgkikikiki-cloud/vehicle-market-master` is superseded. New vehicle data, fixes, workflows, issues, and agent instructions must target this TDR repository and the nested canonical engine path above.

See [`automotive/vehicle_master/docs/consolidation/REPOSITORY_CUTOVER.md`](automotive/vehicle_master/docs/consolidation/REPOSITORY_CUTOVER.md) for cutover, rollback, and retirement gates.
