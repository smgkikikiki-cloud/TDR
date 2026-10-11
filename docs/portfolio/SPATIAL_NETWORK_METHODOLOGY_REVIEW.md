# Dealer Geography + Competitive Network Watch — methodology review v0.1

**Date:** 2026-10-11 · **Status:** PROPOSED METHODOLOGY, NOT AUTHORISED AS DATA/PRODUCTION CONTRACT.  
**Owner-locked UX inherited:** one map-first Spatial workspace with local `Dealer Geography` and `Competitive Network Watch` modes, one main thematic map layer, one selected inspector, optional modeled catchment, no provincial cross-region data leaks. Two distinct products within the same workspace. Competitive Pressure V1 first; Geography follows V1.5, verified Network Watch V2. Shared underlying evidence work may start earlier.

## S1. What is actually observed? Five separate entities

1. **Site:** a physical location with geometry/address, geocoding source/precision, and physical location identity.
2. **Franchise/authorization:** an effective-dated brand × site relationship, with Sales/Service modes independently tracked.
3. **Operator:** legal/trading entity operating one or more sites, independently recorded when verified.
4. **Source Observation:** timestamped OEM dealer locator, verified announcement, legal/official evidence, site confirmation etc; freshness/source rights apply. A *single observation does not prove ongoing completeness*.
5. **Network Event:** a versioned adjudicated change in Site, Franchise or Operator state, each with `detected_at`, `effective_at?`, affected entity and evidence set.

Never equate Site = Franchise = Operator. A building can remain open when one brand franchise exits; a franchise can shift operator with no site closure; one site may serve multiple brands or offer only after-sales service.

**Evidence status lattice** (suggested; owner must approve):
`OBSERVED_CANDIDATE` → `REVIEW_REQUIRED` → `VERIFIED` → `PUBLISHED`, or `REJECTED`; distinct `INSUFFICIENT_EVIDENCE` and `SOURCE_STALE`.
Absence from a dealer locator is **a missing record/negative observation**, not an automatically confirmed closure. Source correction, temporary web outage and brand rename are distinct possibilities.

## S2. Dealer Master measurement contract

Compute only source-confirmed facts at specified as-of/source coverage:

- `VERIFIED_SITE_COUNT(area,t)`: count distinct physical `site_id` meeting verified status at date t. Site count is NOT equal to franchised dealer representation.
- `VERIFIED_SALES_FRANCHISE_COUNT(brand,area,t)`: count distinct (site, brand, Sales entitlement) active at t. A service-only workshop contributes 0 sales franchises.
- `VERIFIED_SERVICE_FRANCHISE_COUNT(...)`: count independently; may overlap Sales in same site.
- `OBSERVED_OPERATOR_COUNT(area,t)`: distinct verified operator IDs with explicit source coverage.
- `COVERAGE`: distinct source-observed verified universe vs explicitly defined monitored target (if target known). **Never advertise national percentage coverage merely because 90% of scraped URLs look complete**.

Network change metrics use the same entity key, effective-date logic and source version:
`net_change = verified_events_added - verified_events_exited` for a specific **relationship type** (e.g. Sales franchises), and separately show all opening/exit counts; if relationship type changes, do not call a pure Sales exit a physical site shutdown. Discovery backfill of preexisting but previously unobserved site is `NEWLY_DISCOVERED`, not `OPENED`.

## S3. Registration geography is distinct from dealership geography

Ice panel province registrations represent registration place, not sale by branch, vehicle owner residence or origin of consumer trip. Geography mode may show:
- mapped **registered units / period / province / brand or model_group** using actual available Ice panel grain and versioned reviewed identity mapping;
- verified site counts and links as separate adjacent contextual values;
- descriptive *density/context* only if numerator and denominator and time bases are explicitly described.

