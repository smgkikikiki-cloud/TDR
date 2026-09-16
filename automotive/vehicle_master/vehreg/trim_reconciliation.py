"""Source-backed MarketTrim candidate resolution and coverage accounting.

Research evidence is deliberately kept one step away from canonical MarketTrim
rows.  A source may prove a marketed grade name while still being ambiguous
about its exact powertrain or Thai retail lifecycle.  This module makes that
state explicit instead of forcing a guess or silently deleting the evidence.

The canonical catalog remains strict: a MarketTrim still requires one exact
powertrain.  Reconciliation state explains why source-backed rows have (or have
not) crossed that boundary yet.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import json
from pathlib import Path
import re
from typing import Iterable, Mapping, Sequence

from .catalog import Catalog, CatalogError, DATA_DIR, DEFAULT_YEAR
from .taxonomy import Powertrain


SCHEMA_VERSION = 1


class TrimResolutionStatus(str, Enum):
    """Disposition of source evidence before/alongside canonical MarketTrim."""

    READY = "READY"
    AMBIGUOUS_POWERTRAIN = "AMBIGUOUS_POWERTRAIN"
    NON_MARKET = "NON_MARKET"
    HISTORICAL_ONLY = "HISTORICAL_ONLY"
    RESEARCH_UNRESOLVED = "RESEARCH_UNRESOLVED"


# These states explicitly explain why source evidence may have zero canonical
# MarketTrim rows. READY is intentionally excluded: a READY zero-trim model is
# a promotion bug and must block a serving release.
ZERO_TRIM_EXEMPTIONS = frozenset({
    TrimResolutionStatus.AMBIGUOUS_POWERTRAIN,
    TrimResolutionStatus.NON_MARKET,
    TrimResolutionStatus.HISTORICAL_ONLY,
    TrimResolutionStatus.RESEARCH_UNRESOLVED,
})


@dataclass(frozen=True, slots=True)
class TrimCandidate:
    model_id: str
    generation_id: str
    raw_name: str
    source_ref: str
    source_powertrain_text: str = ""
    resolved_powertrain: Powertrain | None = None
    status: TrimResolutionStatus = TrimResolutionStatus.RESEARCH_UNRESOLVED
    reason: str = ""

    def as_row(self) -> dict:
        row = asdict(self)
        row["resolved_powertrain"] = (
            self.resolved_powertrain.value if self.resolved_powertrain else None
        )
        row["status"] = self.status.value
        return row


# Ordered from more explicit retail wording to broader wording.  Word-boundary
# patterns avoid reading the "EV" inside unrelated names.  EREV is normalized
# to canonical REEV by Powertrain.parse elsewhere in the codebase.
_POWERTRAIN_PATTERNS: tuple[tuple[Powertrain, re.Pattern[str]], ...] = (
    (Powertrain.REEV, re.compile(r"\b(?:REEV|EREV|RANGE[- ]?EXTENDER)\b", re.I)),
    (Powertrain.PHEV, re.compile(r"\b(?:PHEV|PLUG[- ]?IN|DM[- ]?I)\b", re.I)),
    (Powertrain.HEV, re.compile(r"\b(?:HEV|FULL[- ]?HYBRID|E[- ]?POWER)\b", re.I)),
    (Powertrain.BEV, re.compile(r"\b(?:BEV|PURE[- ]?ELECTRIC|ELECTRIC)\b", re.I)),
    (Powertrain.FCEV, re.compile(r"\b(?:FCEV|FUEL[- ]?CELL)\b", re.I)),
    (Powertrain.ICE, re.compile(r"\b(?:ICE|PETROL|GASOLINE|DIESEL|TFSI|TDI)\b", re.I)),
)


def powertrain_hints(text: object) -> frozenset[Powertrain]:
    """Return only powertrains explicitly named by free-form source text."""
    value = str(text or "")
    return frozenset(powertrain for powertrain, pattern in _POWERTRAIN_PATTERNS
                     if pattern.search(value))


def _known_generation_powertrains(catalog: Catalog, generation_id: str) -> frozenset[Powertrain]:
    return frozenset(
        variant.powertrain
        for variant in catalog.variants.values()
        if variant.generation_id == generation_id
        and variant.powertrain is not Powertrain.UNKNOWN
    )


def resolve_candidate_powertrain(
    *,
    raw_name: str,
    source_powertrain_text: str,
    catalog: Catalog,
    generation_id: str,
) -> tuple[Powertrain | None, TrimResolutionStatus, str]:
    """Resolve one candidate without guessing across a source ambiguity.

    Trust order is deliberate:
      1. an exact powertrain written in the trim/grade name;
      2. one exact powertrain written at source-model level;
      3. one canonical analytical powertrain only when the source did not name
         a powertrain at all.

    A source that explicitly says "BEV / EREV" stays ambiguous when the grade
    name itself does not disambiguate it.  We do *not* use an analytical Variant
    to collapse that source ambiguity because Variant is a different layer and
    may itself be the stale record under repair.
    """
    if generation_id not in catalog.generations:
        raise CatalogError(f"unknown generation_id {generation_id!r}")

    trim_hints = powertrain_hints(raw_name)
    if len(trim_hints) == 1:
        powertrain = next(iter(trim_hints))
        return powertrain, TrimResolutionStatus.READY, "exact powertrain in trim name"
    if len(trim_hints) > 1:
        return None, TrimResolutionStatus.AMBIGUOUS_POWERTRAIN, (
            "trim name names multiple powertrains"
        )

    source_hints = powertrain_hints(source_powertrain_text)
    if len(source_hints) == 1:
        powertrain = next(iter(source_hints))
        return powertrain, TrimResolutionStatus.READY, "exact powertrain in source model text"
    if len(source_hints) > 1:
        return None, TrimResolutionStatus.AMBIGUOUS_POWERTRAIN, (
            "source model text names multiple powertrains and trim name does not disambiguate"
        )

    canonical = _known_generation_powertrains(catalog, generation_id)
    if len(canonical) == 1:
        powertrain = next(iter(canonical))
        return powertrain, TrimResolutionStatus.READY, (
            "source names no powertrain; generation has one canonical analytical powertrain"
        )
    if len(canonical) > 1:
        return None, TrimResolutionStatus.AMBIGUOUS_POWERTRAIN, (
            "source names no powertrain and generation has multiple analytical powertrains"
        )
    return None, TrimResolutionStatus.RESEARCH_UNRESOLVED, (
        "neither source nor canonical generation identifies a powertrain"
    )


def make_candidate(
    *,
    model_id: str,
    generation_id: str,
    raw_name: str,
    source_ref: str,
    source_powertrain_text: str,
    catalog: Catalog,
) -> TrimCandidate:
    if model_id not in catalog.models:
        raise CatalogError(f"unknown model_id {model_id!r}")
    generation = catalog.generations.get(generation_id)
    if generation is None or generation.model_id != model_id:
        raise CatalogError(
            f"generation {generation_id!r} is not a child of model {model_id!r}"
        )
    if not str(raw_name).strip():
        raise CatalogError("trim candidate requires raw_name")
    if not str(source_ref).strip():
        raise CatalogError("trim candidate requires source_ref")
    powertrain, status, reason = resolve_candidate_powertrain(
        raw_name=raw_name,
        source_powertrain_text=source_powertrain_text,
        catalog=catalog,
        generation_id=generation_id,
    )
    return TrimCandidate(
        model_id=model_id,
        generation_id=generation_id,
        raw_name=str(raw_name).strip(),
        source_ref=str(source_ref).strip(),
        source_powertrain_text=str(source_powertrain_text or "").strip(),
        resolved_powertrain=powertrain,
        status=status,
        reason=reason,
    )


def reconciliation_path(data_dir: Path | str = DATA_DIR,
                        year: int = DEFAULT_YEAR) -> Path:
    return Path(data_dir) / str(year) / "market" / "trims" / "reconciliation.json"


def load_reconciliation_state(
    data_dir: Path | str = DATA_DIR,
    year: int = DEFAULT_YEAR,
) -> dict:
    path = reconciliation_path(data_dir, year)
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "models": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise CatalogError(
            f"{path}: unsupported reconciliation schema {payload.get('schema_version')!r}"
        )
    if not isinstance(payload.get("models"), list):
        raise CatalogError(f"{path}: models must be an array")
    return payload


def validate_reconciliation_state(catalog: Catalog, state: Mapping) -> list[str]:
    problems: list[str] = []
    seen: set[str] = set()
    for row in state.get("models", []):
        if not isinstance(row, Mapping):
            problems.append("reconciliation model row must be an object")
            continue
        model_id = str(row.get("model_id") or "").strip()
        if not model_id:
            problems.append("reconciliation row missing model_id")
            continue
        if model_id in seen:
            problems.append(f"reconciliation duplicate model_id {model_id}")
        seen.add(model_id)
        if model_id not in catalog.models:
            problems.append(f"reconciliation unknown model_id {model_id}")
        try:
            status = TrimResolutionStatus(str(row.get("status") or ""))
        except ValueError:
            problems.append(f"reconciliation {model_id}: invalid status {row.get('status')!r}")
            status = None
        refs = row.get("source_refs")
        if not isinstance(refs, list) or not refs or not all(
                isinstance(ref, str) and ref.strip() for ref in refs):
            problems.append(f"reconciliation {model_id}: nonempty source_refs required")
        count = row.get("source_trim_count")
        if type(count) is not int or count < 0:
            problems.append(f"reconciliation {model_id}: source_trim_count must be >= 0 integer")
        if status in ZERO_TRIM_EXEMPTIONS and not str(row.get("reason") or "").strip():
            problems.append(f"reconciliation {model_id}: {status.value} requires reason")
    return problems


def release_reconciliation_report(
    release: Mapping,
    *,
    data_dir: Path | str = DATA_DIR,
    year: int = DEFAULT_YEAR,
) -> dict:
    """Explain every source-backed zero-trim model and flag silent loss.

    Only source evidence registered in ``reconciliation.json`` participates in
    this gate.  Importers are responsible for registering evidence when it
    cannot immediately be promoted.  Canonical models that already have trims
    are reported as CANONICAL even if an older state row remains in the file.
    """
    state = load_reconciliation_state(data_dir, year)
    model_ids = {
        str(row.get("canonical_id") or "")
        for row in release.get("models", [])
        if isinstance(row, Mapping)
    }
    trim_counts: dict[str, int] = {}
    for trim in release.get("market_trims", []):
        if not isinstance(trim, Mapping):
            continue
        model_id = str(trim.get("model_id") or "")
        trim_counts[model_id] = trim_counts.get(model_id, 0) + 1

    rows: list[dict] = []
    blockers: list[dict] = []
    counts: dict[str, int] = {}
    for raw in state.get("models", []):
        model_id = str(raw.get("model_id") or "")
        declared = str(raw.get("status") or "")
        canonical_count = trim_counts.get(model_id, 0)
        effective = "CANONICAL" if canonical_count else declared
        row = {
            "model_id": model_id,
            "source_trim_count": raw.get("source_trim_count", 0),
            "canonical_trim_count": canonical_count,
            "declared_status": declared,
            "status": effective,
            "reason": raw.get("reason", ""),
            "source_refs": list(raw.get("source_refs") or []),
        }
        if model_id not in model_ids:
            row["blocker"] = "SOURCE_EVIDENCE_MODEL_NOT_IN_RELEASE"
            blockers.append(row)
        elif not canonical_count:
            try:
                status = TrimResolutionStatus(declared)
            except ValueError:
                status = None
            if status not in ZERO_TRIM_EXEMPTIONS:
                row["blocker"] = "SOURCE_EVIDENCE_WITHOUT_CANONICAL_TRIM_OR_EXEMPTION"
                blockers.append(row)
        counts[effective] = counts.get(effective, 0) + 1
        rows.append(row)

    return {
        "schema_version": SCHEMA_VERSION,
        "tracked_models": len(rows),
        "counts": dict(sorted(counts.items())),
        "blocker_count": len(blockers),
        "blockers": blockers,
        "models": rows,
    }


def generation_powertrain_mismatches(catalog: Catalog) -> list[dict]:
    """Report retail-vs-analytical disagreements without rewriting either side."""
    out: list[dict] = []
    for trim in sorted(catalog.trims.values(), key=lambda row: row.id):
        analytical = _known_generation_powertrains(catalog, trim.generation_id)
        if analytical and trim.powertrain not in analytical:
            out.append({
                "trim_id": trim.id,
                "model_id": catalog.model_for_trim(trim.id).id,
                "generation_id": trim.generation_id,
                "trim_powertrain": trim.powertrain.value,
                "analytical_powertrains": sorted(p.value for p in analytical),
                "source_refs": {key: list(value) for key, value in trim.source_refs.items()},
            })
    return out


__all__ = [
    "SCHEMA_VERSION",
    "TrimCandidate",
    "TrimResolutionStatus",
    "ZERO_TRIM_EXEMPTIONS",
    "generation_powertrain_mismatches",
    "load_reconciliation_state",
    "make_candidate",
    "powertrain_hints",
    "reconciliation_path",
    "release_reconciliation_report",
    "resolve_candidate_powertrain",
    "validate_reconciliation_state",
]
