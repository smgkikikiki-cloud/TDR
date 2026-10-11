"""Shared, cached loaders for the identity-resolution contract tests (no fixtures: this directory deliberately has no conftest)."""
from __future__ import annotations

import functools
from pathlib import Path

from identity_resolution.contract import loader, render

IR_ROOT = Path(__file__).resolve().parents[2] / "identity_resolution"
CONTRACT_DIR = IR_ROOT / "contract" / "v1"

OUTCOMES = ["AUTO", "PROPOSE", "AMBIGUOUS", "STRUCTURAL_REVIEW", "NO_CANDIDATE", "INSUFFICIENT_DATA", "PROTECTED_HOLD", "SUPPRESSED"]
OPERATIONS = ["REDIRECT", "MOVE_MAPPINGS", "FLAG_MAPPING_REVIEW", "QUARANTINE", "CANDIDATE_HINT", "NOOP", "ERROR"]
WRITE_ACTIONS = ["INSERT_AUTO", "INSERT_PROPOSED", "PROMOTE_TO_AUTO", "REFRESH_EVIDENCE", "DEMOTE_TO_PROPOSED", "MARK_STALE",
                 "BLOCK_REPORT", "SUPPRESS", "REOPEN_AS_PROPOSED", "KEEP", "NOOP"]
NAME_RELATIONS = ["EQUAL", "EQUAL_VIA_MODEL_ALIAS", "EQUAL_VIA_TOKEN_EQUIV", "FUZZY", "SUBJECT_COARSER", "SUBJECT_FINER", "SIBLING", "CONTRADICTION", "UNAVAILABLE"]
BRAND_RELATIONS = ["EXACT", "ALIAS_SAME", "ALIAS_RELABEL", "ALIAS_RELATED", "MISMATCH", "UNKNOWN"]
PAIR_STATES = ["NONE", "PROPOSED", "AUTO", "APPROVED", "LOCKED", "REJECTED"]
RANK_TIERS = ["auto_eligible", "series_state", "lifecycle_relation", "name_relation", "abs_ln_ratio_ascending", "correlation_descending"]
LINK_TYPES = ["EQUIVALENT", "PART_OF", "COMPOSED_OF"]
ABSENT_SEMANTICS = ["ABSENT_IS_ZERO", "ABSENT_IS_UNOBSERVED", "UNKNOWN"]


@functools.lru_cache(maxsize=None)
def policy() -> dict:
    return loader.load_policy()


@functools.lru_cache(maxsize=None)
def capabilities() -> dict:
    return loader.load_capabilities()


@functools.lru_cache(maxsize=None)
def adoption() -> dict:
    return loader.load_adoption()


@functools.lru_cache(maxsize=None)
def registry() -> dict:
    return loader.load_reason_codes()


@functools.lru_cache(maxsize=None)
def taxonomy() -> dict:
    return loader.load_taxonomy()


@functools.lru_cache(maxsize=None)
def schemas() -> dict:
    return loader.load_schema_registry()


@functools.lru_cache(maxsize=None)
def cases() -> list:
    return loader.load_cases()


def codes() -> dict:
    return registry()["codes"]


def spec_text() -> str:
    return (CONTRACT_DIR / "SPEC.md").read_text(encoding="utf-8")


def prose_outside_generated(text: str) -> str:
    """SPEC.md with the generated appendix blocks removed (so prose checks do not trivially pass on generated tables)."""
    return render._BLOCK.sub("", text)


def asserted_codes(node) -> set[str]:
    """Every reason code a case asserts as present: `include` lists, `primary_code`, and refusal codes."""
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "include" and isinstance(value, list):
                found.update(value)
            elif key in ("primary_code", "code") and isinstance(value, str):
                found.add(value)
            else:
                found |= asserted_codes(value)
    elif isinstance(node, list):
        for item in node:
            found |= asserted_codes(item)
    return found


def referenced_codes(node) -> set[str]:
    """Every reason code a case mentions anywhere in its expectation (including `exclude`)."""
    found = asserted_codes(node)
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "exclude" and isinstance(value, list):
                found.update(value)
            elif isinstance(value, (dict, list)):
                found |= referenced_codes(value)
    elif isinstance(node, list):
        for item in node:
            found |= referenced_codes(item)
    return found
