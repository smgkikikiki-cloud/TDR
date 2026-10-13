"""Pure matching engine for the Ice <-> TDR canonical model crosswalk (Market Track M3).

Everything here operates on in-memory values only -- no filesystem, no network, no
Supabase. ``tools/ice_crosswalk_match.py`` is the thin I/O/DB wrapper around this module,
exactly the same split as ``vehreg/ice_package.py`` / ``tools/ice_package_import.py`` in
M2. Keeping the scoring/classification rules here pure means they are fully testable with
synthetic fixtures, independent of whether a real Ice Full Package has ever been imported
(it has not -- see docs/WORK_STATE.md, M2 state).

Reference: docs/vehicle-db/VEHICLE_DB_V3.md §14.2, .claude/skills/tdr-package-import/
SKILL.md §3 (id_changes.csv).

UNVERIFIED ASSUMPTION, isolated here as in vehreg/ice_package.py: the exact brand strings
Ice uses for the required alias pairs (Deepal/Changan, "MG Maxus"/"MAXUS") have never been
observed in a real delivery. ``normalize_brand`` lowercases and trims before any alias
lookup so minor casing differences do not matter, but if Ice spells a brand differently
than the seed rows in migration_v63, only those seed rows need a new entry -- nothing in
this module's logic changes.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

#: Original automatic-match threshold. Identity owner rules may block or correct a
#: candidate before the original series/name scoring is applied.
SERIES_CORRELATION_THRESHOLD = 0.98
SERIES_RATIO_LOW = 0.9
SERIES_RATIO_HIGH = 1.1
NAME_AUTO_THRESHOLD = 0.8

#: Owner-confirmed makes where every model letter and digit is identity-significant.
IDENTITY_LOCK_BRANDS = frozenset({"audi", "bmw", "volvo", "lexus", "peugeot", "ferrari", "zeekr", "mazda", "mg"})

#: Fuzzy-name floor for review proposals only. It cannot produce an AUTO mapping.
#: Exact identity rules and owner designation locks are applied before this threshold.
NAME_CANDIDATE_FLOOR = 0.35

#: Discovery (§14.2 "Ice groups appearing for the first time and provisional groups").
PROVISIONAL_SUFFIX = "__provisional"
PROVISIONAL_MARKER = "|"


# ---------------------------------------------------------------------------
# Brand alias normalization (§14.2 "2. Brand alias")
# ---------------------------------------------------------------------------

def normalize_brand(brand: str, alias_map: dict[str, str]) -> str:
    """Return the comparison key for a brand: its alias_group if one is seeded
    (migration_v63.ice_brand_aliases), else its own lowercased/trimmed form.
    ``alias_map`` keys must already be lowercased/trimmed (as loaded by
    tools/ice_crosswalk_match.py); this never merges brands in Vehicle Master, it
    only decides whether two brand strings should be treated as the same brand for
    matching purposes.
    """
    key = " ".join(re.sub(r"[^0-9a-zA-Z฀-๿]+", " ", brand.strip().lower()).split())
    normalized_aliases = {
        " ".join(re.sub(r"[^0-9a-zA-Z฀-๿]+", " ", alias.strip().lower()).split()): target
        for alias, target in alias_map.items()
    }
    return normalized_aliases.get(key, key)


# ---------------------------------------------------------------------------
# Name similarity (candidate generation only)
# ---------------------------------------------------------------------------

_PUNCTUATION_RE = re.compile(r"[^0-9a-zA-Z฀-๿ ]+")


def normalize_model_name(name: str, brand: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace, and drop a leading brand
    prefix if present -- so "BMW 3 Series" and "3 Series" compare equal once brand is
    already accounted for by the alias/series signal."""
    cleaned = _PUNCTUATION_RE.sub(" ", name.strip().lower())
    cleaned = " ".join(cleaned.split())
    brand_token = " ".join(_PUNCTUATION_RE.sub(" ", brand.strip().lower()).split())
    if brand_token and cleaned.startswith(brand_token):
        cleaned = cleaned[len(brand_token):].strip()
    return cleaned


