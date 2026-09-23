"""Patch MarketTrim rows from a source export: resolve identity, then write columns.

The MarketTrim row is the spec source of truth for the small set of fields it
holds. It is what the release publishes and what compare reads; ``SpecLedger``
publishes zero facts on its own, so a value that reaches neither a column nor
a spec fact lands nowhere. Ingestion therefore writes both: the trim columns
this module has always written (``column_patch``, ``FIELD_TO_COLUMN``), and,
since the identity this module resolves is exactly what a comparable-spec
fact needs to be attached to anything, comparable-spec facts and price
observations for the row's other values (``spec_commands_from_outcomes``,
``price_commands_from_outcomes``) too.

What a source may do to a MarketTrim column it carries:

  blank in the source        the key is omitted, so the stored value stands
  value held is None         filled
  both values, equal         omitted -- nothing to write
  both values, differ        the source wins only where it is authoritative
                             for that field; otherwise it reports a conflict
                             and writes nothing

A comparable-spec fact is a different kind of value and is not held to that
column-authority rule -- the registry is the single record of a field over
time, so a later, differently-dated observation is a new fact, not a
contested overwrite of the old one. See ``spec_commands_from_outcomes``.

Identity is resolved deterministically or not at all. A source id already
recorded on a trim resolves to that trim (a re-approval is the same car). An
exact name match inside one model+generation+powertrain resolves to that
trim. A grade that does not exist yet, under a model and generation that do,
is created. Anything else -- two equally good matches, an unknown model --
is an exception for a person, and is never guessed at.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
import unicodedata
from typing import Any, Iterable, Optional

from .comparable_specs import SpecRegistry, ValueType
from .normalize import trim_identity

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
    "powertrain.transmission": "transmission",
}

#: Deliberately unmapped, with the reason, so the next person does not read
#: an absence as an oversight:
#:   identity.powertrain      part of the canonical id; an import may not
#:                            change which car a trim is
#:   battery.gross_capacity_kwh  the nameplate pack derived from charge and
#:                            voltage, which is not MarketTrim.battery_kwh's
#:                            catalog capacity -- a different quantity
#:   manufacturing.factory    the source names the company, not the plant the
#:                            column means
#:   emissions.*, efficiency.*, ev.*, battery.*, charging.*, engine.fuel_type,
#:   engine.combustion_type, powertrain.gear_count, powertrain.motor_type,
#:   fitment.tyre_size, vehicle.model_year, vehicle.declared_total_weight_kg
#:                            no column on the served trim row, and the spec
#:                            ledger publishes nothing, so writing them would
#:                            put data where the site cannot read it

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
    """One normalized record from a source export, ready to resolve.

    ``values`` and ``specs`` are deliberately two different dicts, not one
    read two ways: ``values`` is whatever the source stated, unfiltered, and
    is what ``column_patch`` reads its ``FIELD_TO_COLUMN`` subset from --
    MarketTrim's own columns are not a comparable-spec registry concept, and
    must not stop being written just because a field the registry does not
    (yet) define shares that dict. ``specs`` is the registry-accepted subset
    (a caller normally passes ``applicable_specs()``'s own result) that
    ``spec_commands_from_outcomes`` turns into APPEND_SPEC facts. A field
    can be, and often is, in one and not the other.

    The remaining fields are needed only for the facts/price path and are
    optional so a caller that only ever wrote columns -- and every existing
    test that builds a ``SourceRow`` by hand -- is unaffected.
    """

    source_id: str
    source_kind: str
    model_id: str
    generation_id: str
    powertrain: str
    trim_name: str
    values: dict[str, Any]
    #: The registry-accepted subset of this row's values, for APPEND_SPEC.
    #: Never read by column_patch.
    specs: dict[str, Any] = field(default_factory=dict)
    #: registry key -> {qualifier key: value}, e.g. measurement_basis.
    qualifiers: dict[str, dict[str, str]] = field(default_factory=dict)
    #: ISO date the source observed these values (a fact's ``start``). Every
    #: fact this row produces is dated by this, never by the day the import
    #: happens to run -- see spec_commands_from_outcomes.
    observed_at: str = ""
    #: Where a person can read the record this row came from.
    source_ref: str = ""
    #: The manufacturer's filed retail price, if the source states one.
    price_thb: Optional[int] = None


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


def resolved_trim_id(outcome: RowOutcome) -> str:
    """The canonical trim id this outcome's row will end up attached to,
    known ahead of the write for CREATED rows too.

    trim_identity() is not a reimplementation of the writer's own rule -- it
    is the exact function vehreg/canonical_write.py calls to derive a new
    trim's id when a command leaves it unset, imported here rather than
    guessed at a second time. Computing it directly (instead of the
    trim_ref-by-reference indirection APPEND_SPEC also supports) is what
    lets a CREATED row's price observation resolve too: APPEND_PRICE has no
    trim_ref fallback at all, so a row whose trim does not exist yet could
    otherwise never get one.
    """
    if outcome.trim_id:
        return outcome.trim_id
    row = outcome.row
    return trim_identity(row.generation_id, None, row.trim_name, row.powertrain)


#: The ``source`` string a fact or price observation carries, keyed by
#: SourceRow.source_kind. "ecosticker" (not "eco") because that is the
#: spelling already established elsewhere for ECO Sticker provenance --
#: vehreg/comparable_specs.py's review-cohort builder and the retired
#: vehreg/ecosticker_import.py::commands_for both write it, and existing
#: SpecFact/PriceObservation data on disk already uses it. A source kind
#: with no entry here falls back to its own lowercased name rather than
#: raising, since this module's column-writing half already works for any
#: source kind a caller names.
_SOURCE_LABELS: dict[str, str] = {"ECO": "ecosticker"}


def _source_label(source_kind: str) -> str:
    return _SOURCE_LABELS.get(source_kind.upper(), source_kind.lower())


def _fact_unit(definition, value: Any) -> str:
    return definition.canonical_unit if definition.value_type is ValueType.NUMBER else ""


def _fact_unchanged(prior: dict[str, Any], candidate: dict[str, Any]) -> bool:
    """Same value, unit, qualifiers and observed_at as what is already on
    disk under this exact fact_id.

    APPEND_SPEC's own writer always rewrites its target file and always
    counts it as a changed file (vehreg/canonical_write.py's _append_spec
    has no before-equals-after short-circuit, unlike APPEND_PRICE's
    same-day-same-amount check) -- so without this comparison, re-running
    an unchanged import would emit a command for every fact on every row,
    every time, and the batch would never register as
    canonical_changed=False. This is what keeps a re-import of the exact
    same file from doing that -- the same guarantee tools/import_source.py
    already gives the MarketTrim-column half of a row.
    """
    return (
        str(prior.get("value_state") or "KNOWN") == "KNOWN"
        and prior.get("value") == candidate.get("value")
        and str(prior.get("unit") or "") == str(candidate.get("unit") or "")
        and {str(k): str(v) for k, v in (prior.get("qualifiers") or {}).items()}
        == {str(k): str(v) for k, v in (candidate.get("qualifiers") or {}).items()}
        and str(prior.get("observed_at") or "") == str(candidate.get("observed_at") or "")
    )


def spec_commands_from_outcomes(
    outcomes: Iterable[RowOutcome],
    *,
    registry: SpecRegistry,
    existing_facts: dict[str, dict[str, Any]],
    submitted_at: str = "",
) -> list[dict]:
    """One APPEND_SPEC per value a resolved row states, for every field the
    registry accepts -- not just PATCHED/CREATED rows.

    A row UNCHANGED at the MarketTrim-column level (column_patch found none
    of FIELD_TO_COLUMN's 8 columns different) says nothing about whether its
    comparable-spec facts are new: those two things were never written
    together before this function existed, so a trim whose columns have
    long been correct can still be recording a field like CO2 or battery
    chemistry for the first time. Only EXCEPTION rows -- no trim identity to
    attach a fact to -- are skipped.

    ``submitted_at`` is the fallback for a row whose source states no
    observation date of its own (``row.observed_at`` empty) -- the run's own
    date, exactly as the retired ``ecosticker_import.commands_for``'s own
    ``observed_at`` parameter did. A row with a stated date is never
    overridden by it.

    fact_id is deterministic and source-specific
    (``eco:<source_id>:<field_key>``, the row's own source_kind lowercased,
    never the established "ecosticker" spelling ``source`` below uses --
    fact_id is an internal key, not read as provenance), never the writer's
    `admin:<trim_id>:<field_key>` fallback: that fallback names a fact by
    what it is ABOUT rather than by which record STATED it, so a later,
    differently-dated ECO record for the same trim+field would silently
    overwrite the earlier one's fact file in place instead of becoming a
    new dated fact the ledger's own conflict/versioning rules can reason
    about. Re-importing the same source record, by contrast, is the same
    fact_id every time -- the correct case for revision-in-place.
    """
    commands: list[dict] = []
    for outcome in outcomes:
        if outcome.status == EXCEPTION:
            continue
        row = outcome.row
        observed_at = row.observed_at or submitted_at
        if not row.specs or not observed_at or not row.source_ref:
            continue
        trim_id = resolved_trim_id(outcome)
        for field_key, value in sorted(row.specs.items()):
            if value is None:
                continue
            definition = registry.fields.get(field_key)
            if definition is None:
                continue  # not a registry key; applicable_specs() already dropped/reported it upstream
            fact_id = f"{row.source_kind.lower()}:{row.source_id}:{field_key}"
            candidate = {
                "fact_id": fact_id,
                "trim_id": trim_id,
                "field_key": field_key,
                "value_state": "KNOWN",
                "value": value,
                "unit": _fact_unit(definition, value),
                "qualifiers": {str(k): str(v) for k, v in (row.qualifiers.get(field_key) or {}).items()},
                "observed_at": observed_at,
                "verification_status": "VERIFIED",
                "source": _source_label(row.source_kind),
                "source_ref": row.source_ref,
            }
            prior = existing_facts.get(fact_id)
            if prior is not None and _fact_unchanged(prior, candidate):
                continue
            commands.append({"operation": "APPEND_SPEC", "canonical_id": trim_id, "payload": candidate})
    return commands


def price_commands_from_outcomes(
    outcomes: Iterable[RowOutcome], *, price_type: str, submitted_at: str = "",
) -> tuple[list[dict], list[dict]]:
    """One APPEND_PRICE per dated price a resolved row's source states,
    deduplicated and conflict-checked the way ecosticker_import.py's
    _resolve_price_observations always has: the same trim can carry several
    dated observations (a filing re-approved each year is real history, not
    a duplicate), but two DIFFERENT amounts for the same trim on the same
    date mean the trim identity is too coarse to price, and neither is
    written -- the fix is a finer trim, never a guess at which figure is real.

    ``submitted_at`` is the same run-date fallback ``spec_commands_from_
    outcomes`` takes, for a row whose source states no date of its own.

    Returns (commands, suppressed) -- suppressed rows are reported, not
    silently dropped, the same as an unresolved identity or a dropped spec
    value.
    """
    by_key: dict[tuple[str, str], list[RowOutcome]] = {}
    for outcome in outcomes:
        if outcome.status == EXCEPTION or not outcome.row.price_thb or outcome.row.price_thb <= 0:
            continue
        observed_at = outcome.row.observed_at or submitted_at
        if not observed_at:
            continue
        key = (resolved_trim_id(outcome), observed_at)
        by_key.setdefault(key, []).append(outcome)

    commands: list[dict] = []
    suppressed: list[dict] = []
    for (trim_id, observed_at), group in by_key.items():
        amounts = {int(o.row.price_thb) for o in group}
        if len(amounts) > 1:
            listed = ", ".join(f"{amount:,}" for amount in sorted(amounts))
            for outcome in group:
                suppressed.append({
                    "source_id": outcome.row.source_id, "trim_id": trim_id,
                    "reason": (f"{trim_id} มีราคาต่างกัน {len(amounts)} ค่า ({listed}) "
                              f"ในวันเดียวกัน ({observed_at}) จึงไม่บันทึกราคาใดเลย"),
                })
            continue
        representative = group[0]
        commands.append({
            "operation": "APPEND_PRICE",
            "canonical_id": trim_id,
            "payload": {
                "trim_id": trim_id,
                "amount_thb": int(representative.row.price_thb),
                "price_type": price_type,
                "observed_at": observed_at,
                "source": _source_label(representative.row.source_kind),
                "source_ref": representative.row.source_ref,
            },
        })
        for duplicate in group[1:]:
            suppressed.append({
                "source_id": duplicate.row.source_id, "trim_id": trim_id,
                "reason": (f"ราคาเดียวกัน ({int(duplicate.row.price_thb):,}) และวันเดียวกัน "
                          f"({observed_at}) กับ source_id {representative.row.source_id} "
                          "จึงนับเป็น observation เดียว"),
            })
    return commands, suppressed


def batches_from_commands(
    commands: list[dict],
    *,
    year: int,
    source_kind: str,
    source_ref: str,
    batch_prefix: str,
    submitted_at: str,
    actor: str = "source-import",
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> list[dict]:
    """Split the commands into batches the input pipeline will accept.

    The batch id carries a digest of what is in it, and ``submitted_at``
    is the caller's, not the clock's. Together that is what makes a retry
    a retry: an import interrupted halfway and run again produces the
    same batches, which the pipeline recognises and replays instead of
    rejecting as "already used with different content" -- which is what
    a positional id plus ``now()`` produced, so re-uploading a corrected
    file after a failure crashed on the batch that had already landed.
    """
    batches = []
    for index in range(0, len(commands), batch_size):
        slice_ = commands[index:index + batch_size]
        digest = hashlib.sha256(
            json.dumps(slice_, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()[:12]
        batches.append({
            "schema_version": 1,
            "batch_id": f"{batch_prefix}-{index // batch_size + 1:03d}-{digest}",
            "year": year,
            "source": {"kind": source_kind.upper(), "ref": source_ref},
            "actor": actor,
            "reason": f"bulk import from {source_ref}",
            "submitted_at": submitted_at,
            "commands": slice_,
        })
    return batches


def summarize(outcomes: Iterable[RowOutcome]) -> dict[str, int]:
    counts = {PATCHED: 0, CREATED: 0, UNCHANGED: 0, EXCEPTION: 0}
    for outcome in outcomes:
        counts[outcome.status] = counts.get(outcome.status, 0) + 1
    return counts
