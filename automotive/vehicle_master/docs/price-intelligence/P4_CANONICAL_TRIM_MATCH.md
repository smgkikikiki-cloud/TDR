# Price Intelligence P4 — Canonical MarketTrim matching

Status: implementation candidate

P4 connects P3 raw retail-grade claims to the canonical vehicle catalog without
moving any price into PriceLedger.

```text
P3 PriceClaim
  brand_raw / model_raw / trim_raw
        ↓
P4 retail-grade normalization
        ↓
existing canonical match_trim resolver
        ↓
EXACT | AMBIGUOUS | UNMAPPED
        ↓
P5 reconciler later
```

## Boundary

P4 resolves **MarketTrim only**. It does not resolve registration `Variant`, the
DLT Trim Ledger, campaign identity, or price truth. A successful trim match says
which retail grade the source is talking about; it says nothing about whether
the price should become canonical.

P4 never writes:

- PriceLedger;
- catalog identities or aliases;
- Supabase serving rows;
- registration facts.

## States

### EXACT

Exactly one canonical MarketTrim is resolved. `method` explains why:

- `EXACT_NAME` — normalized raw grade equals the canonical MarketTrim name;
- `EXACT_ALIAS` — normalized raw grade equals a canonical alias;
- `PARTIAL_GRADE` — the existing conservative subset rule yields one winner.

`EXACT` means unique canonical resolution, not that every character in the raw
source string was identical.

### AMBIGUOUS

The existing resolver returns multiple candidate MarketTrims. P4 reports all of
them and never breaks the tie. Methods are `AMBIGUOUS_EXACT` and
`AMBIGUOUS_PARTIAL`.

### UNMAPPED

No safe canonical identity exists. Diagnostics distinguish `NO_MODEL`,
`NO_MARKET_TRIMS`, `EMPTY_GRADE`, and `NO_GRADE_MATCH`.

## Retail punctuation rule

P4 found a real JAECOO 5 collision: generic catalog folding removes punctuation,
so `MAX+` becomes `MAX`. The J5 catalog simultaneously contains:

- `Long Range Max`, alias `Max`;
- `MAX+`, alias `MAX PLUS`.

Globally changing catalog/DLT normalization just to solve retail punctuation
would expand the blast radius unnecessarily. P4 therefore performs one narrow
surface normalization before invoking the existing resolver:

```text
MAX+ -> MAX PLUS
```

The canonical names/aliases are normalized the same way for diagnostics. Thus:

```text
MAX+      -> MAX PLUS -> J5 MAX+        EXACT
MAX PLUS  -> MAX PLUS -> J5 MAX+        EXACT
MAX       -> MAX      -> two candidates AMBIGUOUS
```

A genuinely underspecified source remains ambiguous.

## JAECOO 5 pilot expectations

The P3 grades resolve as follows:

```text
LONG RANGE DYNAMIC -> jaecoo.jaecoo_5_ev.j5.trim.long_range_dynamic_bev
LONG RANGE MAX     -> jaecoo.jaecoo_5_ev.j5.trim.long_range_max_bev
MAX+               -> jaecoo.jaecoo_5_ev.j5.trim.max_plus_bev
ULTRA              -> jaecoo.jaecoo_5_ev.j5.trim.ultra_bev
```

Both LIST and CAMPAIGN claims for one raw grade resolve to the same MarketTrim.
Price type belongs to a price stream, not vehicle identity.

## CLI

P2/P3 behavior remains opt-in. Canonical matching requires extraction:

```bash
python tools/pricefetch_targets.py \
  --source official_jaecoo_th \
  --follow-discovery \
  --extract-prices \
  --match-trims \
  --out /tmp/jaecoo-price-evidence.json
```

Each extracted claim receives a `match` block with state, canonical model/trim,
candidates, method, reason, and normalized raw grade. The batch also reports
counts for EXACT / AMBIGUOUS / UNMAPPED.

## Frozen P4 invariants

1. MarketTrim is the only canonical identity P4 may return.
2. A model hint never becomes a canonical trim binding.
3. Price type never changes retail trim identity.
4. Ambiguous ties are never broken automatically.
5. Unmapped claims remain evidence/review work; they do not create trims.
6. Retail punctuation normalization is narrow and explicit; generic DLT/catalog
   normalization is not changed by P4.
7. P4 never writes PriceLedger or serving data.
8. P5 must consume P4 disposition rather than silently rematching raw strings
   with weaker semantics.