def strip_alias_brand_prefix(
    normalized_name: str, brand_alias_group: str, alias_map: dict[str, str],
) -> str:
    """Strip an alias-family marque when Ice embeds it in the model name."""
    for brand, alias_group in alias_map.items():
        if alias_group != brand_alias_group:
            continue
        prefix = " ".join(_PUNCTUATION_RE.sub(" ", brand.strip().lower()).split())
        if prefix and normalized_name.startswith(prefix + " "):
            return normalized_name[len(prefix):].strip()
    return normalized_name


def name_similarity(a: str, b: str) -> float:
    """Deterministic 0..1 similarity between two normalized names.
    Used to rank review candidates; it does not establish model identity."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


#: Explicit, owner-confirmed model-name aliases. Keys are normalized brand/alias groups;
#: never infer alias pairs from fuzzy similarity or registration totals.
MODEL_NAME_ALIASES: dict[str, dict[str, str]] = {
    "maxus_mifa": {"7": "mifa 7", "9": "mifa 9"},
    "bmw": {"2 series gran coupe": "2 series"},
    "jaecoo": {"j7": "7", "j5": "5 ev", "5 ev": "5 ev"},
    "toyota": {"hiace": "commuter"},
    "riddara": {"rd6 double cab": "rd6"},
    "wuling": {"binguo": "bingo"},
    "byd": {"sealion 6": "sealion 6 dm i"},
}

# An exact, owner-approved code-to-nameplate exception. It is deliberately narrower
# than the BMW identity lock: 525d is a 5 Series variant, but other BMW codes do not
# inherit a generic digit-prefix rule.
OWNER_APPROVED_NAMEPLATE_ALIASES: dict[tuple[str, str], str] = {
    ("bmw", "525d"): "5 series",
}

# Owner-confirmed aliases that cross brand labels. Keep these as exact pair entries;
# do not turn related marques (for example Chery/Omoda) into a generic brand merge.
CROSS_BRAND_MODEL_ALIASES = frozenset({
    frozenset({("chery", "c5 ev omoda e5"), ("omoda", "c5")}),
})


def apply_model_name_alias(normalized_name: str, brand_alias_group: str) -> str:
    """Map a known model-name alias onto its counterpart's normalized form, scoped to
    one brand alias_group. A name with no entry (including an already-aliased one,
    e.g. "mifa 7") passes through unchanged, so this is safe to call on both sides of
    a comparison unconditionally."""
    return MODEL_NAME_ALIASES.get(brand_alias_group, {}).get(normalized_name, normalized_name)


def apply_owner_nameplate_alias(normalized_name: str, brand_alias_group: str) -> str:
    """Apply an exact, explicitly approved code-to-nameplate identity exception."""
    return OWNER_APPROVED_NAMEPLATE_ALIASES.get(
        (brand_alias_group, normalized_name), normalized_name)


def owner_identity_separation(brand_alias_group: str, left_name: str, right_name: str) -> bool:
    """Protect known designation families from numeric/name-similarity merges."""
    left = " ".join(left_name.strip().lower().split())
    right = " ".join(right_name.strip().lower().split())
    if brand_alias_group == "honda":
        left_en2 = bool(re.search(r"\be\s*n\s*2\b", left))
        right_en2 = bool(re.search(r"\be\s*n\s*2\b", right))
        if left_en2 != right_en2:
            return True
    if brand_alias_group == "byd":
        left_code = re.search(r"\batto\s*([123])\b", left)
        right_code = re.search(r"\batto\s*([123])\b", right)
        if left_code and right_code and left_code.group(1) != right_code.group(1):
            return True
    if brand_alias_group == "gwm":
        for family in ("ora", "tank"):
            left_code = re.search(rf"\b{family}\s*(\d+)\b", left)
            right_code = re.search(rf"\b{family}\s*(\d+)\b", right)
            if left_code and right_code and left_code.group(1) != right_code.group(1):
                return True
    return brand_alias_group == "lotus" and {left, right} == {"emira", "emeya"}


def latin_letter_distance(a: str, b: str) -> int:
    """Levenshtein distance over Latin letters only, per the owner's rule."""
    left = re.sub(r"[^a-z]", "", a.lower())
    right = re.sub(r"[^a-z]", "", b.lower())
    previous = list(range(len(right) + 1))
    for i, char_a in enumerate(left, 1):
        current = [i]
        for j, char_b in enumerate(right, 1):
            current.append(min(
                current[-1] + 1,
                previous[j] + 1,
                previous[j - 1] + (char_a != char_b),
            ))
        previous = current
    return previous[-1]


