# Unresolved owner-directory rows

The source-level canonical promotion intentionally leaves 153 source trim rows unresolved.

- `AMBIGUOUS_POWERTRAIN`: 152 rows. The supplied model-level powertrain description contains multiple possible canonical powertrains and the individual trim string does not identify exactly one of them.
- `NON_MARKET_FUTURE_OR_CONCEPT`: 1 row. Honda e:N2 `e:N2 Concept / Future Production Trim` is retained only as research evidence and is not promoted as a MarketTrim.

Repository guard enforcement additionally restores 22 model surfaces exactly to `main` because existing tests intentionally forbid retail trims there or require an exact canonical trim set. After those guards, 830 source-backed MarketTrim rows remain promoted across 298 changed models.

Separately, 57 promoted MarketTrim rows have a source-backed exact powertrain that is not present in the model generation's existing analytical Variant powertrain set. Those Variant rows are deliberately left unchanged for a separate canonical repair pass.
