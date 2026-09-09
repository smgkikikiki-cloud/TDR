# Canonical vehicle publishing

Vehicle identity, generations, MarketTrim, powertrain, specifications, tyres,
wheels, batteries, list prices and campaigns are authored under `automotive/`.
TDR Supabase UUIDs remain editorial/industry links only.

One edit flows through one release:

1. edit canonical files or approve through the bundled Vehicle Workbench;
2. run the full Python test suite;
3. build one immutable release with `python -m tdr_bridge.release`;
4. publish through the service-role-only `publish_vehicle_release` RPC;
5. all public catalog views flip to the new release in one transaction.

The TDR repository must define `SUPABASE_URL` and
`SUPABASE_SERVICE_ROLE_KEY` as Actions secrets. A missing secret fails the
release job visibly; it never reports success without publishing.

Registration rows never create MarketTrim records. They are a separate paid
analytics input joined through the reviewed canonical-to-TDR crosswalk.
