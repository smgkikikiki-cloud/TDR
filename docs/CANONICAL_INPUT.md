# Canonical vehicle input

Vehicle-market facts have one write path. Registration analytics remains a
separate input because most DLT rows do not identify a retail MarketTrim.

## Flow

1. An editor submits one schema-v1 JSON batch at `/admin/vehicle-input`.
2. `canonical_input_batches` deduplicates it by stable `batch_id` and checksum.
3. The scheduled worker claims the batch and stages every command against a
   complete copy of the canonical data tree.
4. Only an all-valid batch is copied into Vehicle Master. It creates immutable
   command revisions, outbox records and one batch marker.
5. The worker runs the complete engine tests and release build, then opens one
   reviewable PR in TDR.
6. Merging that PR triggers the atomic Supabase vehicle release. Every public
   catalogue/trim/price/spec/fitment projection flips together.
7. The release job marks included batches `PUBLISHED` with the release ID.

An edit uses the same flow and a new batch ID. Facts that have ledger semantics
(price and comparable specs) append a new observation rather than overwriting
history. Exact retries are idempotent; reusing a batch ID for different content
is rejected. The server records one stable `submitted_at` for the batch, so a
worker retry cannot turn an identical submission into a different revision.

The queue and worker are server-only and fail closed without the repository
Actions secrets `SUPABASE_URL` and `SUPABASE_SECRET_KEY` (or legacy
`SUPABASE_SERVICE_ROLE_KEY`). Both workflows probe the configured credential
against the server-only queue before doing any build or write; scheduled intake
pauses without a red run when the credential is absent or invalid.
