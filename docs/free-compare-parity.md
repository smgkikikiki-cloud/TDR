# Free compare parity boundary

The public `/compare` surface is a buyer-facing projection of the active canonical Vehicle Master release.

- exact grain: `MarketTrim`
- canonical read sources: `current_market_trims` + `current_vehicle_models`
- no independent specification table or editable compare data
- current list price stays separate from campaign offers
- empty rows are hidden rather than guessed
- `Show differences only` compares selected trim values, including known vs missing
- tyre/wheel remain in canonical storage but are intentionally excluded from the public product scope

The legacy analyst compare remains a behavioral/data-quality reference; public compare intentionally omits evidence internals and deep review controls.
