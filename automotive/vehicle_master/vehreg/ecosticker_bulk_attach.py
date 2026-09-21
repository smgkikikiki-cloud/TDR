"""Bulk-resolve ECO Sticker review candidates that carry no judgment to make.

The admin review queue (``/admin/eco-trims``) asks a person to click Attach
or Create for every candidate group, one row at a time. That is the right
shape for a genuinely ambiguous case -- which existing trim is this, or is
this actually a new grade -- but it is the wrong shape for the common case:
exactly one existing MarketTrim already shares the group's model,
generation and powertrain, and that trim's name is *exactly* the ECO
record's label once normalized. There is no decision left to make there; a
person clicking "Attach" a thousand times on that case is not a thousand
decisions, it is one rule applied a thousand times, and a script should
apply it instead.

Matching here is intentionally narrower than the fuzzy search a human
does by eye: normalized string EQUALITY only (case, spacing and
punctuation folded -- see :func:`normalized_label`), scoped to trims that
already share model + generation + powertrain. Zero matches, or more than
one, is not resolved here -- it is reported for a human, the same two
buckets the admin page already sorts into (no candidate / several
candidates), just without asking a person to first sit through the
thousand unambiguous rows to find them.

This module is pure logic: no filesystem, no network. See
``tools/ecosticker_bulk_attach.py`` for reading the ECO snapshot, reading
the live catalogue and turning a resolution into a canonical input batch.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Iterable

#: One canonical_input_batches row accepts at most 500 commands
#: (``enqueuePayload`` in ``app/admin/input-actions.ts``); a few hundred
#: also keeps a single PR diff reviewable.
DEFAULT_BATCH_SIZE = 400


def normalized_label(value: object) -> str:
    """Case/spacing/punctuation-folded comparison key -- equality, not a score."""
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True)
class EcoCandidateGroup:
    key: str
    model_id: str
    generation_id: str
    powertrain: str
    raw_label: str
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class ExistingTrim:
    canonical_id: str
    model_id: str
    generation_id: str
    name: str
    powertrain: str
    eco_source_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class AutoAttachResolution:
    group: EcoCandidateGroup
    trim: ExistingTrim


@dataclass(frozen=True)
class NeedsHumanResolution:
    group: EcoCandidateGroup
    reason: str
    candidate_count: int


def resolve_groups(
    groups: Iterable[EcoCandidateGroup],
    trims: Iterable[ExistingTrim],
) -> tuple[list[AutoAttachResolution], list[NeedsHumanResolution]]:
    """Split candidate groups into what a script may attach and what a person must.

    A group already attached (one of its source ids is already on a
    same-scope trim) is dropped entirely, matching the admin page hiding
    attached rows by default -- there is nothing left to queue or to review.
    """
    by_scope: dict[tuple[str, str, str], list[ExistingTrim]] = {}
    for trim in trims:
        scope = (trim.model_id, trim.generation_id, trim.powertrain.upper())
        by_scope.setdefault(scope, []).append(trim)

    auto_attach: list[AutoAttachResolution] = []
    needs_human: list[NeedsHumanResolution] = []
    for group in groups:
        scope = (group.model_id, group.generation_id, group.powertrain.upper())
        candidates = by_scope.get(scope, [])
        source_set = set(group.source_ids)
        if any(source_set.intersection(trim.eco_source_ids) for trim in candidates):
            continue
        label = normalized_label(group.raw_label)
        exact = [trim for trim in candidates if normalized_label(trim.name) == label]
        if len(exact) == 1:
            auto_attach.append(AutoAttachResolution(group=group, trim=exact[0]))
        elif not exact:
            reason = ("no existing trim shares this model/generation/powertrain" if not candidates
                       else "no candidate trim's name matches the ECO label exactly")
            needs_human.append(NeedsHumanResolution(group=group, reason=reason, candidate_count=len(candidates)))
        else:
            needs_human.append(NeedsHumanResolution(
                group=group, reason="more than one trim shares this exact name", candidate_count=len(exact)))
    return auto_attach, needs_human


def merged_source_refs(existing: dict | None, new_source_ids: Iterable[str]) -> dict:
    refs = dict(existing) if isinstance(existing, dict) else {}
    current = refs.get("ecosticker")
    current = [str(v).lower() for v in current] if isinstance(current, list) else []
    refs["ecosticker"] = sorted({*current, *(str(v).lower() for v in new_source_ids)})
    return refs


def attach_command(
    resolution: AutoAttachResolution,
    *,
    generation_code: str,
    existing_source_refs: dict | None,
) -> dict:
    """The same ``UPSERT_MODEL_BUNDLE`` shape ``enqueueEcoAttachExistingTrim`` builds by hand."""
    brand_id = resolution.group.model_id.split(".", 1)[0]
    trim = resolution.trim
    return {
        "operation": "UPSERT_MODEL_BUNDLE",
        "canonical_id": resolution.group.model_id,
        "reason": f"bulk-attach ECO evidence: exact trim-name match ({resolution.group.raw_label!r})",
        "payload": {
            "brand": {"id": brand_id},
            "model": {},
            "generation": {"code": generation_code},
            "variants": [],
            "trims": [{
                "canonical_id": trim.canonical_id,
                "name": trim.name,
                "powertrain": trim.powertrain,
                "source_refs": merged_source_refs(existing_source_refs, resolution.group.source_ids),
            }],
        },
    }


def batches_from_resolutions(
    resolutions: list[AutoAttachResolution],
    *,
    generation_codes: dict[str, str],
    source_refs_by_trim: dict[str, dict],
    year: int,
    snapshot_ref: str,
    batch_prefix: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> tuple[list[dict], list[NeedsHumanResolution]]:
    """Compile resolutions into ``canonical_input_batches``-ready payloads.

    A resolution whose generation code is unknown (the live catalogue query
    that would supply it failed or came back empty) is not silently
    dropped -- it is returned as an additional needs-human item, because a
    trim this script cannot describe is not one it should attach either.
    """
    commands = []
    stranded: list[NeedsHumanResolution] = []
    for resolution in resolutions:
        code = generation_codes.get(resolution.group.generation_id)
        if not code:
            stranded.append(NeedsHumanResolution(
                group=resolution.group,
                reason="matched exactly one trim, but its generation code could not be read",
                candidate_count=1,
            ))
            continue
        commands.append(attach_command(
            resolution, generation_code=code,
            existing_source_refs=source_refs_by_trim.get(resolution.trim.canonical_id),
        ))

    batches = []
    for index in range(0, len(commands), batch_size):
        chunk = commands[index:index + batch_size]
        batches.append({
            "schema_version": 1,
            "batch_id": f"{batch_prefix}-{index // batch_size + 1:03d}",
            "year": year,
            "source": {"kind": "ECO", "ref": snapshot_ref},
            "reason": "Bulk-attach ECO evidence to exact-name-match existing trims",
            "commands": chunk,
        })
    return batches, stranded
