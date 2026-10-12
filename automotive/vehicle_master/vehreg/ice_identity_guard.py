"""Conservative Ice-to-TDR nameplate identity guards.

BLOCK forbids a candidate; REVIEW forbids automatic acceptance but preserves
a candidate for human review. Neither outcome creates a canonical model.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from vehreg import ice_crosswalk as crosswalk

CODE_SENSITIVE_BRANDS = frozenset({
    "audi", "bmw", "volvo", "lexus", "peugeot", "ferrari",
    "zeekr", "mazda", "mg",
})


@dataclass(frozen=True)
class IdentityGuard:
    disposition: str  # ALLOW | BLOCK | REVIEW
    reason: str


def _nameplate(name: str, brand: str, alias_group: str) -> str:
    normalized = crosswalk.normalize_model_name(name, brand)
    return crosswalk.apply_model_name_alias(normalized, alias_group)


def _latin_letters(name: str) -> str:
    return "".join(re.findall(r"[a-z]", name))


def latin_letter_distance(left: str, right: str) -> int:
    """Levenshtein edits over Latin letters only, ignoring numbers/separators."""
    a, b = _latin_letters(left), _latin_letters(right)
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, 1):
        row = [i]
        for j, char_b in enumerate(b, 1):
            row.append(min(row[-1] + 1, previous[j] + 1,
                           previous[j - 1] + (char_a != char_b)))
        previous = row
    return previous[-1]


def _code_signature(name: str) -> tuple[str, ...]:
    """Model-code tokens after brand removal; intentionally not fuzzy."""
    return tuple(re.findall(r"[a-z0-9]+", name))


def check_pair(
    *, ice_name: str, ice_brand: str, canonical_name: str,
    canonical_brand: str, alias_group: str,
) -> IdentityGuard:
    """Apply owner rules in precedence order (L, Latin edits, brand codes)."""
    ice = _nameplate(ice_name, ice_brand, alias_group)
    canonical = _nameplate(canonical_name, canonical_brand, alias_group)
    if ("l" in ice.split()) != ("l" in canonical.split()):
        return IdentityGuard("BLOCK", "isolated L/l identity split")
    edits = latin_letter_distance(ice, canonical)
    if edits > 3:
        return IdentityGuard("BLOCK", f"Latin-letter nameplate edit distance {edits} > 3")
    if crosswalk.normalize_brand(ice_brand, {}) in CODE_SENSITIVE_BRANDS or (
        crosswalk.normalize_brand(canonical_brand, {}) in CODE_SENSITIVE_BRANDS
    ):
        if _code_signature(ice) != _code_signature(canonical):
            return IdentityGuard("REVIEW", "sensitive-brand model-code token mismatch")
    return IdentityGuard("ALLOW", "nameplate identity guards passed")
