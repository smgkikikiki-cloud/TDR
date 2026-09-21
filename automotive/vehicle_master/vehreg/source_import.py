"""Patch MarketTrim rows from a source export: resolve identity, then write columns.

The MarketTrim row is the spec source of truth. It is what the release
publishes and what compare reads; ``SpecLedger`` publishes zero facts, so a
source that lands there lands nowhere. Ingestion therefore writes trim
columns, and this module decides which ones.

What a source may do to a field it carries:

  blank in the source        the key is omitted, so the stored value stands
  value held is None         filled
  both values, equal         omitted -- nothing to write
  both values, differ        the source wins only where it is authoritative
                             for that field; otherwise it reports a conflict
                             and writes nothing

Identity is resolved deterministically or not at all. A source id already
recorded on a trim resolves to that trim (a re-approval is the same car). An
exact name match inside one model+generation+powertrain resolves to that
trim. A grade that does not exist yet, under a model and generation that do,
is created. Anything else -- two equally good matches, an unknown model --
is an exception for a person, and is never guessed at.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import unicodedata
from typing import Any, Iterable

#: One canonical_input_batches row accepts at most 500 commands; a few
#: hundred also keeps a single commit reviewable after the fact.
DEFAULT_BATCH_SIZE = 400

PATCHED = "PATCHED"
CREATED = "CREATED"
UNCHANGED = "UNCHANGED"
EXCEPTION = "EXCEPTION"

#: Registry key emitted by a source normalizer -> MarketTrim column.
#: Only fields the trim row actually holds appear here. Anything else the
#: source knows (CO2, consumption, range, battery chemistry) has no column
#: to live in and is deliberately dropped rather than written somewhere it
#: would not be served from.
FIELD_TO_COLUMN: dict[str, str] = {
    "vehicle.seats": "seats",
    "vehicle.length_mm": "length_mm",
    "vehicle.width_mm": "width_mm",
    "vehicle.height_mm": "height_mm",
    "engine.displacement_cc": "engine_cc",
    "fitment.tyre_front": "tire_front",
    "fitment.tyre_rear": "tire_rear",
}

#: Which columns a source kind may overwrite when the stored value differs.
#: ECO Sticker is a homologation filing, so its measured dimensions and
#: seat count outrank whatever was typed in earlier; its gear wording is too
#: coarse to overrule a transmission somebody set by hand, so it is absent.
AUTHORITATIVE_COLUMNS: dict[str, frozenset[str]] = {
    "ECO": frozenset({"seats", "length_mm", "width_mm", "height_mm",
                      "engine_cc", "tire_front", "tire_rear"}),
    "OEM": frozenset(FIELD_TO_COLUMN.values()),
    "ADMIN": frozenset(FIELD_TO_COLUMN.values()),
}

_INT_COLUMNS = frozenset({"seats", "length_mm", "width_mm", "height_mm", "engine_cc"})


#: Wording that carries no identity. A source writes "HYBRID G 2WD CAR"
#: where the catalogue writes "2.5 HYBRID G"; the trailing "CAR" is the
#: export's own boilerplate, and a parenthetical in a catalogue name is a
#: note to a reader ("(Retractable Fastback Manual)"), not part of the grade.
_NOISE_TOKENS = frozenset({"car", "cars"})
_PARENTHETICAL = re.compile(r"\([^)]*\)")
#: One powertrain, spelled five ways across sources.
_TOKEN_ALIASES = {
    "ehev": "hev", "e": "", "hybrid": "hev", "phev": "phev", "bev": "bev",
}


def label_tokens(value: object) -> frozenset[str]:
    """The identity-bearing tokens of a grade name.

    Set equality, not similarity: "e:HEV SPADA PREMIUM LINE" and "Spada
    Premium Line e:HEV" are the same car written in two orders, and this
    says so without ever scoring how close two different names are.
    """
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    text = _PARENTHETICAL.sub(" ", text)
    text = text.replace("e:hev", "hev").replace("e-hev", "hev")
    raw = re.split(r"[^\w]+", text, flags=re.UNICODE)
    tokens = set()
    for token in raw:
        token = _TOKEN_ALIASES.get(token, token)
        if token and token not in _NOISE_TOKENS:
            tokens.add(token)
    return frozenset(tokens)


def normalized_label(value: object) -> str:
    """Case/spacing/punctuation-folded comparison key -- equality, not a score."""
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True)
class SourceRow:
    """One normalized record from a source export, ready to resolve."""

    source_id: str
    source_kind: str
    model_id: str
    generation_id: str
    powertrain: str
    trim_name: str
    values: dict[str, Any]


@dataclass(frozen=True)
class ExistingTrim:
    canonical_id: str
    model_id: str
    generation_id: str
    name: str
    powertrain: str
    columns: dict[str, Any] = field(default_factory=dict)
    source_ids: tuple[str, ...] = ()


@dataclass
class RowOutcome:
    row: SourceRow
    status: str
    trim_id: str | None = None
    patch: dict[str, Any] = field(default_factory=dict)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""


def _coerce(column: str, value: Any) -> Any:
    if value is None:
        return None
    if column in _INT_COLUMNS:
        try:
            number = int(round(float(value)))
        except (TypeError, ValueError):
            return None
        return number if number > 0 else None
    text = str(value).strip()
    return text or None


def _same(held: Any, incoming: Any) -> bool:
    if isinstance(held, (int, float)) and isinstance(incoming, (int, float)):
        return float(held) == float(incoming)
    return str(held).strip().lower() == str(incoming).strip().lower()


def column_patch(
    row: SourceRow,
    held: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Columns to write, and the differences this source may not overwrite."""
    authoritative = AUTHORITATIVE_COLUMNS.get(row.source_kind.upper(), frozenset())
    patch: dict[str, Any] = {}
    conflicts: list[dict[str, Any]] = []
    for key, column in FIELD_TO_COLUMN.items():
        incoming = _coerce(column, row.values.get(key))
        if incoming is None:
            continue
        current = held.get(column)
        if current is None or (isinstance(current, str) and not current.strip()):
            patch[column] = incoming
        elif _same(current, incoming):
            continue
        elif column in authoritative:
            patch[column] = incoming
        else:
            conflicts.append({"column": column, "held": current, "incoming": incoming})
    return patch, conflicts