Forbidden:
- `province registrations / dealer count = average dealer sales`;
- `dealer enters/exits → province share will move X percentage points`;
- allocation from regional/province group totals to particular site without buyer, dealer transaction or confirmed mapping;
- implying a modeled road catchment is the true geographic origin of dealership buyers.

**MAUP / ecological fallacy risk:** change the polygon boundaries or aggregation level and the apparent rankings and rates may change. A provincial hot spot must not be reframed as the performance of a branch located there. Spatial group comparisons must disclose selected geographic unit, area mapping revision and denominator. General methodology background: https://pmc.ncbi.nlm.nih.gov/articles/PMC7151983/.

## S4. Spatial computation: measurable, modeled, hypothetical

**Level 0 verified facts:** coordinates, location quality, brand links, Sales/Service, events, geographic admin units.
**Level 1 physical accessibility model:** great-circle distance (label `STRAIGHT_LINE_DISTANCE`), optional driving route duration and isochrones (label `NETWORK_MODELED_TIME` and route provider/assumptions). Never use Euclidean km as claimed real driving minutes.
**Level 2 spatial co-presence / exposure:** count distinct approved substitute-brand network sites within a documented route catchment relative to an organization-verified My Branch. This is **potential exposure**, not customer switching, deal conversion, sales or franchise economics.
**Level 3 causal impact / predicted change:** NOT approved. Requires separate hypothesis, natural experiment or verified store-level response, time confounders and sensitivity tests before quantification.

A modeled site catchment can extend across provincial borders; region authorization still applies to registered volumes and derived stats. Neutral nearby out-of-region site directory facts are allowed under owner-locked UX, but no outside-region registration numbers, shares or re-identifiable aggregates in payloads, PDFs, inspector, cluster tooltips, exports or caches.

**Source license note:** provider locator/Places/maps usage and retention rights must be checked; public place visibility does not imply unlimited storage/republication or reverse engineered scraping authorization. Country administrative geography and geocode precision must be versioned.

## S5. Event-based network-change methodology

```text
source snapshot (observed_at, locator/source coverage)
      ↓
identity-aware diff of Site / Brand Franchise / Operator relationships
      ↓
candidate event + difference record
      ↓
evidence verification: official notice, repeated controlled observations,
  manual validation where applicable; source may be incomplete
      ↓
verified event (type, detected_at, effective_at?, evidence, reviewer)
      ↓
network analytics + region/branch contextual relevance + customer release
```

Event types (identity-aware): `SITE_OPENED`, `SITE_CLOSED`, `SITE_RELOCATED`, `SALES_FRANCHISE_ADDED`, `SALES_FRANCHISE_EXITED`, `SERVICE_FRANCHISE_ADDED`, `SERVICE_FRANCHISE_EXITED`, `OPERATOR_CHANGED` plus `SOURCE_RECORD_CORRECTION` and `NEWLY_DISCOVERED` (not commercial events).

**Detection time != actual effective time**. If only the detection interval is known (present at day 1, absent at day 7), express as `effective_window` if approved, not `effective_at=day7` fabricated. Events from one site correction may represent multiple raw source diffs but must be deduped to one reviewed event identity.

For customer Network Watch, surface only `VERIFIED/PUBLISHED` events with relevant approved dealer relation, substitute models and scope. Potential suggested actions should be explicitly hypotheses (“review local outreach positioning”), not promises of gained/lost sales.

## S6. Minimal typed output envelopes (proposed)

