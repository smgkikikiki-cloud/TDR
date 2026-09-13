# Owner directory canonical application

This directory is the provenance bundle for the owner-provided 321-nameplate trim directory imported on 2026-09-13.

Canonical application result:
- 321 / 321 source nameplates matched to a canonical model.
- 885 source-backed MarketTrim rows promoted into canonical model JSON.
- 2 existing MarketTrim rows gained owner-directory source references.
- 153 source trim rows were intentionally left unresolved: 152 because an exact powertrain could not be determined from the supplied row/trim text, and 1 because it is a concept/future-production row.
- 57 promoted MarketTrim rows disagree with the pre-existing analytical Variant powertrain set. The import preserves those Variant rows unchanged for separate canonical review.

Validation completed successfully with `python -m vehreg market validate` before the generated canonical files were committed.