def resolve_rows(
    rows: Iterable[SourceRow],
    trims: Iterable[ExistingTrim],
    *,
    known_generations: Iterable[str] = (),
) -> list[RowOutcome]:
    """Resolve each row to a trim and work out what it would change."""
    by_scope: dict[tuple[str, str], list[ExistingTrim]] = {}
    by_source_id: dict[str, ExistingTrim] = {}
    for trim in trims:
        by_scope.setdefault((trim.model_id, trim.powertrain.upper()), []).append(trim)
        for source_id in trim.source_ids:
            by_source_id[source_id.lower()] = trim
    generations = set(known_generations)

    rows = list(rows)
    # Which existing trims this run matches at all. A leftover source row is
    # only ambiguous while some existing grade is still unspoken for: once
    # every grade the catalogue holds has been claimed by some other row, a
    # name that matched none of them is a grade the catalogue does not have.
    claimed: set[str] = set()
    for row in rows:
        hit = by_source_id.get(row.source_id.lower())
        if hit is None:
            label = label_tokens(row.trim_name)
            for candidate in by_scope.get((row.model_id, row.powertrain.upper()), []):
                if label_tokens(candidate.name) == label:
                    hit = candidate
                    break
        if hit is not None:
            claimed.add(hit.canonical_id)

    outcomes: list[RowOutcome] = []
    for row in rows:
        siblings: list[ExistingTrim] = []
        target = by_source_id.get(row.source_id.lower())
        if target is None:
            # Scoped by model and powertrain rather than by generation: a
            # patch does not need to know which generation the grade sits in,
            # and requiring it would reject rows the catalogue can place
            # unambiguously. Creating one still does -- see below.
            scope = (row.model_id, row.powertrain.upper())
            label = label_tokens(row.trim_name)
            siblings = by_scope.get(scope, [])
            exact = [t for t in siblings if label_tokens(t.name) == label]
            if len(exact) == 1:
                target = exact[0]
            elif len(exact) > 1:
                outcomes.append(RowOutcome(
                    row=row, status=EXCEPTION,
                    reason=f"{len(exact)} trims share this exact name under one model"))
                continue

        if target is None:
            if not row.trim_name.strip():
                outcomes.append(RowOutcome(
                    row=row, status=EXCEPTION, reason="source carries no grade name"))
            elif row.generation_id not in generations:
                outcomes.append(RowOutcome(
                    row=row, status=EXCEPTION,
                    reason=f"generation {row.generation_id} is not in the catalogue"))
            elif not row.powertrain.strip():
                outcomes.append(RowOutcome(
                    row=row, status=EXCEPTION, reason="powertrain could not be established"))
            elif [t for t in siblings if t.canonical_id not in claimed]:
                # Some grade the catalogue holds was matched by no row in
                # this run, so this name may be that grade worded
                # differently rather than a new car. Nothing in the source
                # settles it, so a person does -- the catalogue does not
                # grow a second copy of a car it already has on a guess.
                unclaimed = [t.name for t in siblings if t.canonical_id not in claimed]
                outcomes.append(RowOutcome(
                    row=row, status=EXCEPTION,
                    reason=("this name matches no existing grade, and "
                            f"{len(unclaimed)} existing grade(s) went unmatched: "
                            + ", ".join(sorted(unclaimed)[:5]))))
            else:
                patch, _ = column_patch(row, {})
                outcomes.append(RowOutcome(row=row, status=CREATED, patch=patch))
            continue

        patch, conflicts = column_patch(row, target.columns)
        new_source = row.source_id.lower() not in {s.lower() for s in target.source_ids}
        if patch or new_source:
            outcomes.append(RowOutcome(row=row, status=PATCHED, trim_id=target.canonical_id,
                                       patch=patch, conflicts=conflicts))
        else:
            outcomes.append(RowOutcome(row=row, status=UNCHANGED, trim_id=target.canonical_id,
                                       conflicts=conflicts))
    return outcomes