def standalone_l_mismatch(a: str, b: str) -> bool:
    """A standalone L/l token is identity-significant across all brands."""
    has_l_a = bool(re.search(r"(?<![a-z0-9])l(?![a-z0-9])", a.lower()))
    has_l_b = bool(re.search(r"(?<![a-z0-9])l(?![a-z0-9])", b.lower()))
    return has_l_a != has_l_b


def is_explicit_cross_brand_alias(
    brand_a: str, name_a: str, brand_b: str, name_b: str,
) -> bool:
    """Return true only for an owner-recorded exact cross-brand alias pair."""
    return frozenset({(brand_a, name_a), (brand_b, name_b)}) in CROSS_BRAND_MODEL_ALIASES


# ---------------------------------------------------------------------------
# Monthly series comparison -- corroboration/data-quality diagnostics only
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SeriesEvaluation:
    correlation: float | None
    ratio: float | None
    strong: bool


def pearson_correlation(xs: list[float], ys: list[float]) -> float | None:
    """Standard Pearson correlation coefficient, stdlib only. None when undefined
    (fewer than 2 points, or either series has zero variance)."""
    n = len(xs)
    if n != len(ys) or n < 2:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x <= 0 or var_y <= 0:
        return None
    return cov / (var_x ** 0.5 * var_y ** 0.5)


def total_ratio(ice_series: list[float], legacy_series: list[float]) -> float | None:
    """legacy total / ice total -- None when the Ice total is zero (undefined ratio,
    never treated as a match)."""
    ice_total = sum(ice_series)
    if ice_total == 0:
        return None
    return sum(legacy_series) / ice_total


def build_paired_series(
    periods: list[str], ice_monthly: dict[str, float], legacy_monthly: dict[str, float],
) -> tuple[list[float], list[float]]:
    """Align two monthly dicts over an explicit, caller-supplied ordered period list
    (the last 24 months per §14.2) -- a period missing from either side is 0.0, not
    dropped, so a month Ice reports with zero registrations is not silently excluded
    from the correlation."""
    xs = [float(ice_monthly.get(p, 0.0)) for p in periods]
    ys = [float(legacy_monthly.get(p, 0.0)) for p in periods]
    return xs, ys


def sum_monthly_series(series_list: list[dict[str, float]]) -> dict[str, float]:
    """Sum several per-model monthly dicts into one combined series -- §14.2's "when
    evaluating an Ice group that already has multiple approved/AUTO TDR models, sum
    those TDR models consistently for the group": the legacy side of the comparison for
    a many-TDR-models-to-one-Ice-group candidate is the sum across every TDR model
    already actively mapped to that group plus the candidate under evaluation, not any
    single model's series alone."""
    combined: dict[str, float] = {}
    for series in series_list:
        for period, value in series.items():
            combined[period] = combined.get(period, 0.0) + value
    return combined


def evaluate_series(ice_series: list[float], legacy_series: list[float]) -> SeriesEvaluation:
    correlation = pearson_correlation(ice_series, legacy_series)
    ratio = total_ratio(ice_series, legacy_series)
    strong = (
        correlation is not None and correlation >= SERIES_CORRELATION_THRESHOLD
        and ratio is not None and SERIES_RATIO_LOW <= ratio <= SERIES_RATIO_HIGH
    )
    return SeriesEvaluation(correlation=correlation, ratio=ratio, strong=strong)


