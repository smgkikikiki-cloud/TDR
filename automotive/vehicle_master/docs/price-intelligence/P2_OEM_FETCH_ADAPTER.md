# P2 — OEM Fetch Adapter

Status: implementation contract for Price Intelligence P2.

## Scope

P2 turns registered `SourceTarget` URLs into immutable `SourceDocument` evidence.
It does **not** extract a price, decide what a number means, create a
`PriceCandidate`, reconcile against `PriceLedger`, or publish serving data.

```text
Source / Target Registry (P1)
        ↓
OfficialOEMAdapter
        ↓
HTTP representation
        ↓
SourceDocument + raw body + target role
        ↓
P3 extractor (later)
```

## Why target role is not added to SourceDocument

`SourceDocument` remains the generic evidence object already used by the
pricefeed engine. P2 returns a `FetchResult` envelope that carries:

- target id;
- target role;
- source id;
- immutable `SourceDocument`;
- raw response bytes/text for the next stage;
- fetch state;
- discovered child targets.

This keeps existing pricefeed serialization and consensus behavior compatible
while preserving the semantic distinction introduced in P1.

## Fetch identity

The HTTP response body is hashed as raw bytes.

```text
document_id = sha256(raw response bytes)
content_hash = same sha256 ref
```

A changed page therefore produces a new document identity. A 200 response with
the same content hash preserves `first_seen_at`. A 304 response creates no new
document.

## Conditional fetch state

`FetchState` stores transport state only:

- target id;
- last content hash;
- first seen timestamp for that representation;
- ETag;
- HTTP Last-Modified.

This state is not canonical price state and must never be interpreted as price
validity or expiry. P0's rule still applies: absence, age, 304, fetch failure or
page disappearance never closes a canonical price.

## Safety / provenance guards

1. A source-specific adapter accepts only its configured source ids.
2. Targets must already be enabled and validated by P1.
3. The JAECOO adapter only accepts the official OMODA & JAECOO Thailand hosts.
4. A redirect that leaves the official host is rejected rather than silently
   inheriting Tier-A authority.
5. The read-only CLI checks robots policy before fetching.
6. Non-HTML responses are rejected by the current OEM HTML adapter.
7. No crawler path imports or writes `PriceLedger`.

## Metadata

P2 extracts only document metadata needed for evidence:

- title;
- publication timestamp when explicitly available;
- modified timestamp when explicitly available;
- visible-text sketch for reprint comparison.

Metadata is read from standard OpenGraph/article meta tags and JSON-LD. P2 does
not infer a publication timestamp from fetch time.

## JAECOO pilot

`official_jaecoo_th` now uses adapter `omoda_jaecoo_th`.

Static P1 targets include:

- JAECOO 5 current model page;
- Thailand promotion index;
- 2 September 2026 JAECOO 5 buyer-guide page.

When the promotion index contains same-site links under `/th/promotion/*`, P2
emits ephemeral `PROMOTION` child targets. They are evidence discovered in the
run, not permanent rows automatically written back to `targets.json`.

This allows a run to discover pages such as the BIG MOTOR SALE 2026 promotion
without turning the static registry into an ever-growing article catalog.

## Read-only CLI

```bash
python tools/pricefetch_targets.py \
  --source official_jaecoo_th \
  --follow-discovery \
  --out /tmp/jaecoo-fetch.json \
  --state-out /tmp/jaecoo-state.json \
  --snapshot-dir /tmp/jaecoo-snapshots
```

The optional output/state/snapshot paths are staging artifacts only. They are
not canonical data and should not be committed as PriceLedger truth.

## Deliberate technology choice

P2 uses Python's standard HTTP/HTML stack. The JAECOO Thailand pages are
server-rendered and do not require a headless browser for evidence discovery.

Do not add Playwright as a universal crawler dependency. If a later OEM is
JavaScript-only, add a source-specific fallback adapter for that OEM.

## P3 contract

P3 consumes `FetchResult.document`, raw content and target role. It may emit
`PriceClaim` evidence, but it still must not write `PriceLedger`. Price-type
classification must be based on what the document actually says; `Tier.A` and a
`CURRENT_MODEL_PAGE` role do not magically turn every number into MSRP.
