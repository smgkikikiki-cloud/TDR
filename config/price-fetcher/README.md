# OEM price-fetcher playbooks

One JSON file per brand in `playbooks/<brand>.json`, validated by `validatePlaybook` (`lib/price-refresh/playbook.ts`) on every
run; an invalid file is reported and not used. **There are no real playbooks yet**: the first five (Toyota, Isuzu, Honda, BYD, MG)
are PR 3 and must be written from real captured pages. Nothing here claims any brand is verified.

```jsonc
{
  "schema_version": 1,
  "brand": "acme",
  "playbook_version": "2026-10-13.1",
  "status": "DRAFT",                       // DRAFT = dry runs only. VERIFIED needs "evidence": [{url, captured_on, note}]
  "sources": [
    {
      "id": "acme_price_list",
      "target_id": "acme_th_price_list",   // optional: the registry target it came from
      "url": "https://...",
      "role": "PRICE_LIST",                // MODEL_PAGE | PRICE_LIST | PRICE_LIST_PDF | BROCHURE | ANNOUNCEMENT (last two = evidence only)
      "models": ["acme.roadster"],         // canonical vehicle_models ids this page speaks for
      "priority": 1,                       // 1 = most trusted
      "fetch": { "kind": "HTML" },         // HTML | BROWSER {wait_for_text?} | PDF (pdftotext)
      "authority": { "prices": true, "existence": true },
      "extraction": { "mode": "ROW_REGEX", "row_regex": "^(?<name>[^|]+?)\\s*\\|\\s*(?<price>[\\d,]{7,})", "section": { "start": "...", "end": "..." } },
      "price_semantics": { "msrp_markers": [], "promotion_markers": [], "mixed_msrp": "AMBIGUOUS", "require_list_marker": false },
      "as_of": { "pattern": "มีผล (?<date>[\\d/]+)", "stale_after_days": 60, "required": true },
      "lineup_complete": false,            // default false. true needs lineup_verification and a VERIFIED playbook
      "lineup_verification": { "verified_on": "2026-10-13", "verified_by": "...", "evidence_ref": "..." },
      "required": true,                    // a required source that cannot be read stops the model
      "fallback_of": "other_source_id"     // fetched only if that primary is unusable; never completes the lineup
    }
  ]
}
```

Rules the engine enforces regardless of what a file says
- Completeness is declared, dated (valid 90 days) and signed; a successful fetch or a partial read never implies it. Absence of a trim
  can only become a "discontinue" card from a source that is declared complete, was read now, and across days that were all really read.
- Promotions / campaign prices are `CAMPAIGN_PRICE` observations; they can never become a `LIST_PRICE`.
- MSRP next to another plain price on one grade is ambiguous (no price) unless the playbook sets `mixed_msrp: "MSRP_IS_LIST"`.
- Two sources that disagree on a grade's price: no price for that grade, reported as a conflict.
- Stale (as-of date too old), empty, or layout-changed (`section` marker missing) sources supply nothing.
- Brochures and announcements are never fetched into the price path.
