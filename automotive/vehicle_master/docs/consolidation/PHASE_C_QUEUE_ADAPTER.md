# Phase C queue adapter

`vehreg.canonical_queue` is the boundary between the private Supabase shadow queue and the file-backed canonical writer.

A queue row is executable only when it is already `queued` with an explicit verified canonical model ID. The adapter does not resolve names, slugs, generations, Variants or MarketTrims.

Legacy model-level fields are deliberately narrowed before they reach canonical state. Safe model/generation facts such as Thai display name, body type, segment and seats can be carried when the canonical model has exactly one generation. Legacy generation labels, production fields, market position, launch metadata and other semantically different fields are ignored until their canonical owner/evidence path is explicit.

Any legacy child powertrain or trim rows block processing until those child identities have verified crosswalks. This is the guard that prevents a legacy TDR trim from silently becoming a canonical `Variant` or `MarketTrim`.

After canonical apply, `revision_payload()` exposes the exact immutable revision that an operational DB worker should mirror to `canonical_write_revisions` and `canonical_publish_outbox`. Serving tables remain untouched in Phase C.