```ts
type DealerSiteEvidence = {
  siteId: string;
  coordinates: { lat: number; lon: number; quality: "ROOFTOP" | "STREET" | "CENTROID" | "UNKNOWN" };
  placeAsOf: string;
  verifiedStatus: "VERIFIED" | "UNKNOWN" | "STALE";
  sourceRefs: string[];
};
type DealerRelation = {
  siteId: string;
  brandId: string;
  mode: "SALES" | "SERVICE";
  operatorId?: string; // only if verified
  validFrom?: string; validTo?: string;
  observationAsOf: string;
  evidenceStatus: "VERIFIED" | "CANDIDATE" | "CONFLICT";
};
type DealerNetworkEvent = {
  eventId: string;
  entityKind: "SITE" | "FRANCHISE" | "OPERATOR";
  eventType: string;
  detectedAt: string;
  effectiveAt: string | null;
  verifiedAt: string | null;
  status: "CANDIDATE" | "VERIFIED" | "REJECTED";
  sourceRefs: string[];
  siteIds: string[];
};
type SpatialContext = {
  regionCode: string;
  authorizedProvinceCodes: string[];
  primarySiteId?: string;
  sourceVersion: string;
  registrationBasis: "PROVINCE_REGISTERED" | "UNAVAILABLE";
  coverageStatus: string;
};
```

Keep shared Site and Event evidences globally authoritative within TDR-admin network domain; organization `My Branch` **references** verified global sites with a verified claim. An organization may not create facts about competitor branches in a separate shadow database.

## S7. Adversarial tests and publication stops

| ID | Case | Required conclusion |
| --- | --- | --- |
| SP-01 | Dealer locator record disappears once | `CANDIDATE/UNKNOWN`; no `SITE_CLOSED` publication |
| SP-02 | Franchise ends, workshop continues as service-only | Sales exit, **not** site closure |
| SP-03 | Operator name changes at same site, same brand | Operator change/review, no fabricated new dealer site |
| SP-04 | Site shifts 800m, source URL also changes | candidate relocation; do not double-count old+new |
| SP-05 | New-to-source preexisting site | `NEWLY_DISCOVERED`, not historical opening |
| SP-06 | Same physical site sells two brands | one site, two Sales relations |
| SP-07 | Newly seen network change lacks effective date | `detectedAt` shown; actual effective date remains unknown |
| SP-08 | Service-only location | Sales count=0, Service count=1 |
| SP-09 | Nearby rival across user region border | neutral location visible; registration from adjacent unauthorized province denied everywhere |
| SP-10 | Province registrations rise but dealer roster unchanged | show registrations increase; no dealer sales assertion |
| SP-11 | Routing service unavailable | show straight-line context if permissible, never substitute invented driving minutes |
| SP-12 | Catchment polygon crosses border | geometry allowed; unauthorized registration metrics masked before client response |
| SP-13 | source changes completeness, target denominator unknown | source coverage status exposed; no misleading 100% verified nationwide |
| SP-14 | monthly geography map after province boundary version changes | label version, no silent historical district reallocation |
| SP-15 | venue coordinate = province centroid, not rooftop | represent geocode precision; no exact-drive-time claim |
| SP-16 | event affects nearby competitor franchise | potential local competitive relevance, NOT proven branch sales loss |
| SP-17 | organization claims competitor site as 'own branch' | reject pending validation; member cannot bypass via API |
| SP-18 | source revision retracts event | prior immutable event revision remains auditable, current customer state updated without silent overwrite |

## S8. Gate sequence

- **S0 Data inventory (read-only):** sources by brand, area, legal permissions, Site/Franchise/Operator keyability, timestamp quality, Ice regional availability, actual authorized supabase/project mapping.
- **S1 Synthetic model:** site/relationship/event schema, status transitions and spatial authorization negative tests; verify 5 brands/one area as a *suggested* manageable pilot, not automatically national.
- **S2 Dealer Geography readiness:** authoritative verified listing, as-of/coverage, site facts + selected authorized province context, one map-first UX surface. No simulated regional vehicle sales.
- **S3 Network Watch readiness:** versioned before/after source collections; event review admin, dedup, effective-time unknown support, publish gate and region/branch relevance.
- **S4 Later economic validation:** only if actual suitable demand/trade data appear may quantitative sales capture impact be studied; no release promise implied.

No production integrations, change-detection bot, paid maps APIs, market cutover, company access permission edits or migrations are authorized by this document.
