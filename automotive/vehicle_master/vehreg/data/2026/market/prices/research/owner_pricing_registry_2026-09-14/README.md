# Owner pricing registry — 2026-09-14

This directory preserves the owner-supplied Thailand automotive MSRP and promotion registry and records the canonicalization result.

Rules used for promotion into the canonical price ledger:

- An MSRP is promoted only when the source supplies an exact amount that can be bound to one current canonical `MarketTrim.id`.
- Grouped MSRP ranges are retained as research evidence but are not converted into fabricated per-trim prices.
- Rows explicitly marked estimated or without an official Thai price are retained but not promoted.
- Guard-protected canonical model surfaces are not modified just to make a price fit.
- The source describes prices as current but gives no explicit publication/effective date, so promoted rows use `observed_at = 2026-09-14` and leave `effective_from = null`.
- Promotion/campaign text is preserved verbatim in `records.json`. It is not installed as a live campaign because the source does not provide a reliable start/end window per campaign; doing so would make time-limited promotions appear indefinitely active.
