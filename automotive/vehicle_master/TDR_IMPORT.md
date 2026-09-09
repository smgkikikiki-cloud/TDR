# Vehicle Master import into TDR

Phase B consolidation import.

Source repository: `smgkikikiki-cloud/vehicle-market-master`
Source commit: `8cd44655fb2ad4b52f2cb523d6aa757cd2ea1b82`

This directory is an intact import of the canonical Python vehicle engine and its committed data/tests/tooling. It is intentionally nested first so the import does not rewrite working engine behavior while TDR's Next.js application continues to build unchanged.

Canonical domains imported here include vehicle identity, Variant vs MarketTrim separation, PriceLedger, comparable specs, ECO ingestion, DLT matching/warehouse, provenance, and DLT Trim Ledger.

This commit does **not** import registration rows into Supabase and does **not** make the legacy TDR `trims.price_baht` authoritative. Serving projections and entitlement changes are later consolidation phases.
