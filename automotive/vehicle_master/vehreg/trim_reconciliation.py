"""Source-backed MarketTrim resolution, canonical overlay, and coverage gates.

Retail grades are a different grain from analytical registration Variants.  The
legacy catalog can still carry nested ``generation.trims`` rows, but new retail
identity may also live in the dedicated ``market/trims/canonical.json`` store.
That keeps showroom churn out of analytical model files while preserving the
same immutable serving-release schema.

Research evidence is deliberately kept one step away from canonical MarketTrim
rows. A source may prove a marketed grade name while still being ambiguous
about its exact powertrain or Thai retail lifecycle. Reconciliation state makes
that gap explicit instead of forcing a guess or silently deleting evidence.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from enum import Enum
import json
from pathlib import Path
import re
from typing import Mapping

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


# READY is deliberately absent. Any source row that is ready to promote but is
# not represented canonically is a release blocker.
UNRESOLVED_EXEMPTIONS = frozenset({
    TrimResolutionStatus.AMBIGUOUS_POWERTRAIN,
    TrimResolutionStatus.NON_MARKET,
    TrimResolutionStatus.HISTORICAL_ONLY,
    TrimResolutionStatus.RESEARCH_UNRESOLVED,
})
ZERO_TRIM_EXEMPTIONS = UNRESOLVED_EXEMPTIONS  # backwards-compatible name


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


# Word boundaries make bare EV safe: it matches "S05 EV 510" but not letters
# embedded in another word. EREV is canonical REEV in this warehouse.
_POWERTRAIN_PATTERNS: tuple[tuple[Powertrain, re.Pattern[str]], ...] = (
    (Powertrain.REEV, re.compile(r"\b(?:REEV|EREV|RANGE[- ]?EXTENDER)\b", re.I)),
    (Powertrain.PHEV, re.compile(r"\b(?:PHEV|PLUG[- ]?IN|DM[- ]?I)\b", re.I)),
    (Powertrain.HEV, re.compile(r"\b(?:HEV|FULL[- ]?HYBRID|E[- ]?POWER)\b", re.I)),
    (Powertrain.BEV, re.compile(r"\b(?:BEV|EV|PURE[- ]?ELECTRIC|ELECTRIC)\b", re.I)),
    (Powertrain.FCEV, re.compile(r"\b(?:FCEV|FUEL[- ]?CELL)\b", re.I)),
    (Powertrain.ICE, re.compile(r"\b(?:ICE|PETROL|GASOLINE|DIESEL|TFSI|TDI)\b", re.I)),
)
_LOCAL_ID = re.compile(r"^[a-z0-9][a-z0-9_]*$")


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

    Trust order:
      1. one exact powertrain written in the trim/grade name;
      2. one exact powertrain written at source-model level;
      3. one canonical analytical powertrain only when the source names none.

    If source text explicitly says BEV / EREV and a grade does not disambiguate,
    the row stays ambiguous. Analytical Variant is a different layer and may be
    the stale record under repair, so it cannot collapse a source ambiguity.
    """
    if generation_id not in catalog.generations:
        raise CatalogError(f"unknown generation_id {generation_id!r}")

    trim_hints = powertrain_hints(raw_name)
    if len(trim_hints) == 1:
        return next(iter(trim_hints)), TrimResolutionStatus.READY, "exact powertrain in trim name"
    if len(trim_hints) > 1:
        return None, TrimResolutionStatus.AMBIGUOUS_POWERTRAIN, "trim name names multiple powertrains"

    source_hints = powertrain_hints(source_powertrain_text)
    if len(source_hints) == 1:
        return next(iter(source_hints)), TrimResolutionStatus.READY, "exact powertrain in source model text"
    if len(source_hints) > 1:
        return None, TrimResolutionStatus.AMBIGUOUS_POWERTRAIN, (
            "source model text names multiple powertrains and trim name does not disambiguate"
        )

    canonical = _known_generation_powertrains(catalog, generation_id)
    if len(canonical) == 1:
        return next(iter(canonical)), TrimResolutionStatus.READY, (
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


def _trim_root(data_dir: Path | str, year: int) -> Path:
    return Path(data_dir) / str(year) / "market" / "trims"


def canonical_trim_overlay_path(data_dir: Path | str = DATA_DIR,
                                year: int = DEFAULT_YEAR) -> Path:
    return _trim_root(data_dir, year) / "canonical.json"


def reconciliation_path(data_dir: Path | str = DATA_DIR,
                        year: int = DEFAULT_YEAR) -> Path:
    return _trim_root(data_dir, year) / "reconciliation.json"


def _load_versioned(path: Path, key: str) -> dict:
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, key: []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise CatalogError(
            f"{path}: unsupported schema {payload.get('schema_version')!r}"
        )
    if not isinstance(payload.get(key), list):
        raise CatalogError(f"{path}: {key} must be an array")
    return payload


def load_canonical_trim_overlay(data_dir: Path | str = DATA_DIR,
                                year: int = DEFAULT_YEAR) -> dict:
    return _load_versioned(canonical_trim_overlay_path(data_dir, year), "trims")


def load_reconciliation_state(data_dir: Path | str = DATA_DIR,
                              year: int = DEFAULT_YEAR) -> dict:
    return _load_versioned(reconciliation_path(data_dir, year), "models")


def _normalize_source_refs(raw: object, *, label: str) -> dict[str, list[str]]:
    if not isinstance(raw, Mapping) or not raw:
        raise CatalogError(f"{label}: source_refs must be a nonempty object")
    out: dict[str, list[str]] = {}
    for key, value in raw.items():
        source = str(key).strip()
        values = [value] if isinstance(value, str) else value
        if not source or not isinstance(values, list):
            raise CatalogError(f"{label}: invalid source_refs")
        refs = [str(ref).strip() for ref in values if str(ref).strip()]
        if not refs:
            raise CatalogError(f"{label}: source_refs entries must be nonempty")
        out[source] = list(dict.fromkeys(refs))
    return out


def apply_canonical_trim_overlay(
    release: Mapping,
    *,
    data_dir: Path | str = DATA_DIR,
    year: int = DEFAULT_YEAR,
) -> dict:
    """Merge dedicated retail canonical rows into a serving release.

    Overlay rows may not replace an existing canonical trim. They intentionally
    carry no analytical ``variant_id`` until that cross-grain relationship is
    separately reviewed. Prices/spec facts likewise stay empty until their own
    evidence stores contain them.
    """
    out = deepcopy(dict(release))
    overlay = load_canonical_trim_overlay(data_dir, year)
    if not overlay.get("trims"):
        return out

    models = {
        str(row.get("canonical_id") or ""): row
        for row in out.get("models", []) if isinstance(row, Mapping)
    }
    generations = {
        str(row.get("canonical_id") or ""): row
        for row in out.get("generations", []) if isinstance(row, Mapping)
    }
    brands = {
        str(row.get("canonical_id") or ""): row
        for row in out.get("brands", []) if isinstance(row, Mapping)
    }
    existing_ids = {
        str(row.get("canonical_id") or "")
        for row in out.get("market_trims", []) if isinstance(row, Mapping)
    }
    additions: list[dict] = []

    for raw in overlay["trims"]:
        if not isinstance(raw, Mapping):
            raise CatalogError("canonical trim overlay row must be an object")
        local_id = str(raw.get("id") or "").strip()
        model_id = str(raw.get("model_id") or "").strip()
        generation_id = str(raw.get("generation_id") or "").strip()
        name = str(raw.get("name") or "").strip()
        if not _LOCAL_ID.fullmatch(local_id):
            raise CatalogError(f"canonical trim overlay: invalid local id {local_id!r}")
        if model_id not in models:
            raise CatalogError(f"canonical trim overlay {local_id}: unknown model {model_id!r}")
        generation = generations.get(generation_id)
        if generation is None or str(generation.get("model_id") or "") != model_id:
            raise CatalogError(
                f"canonical trim overlay {local_id}: generation {generation_id!r} is not under {model_id!r}"
            )
        if not name:
            raise CatalogError(f"canonical trim overlay {local_id}: name required")
        try:
            powertrain = Powertrain.parse(raw.get("powertrain"))
        except ValueError as exc:
            raise CatalogError(f"canonical trim overlay {local_id}: invalid powertrain") from exc
        if powertrain is Powertrain.UNKNOWN:
            raise CatalogError(f"canonical trim overlay {local_id}: exact powertrain required")
        if raw.get("variant_id") not in (None, ""):
            raise CatalogError(
                f"canonical trim overlay {local_id}: variant_id must stay empty until cross-grain mapping is reviewed"
            )
        source_refs = _normalize_source_refs(raw.get("source_refs"), label=local_id)
        canonical_id = f"{generation_id}.trim.{local_id}"
        if canonical_id in existing_ids:
            raise CatalogError(
                f"canonical trim overlay {local_id}: {canonical_id} already exists in base catalog"
            )
        existing_ids.add(canonical_id)

        aliases = raw.get("aliases") or []
        if not isinstance(aliases, list) or not all(isinstance(alias, str) for alias in aliases):
            raise CatalogError(f"canonical trim overlay {local_id}: aliases must be strings")
        specs = raw.get("specs") or {}
        if not isinstance(specs, Mapping):
            raise CatalogError(f"canonical trim overlay {local_id}: specs must be an object")
        model = models[model_id]
        brand = brands.get(str(model.get("brand_id") or ""), {})
        spec_payload = {
            "id": canonical_id,
            "generation_id": generation_id,
            "name": name,
            "powertrain": powertrain.value,
            "variant_id": None,
            "aliases": aliases,
            "source_refs": source_refs,
            **dict(specs),
        }
        additions.append({
            "canonical_id": canonical_id,
            "model_id": model_id,
            "generation_id": generation_id,
            "variant_id": None,
            "name": name,
            "powertrain": powertrain.value,
            "status": "UNVERIFIED",
            "payload": {
                "catalog_year": year,
                "price_as_of": out.get("as_of"),
                "model_id": model_id,
                "model": model.get("name_en"),
                "brand": brand.get("name_en"),
                "specs": spec_payload,
                "current_list_price": None,
                "price_history": [],
                "ecosticker_evidence": None,
                "comparable_specs": [],
            },
            "current_list_price": None,
            "campaign_quote": {},
            "price_history": [],
            "source_refs": source_refs,
        })

    merged = list(out.get("market_trims", [])) + additions
    out["market_trims"] = sorted(merged, key=lambda row: str(row.get("canonical_id") or ""))
    counts = dict(out.get("counts") or {})
    counts["market_trims"] = len(out["market_trims"])
    out["counts"] = counts
    return out


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
            TrimResolutionStatus(str(row.get("status") or ""))
        except ValueError:
            problems.append(f"reconciliation {model_id}: invalid status {row.get('status')!r}")
        refs = row.get("source_refs")
        if not isinstance(refs, list) or not refs or not all(
                isinstance(ref, str) and ref.strip() for ref in refs):
            problems.append(f"reconciliation {model_id}: nonempty source_refs required")
        count = row.get("source_trim_count")
        if type(count) is not int or count < 0:
            problems.append(f"reconciliation {model_id}: source_trim_count must be >= 0 integer")
        if not str(row.get("reason") or "").strip():
            problems.append(f"reconciliation {model_id}: reason required")
    return problems


def _flatten_refs(trim: Mapping) -> set[str]:
    refs = trim.get("source_refs")
    if not isinstance(refs, Mapping):
        return set()
    out: set[str] = set()
    for values in refs.values():
        if isinstance(values, str):
            values = [values]
        if isinstance(values, list):
            out.update(str(value).strip() for value in values if str(value).strip())
    return out


def release_reconciliation_report(
    release: Mapping,
    *,
    data_dir: Path | str = DATA_DIR,
    year: int = DEFAULT_YEAR,
) -> dict:
    """Prove source evidence is fully promoted or explicitly unresolved.

    Coverage is source-aware, not merely ``trim_count > 0``. If owner evidence
    listed five rows and only three owner-backed canonical rows exist, the two
    remaining rows stay visible and READY is not allowed to pass silently.
    """
    state = load_reconciliation_state(data_dir, year)
    model_ids = {
        str(row.get("canonical_id") or "")
        for row in release.get("models", []) if isinstance(row, Mapping)
    }
    trims_by_model: dict[str, list[Mapping]] = {}
    for trim in release.get("market_trims", []):
        if isinstance(trim, Mapping):
            trims_by_model.setdefault(str(trim.get("model_id") or ""), []).append(trim)

    rows: list[dict] = []
    blockers: list[dict] = []
    counts: dict[str, int] = {}
    for raw in state.get("models", []):
        model_id = str(raw.get("model_id") or "")
        declared = str(raw.get("status") or "")
        source_refs = {str(ref).strip() for ref in raw.get("source_refs") or [] if str(ref).strip()}
        source_count = int(raw.get("source_trim_count") or 0)
        canonical_rows = trims_by_model.get(model_id, [])
        source_backed = [trim for trim in canonical_rows if _flatten_refs(trim) & source_refs]
        promoted = len(source_backed)
        unresolved = max(source_count - promoted, 0)
        effective = "CANONICAL" if unresolved == 0 else declared
        row = {
            "model_id": model_id,
            "source_trim_count": source_count,
            "canonical_trim_count": len(canonical_rows),
            "canonical_source_trim_count": promoted,
            "unresolved_source_trim_count": unresolved,
            "declared_status": declared,
            "status": effective,
            "reason": raw.get("reason", ""),
            "source_refs": sorted(source_refs),
        }
        if model_id not in model_ids:
            row["blocker"] = "SOURCE_EVIDENCE_MODEL_NOT_IN_RELEASE"
            blockers.append(row)
        elif unresolved:
            try:
                status = TrimResolutionStatus(declared)
            except ValueError:
                status = None
            if status not in UNRESOLVED_EXEMPTIONS:
                row["blocker"] = "SOURCE_EVIDENCE_NOT_FULLY_PROMOTED"
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
    "UNRESOLVED_EXEMPTIONS",
    "ZERO_TRIM_EXEMPTIONS",
    "apply_canonical_trim_overlay",
    "canonical_trim_overlay_path",
    "generation_powertrain_mismatches",
    "load_canonical_trim_overlay",
    "load_reconciliation_state",
    "make_candidate",
    "powertrain_hints",
    "reconciliation_path",
    "release_reconciliation_report",
    "resolve_candidate_powertrain",
    "validate_reconciliation_state",
]