# ---------------------------------------------------------------------------
# Acceptance decision (§14.2 "Acceptance")
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MatchDecision:
    status: str  # APPROVED | AUTO | PROPOSED
    match_method: str  # ADMIN | SERIES | NAME
    #: Full evidence tuple for fingerprints and review. The original scorer uses
    #: series strength for SERIES decisions and name similarity for NAME decisions.
    correlation: float | None
    ratio: float | None
    name_score: float
    reason: str

    @property
    def primary_score(self) -> float | None:
        """The score column holds the original deciding signal."""
        return self.correlation if self.match_method == "SERIES" else self.name_score


def decide_match(*, series: SeriesEvaluation, name_score: float) -> MatchDecision | None:
    """Apply the original series/name acceptance scoring after identity-rule filters.

    Returns None for "no candidate" -- callers must not
    insert a crosswalk row for that case (see migration_v63's row-identity note);
    canonical_model_id simply stays absent rather than being written as an explicit
    null row, except for the one safety-net "no candidate" row shape the schema allows
    but this module never produces on its own."""
    if series.strong and name_score >= NAME_AUTO_THRESHOLD:
        return MatchDecision(
            status="AUTO", match_method="SERIES",
            correlation=series.correlation, ratio=series.ratio, name_score=name_score,
            reason=f"strong monthly series (corr={series.correlation:.4f}, ratio={series.ratio:.4f}) "
                   f"and name similarity {name_score:.2f} >= {NAME_AUTO_THRESHOLD}")
    if series.strong:
        return MatchDecision(
            status="PROPOSED", match_method="SERIES",
            correlation=series.correlation, ratio=series.ratio, name_score=name_score,
            reason=f"strong monthly series (corr={series.correlation:.4f}, ratio={series.ratio:.4f}) "
                   f"but name similarity {name_score:.2f} < {NAME_AUTO_THRESHOLD} -- needs review")
    if name_score >= NAME_CANDIDATE_FLOOR:
        return MatchDecision(
            status="PROPOSED", match_method="NAME",
            correlation=series.correlation, ratio=series.ratio, name_score=name_score,
            reason=f"name similarity {name_score:.2f} candidate but monthly series not strong "
                   f"(corr={series.correlation}, ratio={series.ratio}) -- needs review, name alone "
                   f"is never sufficient for AUTO")
    return None


#: Original signal priority. Correlation and lexical similarity are never compared as
#: raw numbers; rank status, method, then same-signal evidence.
_STATUS_RANK = {"APPROVED": 2, "AUTO": 1, "PROPOSED": 0}
_METHOD_RANK = {"ADMIN": 2, "SERIES": 1, "NAME": 0}


def decision_rank(decision: MatchDecision) -> tuple[int, int, float, float, float]:
    """Restore original strongest-first scoring; unlike units are never compared."""
    return (
        _STATUS_RANK[decision.status],
        _METHOD_RANK[decision.match_method],
        decision.correlation if decision.correlation is not None else -1.0,
        decision.ratio if decision.ratio is not None else -1.0,
        decision.name_score,
    )


