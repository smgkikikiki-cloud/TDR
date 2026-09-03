# TDR Automotive Intelligence — V1.1

V1.1 turns the prototype into one master vehicle record that feeds both a consumer catalog and the Thailand-production intelligence layer.

## What changed

- Consumer-facing vehicle catalog with brand rail and filters.
- Current-model policy: current records are public; discontinued records remain archived in the database.
- Model editor is one panel for core vehicle data, structured powertrains, trims/prices and optional Thailand-production data.
- Brand field accepts an existing brand or creates a new brand category automatically.
- Structured powertrains support ICE / HEV / PHEV / REEV / BEV with dynamic technical fields.
- Multiple trims per model, each linked to one or more powertrain configurations.
- Model price range is derived automatically from current trims.
- Seats and payload capacity, with optional trim-level overrides.
- Model / Trim / Powertrain edit and delete flow.
- Production program remains a separate industry object; local content and MiT stay there, not on the consumer model.
- TDR Report remains a blurred future-paywall preview.
- The public “รุ่นใหม่ / Upcoming” category is removed.

## Upgrade an existing V1 install

1. In Supabase SQL Editor, run:

   `supabase/migration_v11_consumer_catalog.sql`

2. Copy the V1.1 flat patch over the existing project and choose **Replace files in destination**.
3. Keep the existing `.env.local` file.
4. Restart:

```bash
npm run dev
```

5. Open:

- Public catalog: `http://localhost:3000/models`
- Admin: `http://localhost:3000/admin`
- Add model: `http://localhost:3000/admin/models/new`

## Important data behavior

- Do not create a new record for tiny MY/spec changes; edit the current model.
- For a major minor-change or new generation, mark the old model `Discontinued / Archive` and create a new model record.
- Trim equipment and safety detail stays in the trim description rather than becoming hundreds of equipment fields.
- A Thailand Production page appears automatically only when the model has at least one production program.
- CBU-only cars can remain consumer-only records.

## Environment

The existing `.env.local` format from V1 is still used.

Do not commit secret Supabase keys.

## Fresh Supabase project

For a brand-new database, run `supabase/schema_v11_full.sql` instead of running every historical migration manually.
