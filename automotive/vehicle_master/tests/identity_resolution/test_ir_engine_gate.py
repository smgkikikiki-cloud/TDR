"""Identity Resolution contract v1: there is deliberately no engine yet.

The day an `engine/` package is added, a corpus runner MUST be added with it (SPEC §14.3) — otherwise the golden corpus would stop
being a regression suite without anyone noticing. This test makes CI enforce that, and states the current position in its skip reason.
"""
from __future__ import annotations

from pathlib import Path

import re

import pytest

import ir_support as S

RUNNER = Path(__file__).with_name("test_ir_conformance_runner.py")
IMPORT = re.compile(r"^\s*(?:from|import)\s+identity_resolution\b", re.M)


def test_an_engine_requires_the_conformance_runner():
    if not (S.IR_ROOT / "engine").exists():
        pytest.skip("no engine yet: contract-only deliverable (identity_resolution/README.md, 'Migration path')")
    assert RUNNER.is_file(), "identity_resolution/engine exists but tests/identity_resolution/test_ir_conformance_runner.py does not: wire the golden corpus (SPEC §14.3)"


def test_legacy_matcher_is_untouched_by_this_contract():
    """The task: existing vehreg/ice_crosswalk.py and tools/ice_crosswalk_match.py remain functional compatibility facades."""
    root = S.IR_ROOT.parent
    for relative in ("vehreg/ice_crosswalk.py", "tools/ice_crosswalk_match.py"):
        source = (root / relative).read_text(encoding="utf-8")
        assert not IMPORT.search(source), f"{relative} must not import the draft subsystem yet"


def test_nothing_outside_the_subsystem_imports_it_yet():
    root = S.IR_ROOT.parent
    # (`vehreg/retail_lineup_*` has an unrelated *field* called identity_resolution; only imports count.)
    for directory in ("vehreg", "tools", "tdr_bridge", "pages"):
        for path in (root / directory).rglob("*.py"):
            assert not IMPORT.search(path.read_text(encoding="utf-8")), f"{path} wires the draft subsystem into production code"