def merged_source_refs(existing: dict | None, source_kind: str, source_id: str) -> dict:
    key = source_kind.lower()
    refs = {k: list(v) for k, v in (existing or {}).items()}
    current = [str(v).lower() for v in refs.get(key, [])]
    refs[key] = sorted({*current, source_id.lower()})
    return refs


def commands_from_outcomes(
    outcomes: Iterable[RowOutcome],
    *,
    generation_codes: dict[str, str],
    existing_by_trim: dict[str, ExistingTrim],
) -> tuple[list[dict], list[RowOutcome]]:
    """Compile write outcomes into UPSERT_MODEL_BUNDLE commands."""
    commands: list[dict] = []
    stranded: list[RowOutcome] = []
    for outcome in outcomes:
        if outcome.status not in (PATCHED, CREATED):
            continue
        row = outcome.row
        held = existing_by_trim.get(outcome.trim_id or "")
        # A patch belongs to the generation its trim already sits in; only a
        # create falls back to the generation the source was placed into.
        generation_id = held.generation_id if held else row.generation_id
        code = generation_codes.get(generation_id)
        if not code:
            outcome.status = EXCEPTION
            outcome.reason = "generation code could not be read"
            stranded.append(outcome)
            continue
        trim: dict[str, Any] = {
            "name": held.name if held else row.trim_name,
            "powertrain": (held.powertrain if held else row.powertrain).upper(),
            **outcome.patch,
            "source_refs": merged_source_refs(
                {k: list(v) for k, v in (held.columns.get("source_refs") or {}).items()}
                if held else None,
                row.source_kind, row.source_id),
        }
        if outcome.trim_id:
            trim["canonical_id"] = outcome.trim_id
        commands.append({
            "operation": "UPSERT_MODEL_BUNDLE",
            "canonical_id": row.model_id,
            "payload": {
                "brand": {"id": row.model_id.split(".", 1)[0]},
                "model": {},
                "generation": {"code": code},
                "variants": [],
                "trims": [trim],
            },
        })
    return commands, stranded


def batches_from_commands(
    commands: list[dict],
    *,
    year: int,
    source_kind: str,
    source_ref: str,
    batch_prefix: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> list[dict]:
    batches = []
    for index in range(0, len(commands), batch_size):
        batches.append({
            "schema_version": 1,
            "batch_id": f"{batch_prefix}-{index // batch_size + 1:03d}",
            "year": year,
            "source": {"kind": source_kind.upper(), "ref": source_ref},
            "commands": commands[index:index + batch_size],
        })
    return batches


def summarize(outcomes: Iterable[RowOutcome]) -> dict[str, int]:
    counts = {PATCHED: 0, CREATED: 0, UNCHANGED: 0, EXCEPTION: 0}
    for outcome in outcomes:
        counts[outcome.status] = counts.get(outcome.status, 0) + 1
    return counts
