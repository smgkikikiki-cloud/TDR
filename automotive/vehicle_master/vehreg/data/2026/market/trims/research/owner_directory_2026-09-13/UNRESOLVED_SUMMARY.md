# Unresolved owner-directory rows

The canonical promotion intentionally leaves 153 source trim rows unresolved.

- `AMBIGUOUS_POWERTRAIN`: 152 rows. The supplied model-level powertrain description contains multiple possible canonical powertrains and the individual trim string does not identify exactly one of them.
- `NON_MARKET_FUTURE_OR_CONCEPT`: 1 row. Honda e:N2 `e:N2 Concept / Future Production Trim` is retained only as research evidence and is not promoted as a MarketTrim.

Separately, 57 promoted MarketTrim rows have a source-backed exact powertrain that is not present in the model generation's existing analytical Variant powertrain set. Those Variant rows are deliberately left unchanged for a separate canonical repair pass.