def decision_fingerprint(
    *, model_group_id: str, canonical_model_id: str, correlation: float | None,
    ratio: float | None, name_score: float, master_version: str,
) -> str:
    """A stable hash of the inputs behind one decision. Used to tell "the underlying
    Ice identity/data actually changed" (SKILL.md: a REJECTED mapping must not be
    silently re-proposed otherwise) from a re-run producing the same inputs."""
    payload = json.dumps(
        {
            "model_group_id": model_group_id,
            "canonical_model_id": canonical_model_id,
            "correlation": None if correlation is None else round(correlation, 6),
            "ratio": None if ratio is None else round(ratio, 6),
            "name_score": round(name_score, 6),
            "master_version": master_version,
        },
        sort_keys=True, ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Calendar conversion -- Ice's period is Buddhist-calendar "YYYY-MM" text
# (migration_v62's comment on ice_reg_trend.period); the legacy `registrations` table
# (migration_v41) uses a real Gregorian SQL date. The Buddhist year is always the
# Gregorian year + 543 -- this is a fixed offset, not a lookup, and both directions are
# pure string/int arithmetic so the DB-wired orchestrator never needs its own copy.
# ---------------------------------------------------------------------------

_BUDDHIST_GREGORIAN_OFFSET = 543


def buddhist_period_to_gregorian_year_month(period: str) -> str:
    """"2569-08" -> "2026-08"."""
    year_str, month_str = period.split("-")
    return f"{int(year_str) - _BUDDHIST_GREGORIAN_OFFSET:04d}-{month_str}"


def gregorian_date_to_buddhist_period(date_str: str) -> str:
    """"2026-08-01" (or "2026-08") -> "2569-08"."""
    year_str, month_str = date_str.split("-")[:2]
    return f"{int(year_str) + _BUDDHIST_GREGORIAN_OFFSET:04d}-{month_str}"


# ---------------------------------------------------------------------------
# id_changes.csv (SKILL.md §3, VEHICLE_DB_V3.md §14.2 "5. id_changes handling")
# ---------------------------------------------------------------------------

ID_CHANGE_TYPES = ("เปลี่ยนรหัส", "รวม", "แยก")


@dataclass(frozen=True)
class IdChangeRow:
    old_model_group_id: str
    new_model_group_id: str
    reg_moved_all_periods: bool
    share_of_old_pct: float | None
    type: str


def parse_id_change_row(row: dict[str, str]) -> IdChangeRow:
    change_type = row["type"].strip()
    if change_type not in ID_CHANGE_TYPES:
        raise ValueError(f"unknown id_changes type: {change_type!r} (expected one of {ID_CHANGE_TYPES})")
    raw_moved = row.get("reg_moved_all_periods", "").strip().lower()
    share_raw = row.get("share_of_old_pct", "").strip()
    return IdChangeRow(
        old_model_group_id=row["old_model_group_id"].strip(),
        new_model_group_id=row["new_model_group_id"].strip(),
        reg_moved_all_periods=raw_moved in ("true", "1", "yes", "y"),
        share_of_old_pct=float(share_raw) if share_raw else None,
        type=change_type,
    )


# ---------------------------------------------------------------------------
# Discovery (§14.2 "Ongoing, on every Ice import")
# ---------------------------------------------------------------------------

def is_provisional_model_group(model_group_id: str) -> bool:
    return PROVISIONAL_MARKER in model_group_id or model_group_id.endswith(PROVISIONAL_SUFFIX)


def is_new_model_group(model_group_id: str, known_model_group_ids: set[str]) -> bool:
    return model_group_id not in known_model_group_ids


def discovery_flags(model_group_id: str, known_model_group_ids: set[str]) -> list[str]:
    flags = []
    if is_new_model_group(model_group_id, known_model_group_ids):
        flags.append("NEW")
    if is_provisional_model_group(model_group_id):
        flags.append("PROVISIONAL")
    return flags


# ---------------------------------------------------------------------------
# One-time review sheet (§14.2 "4. One-time review sheet")
# ---------------------------------------------------------------------------

REVIEW_SHEET_COLUMNS = (
    "model_group_id", "model_name", "brand",
    "proposed_canonical_model_id", "proposed_model_name",
    "series_correlation", "total_ratio", "name_similarity",
    "proposed_status", "match_method", "master_version", "reason",
)


def build_review_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deterministic ordering (by model_group_id, then proposed_canonical_model_id
    with None last) over already-decided non-AUTO candidates. Pure formatting only --
    callers must already have excluded AUTO/APPROVED rows (§14.2: "for each non-AUTO
    candidate"; "do not auto-approve PROPOSED rows")."""
    def sort_key(record: dict[str, Any]) -> tuple[str, str]:
        canonical = record.get("proposed_canonical_model_id")
        return (record["model_group_id"], canonical if canonical is not None else "￿")

    ordered = sorted(records, key=sort_key)
    return [{column: record.get(column) for column in REVIEW_SHEET_COLUMNS} for record in ordered]
