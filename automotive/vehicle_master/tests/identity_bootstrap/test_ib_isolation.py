"""Scope guards: this milestone is contract, corpus and tests only."""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import ib_support as S

PKG = S.IB_ROOT
VM = PKG.parent
REPO = VM.parents[1]
FORBIDDEN_IMPORT_ROOTS = {"vehreg", "tools", "supabase", "requests", "httpx", "psycopg", "psycopg2", "urllib3", "identity_resolution", "tdr_bridge", "streamlit", "socket"}


def py_files(root: Path):
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


def test_the_package_imports_nothing_from_the_engine_database_network_or_identity_resolution():
    for path in py_files(PKG):
        for name in imports(path):
            assert name.split(".")[0] not in FORBIDDEN_IMPORT_ROOTS, f"{path.relative_to(VM)} imports {name}"


def test_the_engine_exists_only_with_its_conformance_runner_and_stays_offline():
    assert (VM / "tests" / "identity_bootstrap" / "test_ib_engine_conformance.py").exists(), "an engine needs a corpus conformance runner"
    names = {p.name for p in PKG.iterdir()}
    assert names <= {"__init__.py", "README.md", "INTEGRATION.md", "contract", "engine", "providers", "shadow", "__pycache__"}, names
    assert {p.name for p in (PKG / "engine").iterdir()} - {"__pycache__"} == {"__init__.py", "allocate.py", "decide.py", "fingerprint.py", "lexical.py", "lineage.py", "plan.py"}
    for path in py_files(PKG / "engine") + py_files(PKG / "providers"):
        text = path.read_text(encoding="utf-8")
        for needle in ("open(", "Path(", "requests", "subprocess", "os.environ", "datetime", "time.time", "random", "uuid"):
            assert needle not in text, f"{path.name}: the engine and adapters are pure (no I/O, clock or randomness): {needle}"


def test_no_production_wiring_or_persistence_was_added():
    banned = ("supabase", "create_client", "psycopg", "execute_sql", "apply_migration", "rpc(")
    for path in py_files(PKG):
        text = path.read_text(encoding="utf-8")
        for needle in banned:
            assert needle not in text, f"{path.relative_to(VM)} mentions {needle}"
    assert not (PKG / "shadow" / "persist.py").exists()


def test_nothing_in_production_imports_the_package():
    skip = {PKG, VM / "tests" / "identity_bootstrap"}
    pattern = re.compile(r"^\s*(?:from|import)\s+identity_bootstrap\b", re.M)
    offenders = []
    for root in (VM,):
        for path in py_files(root):
            if any(s in path.parents for s in skip):
                continue
            if pattern.search(path.read_text(encoding="utf-8", errors="ignore")):
                offenders.append(str(path.relative_to(REPO)))
    for ext in ("ts", "tsx"):
        for path in list((REPO / "lib").rglob(f"*.{ext}")) + list((REPO / "app").rglob(f"*.{ext}")):
            if "identity_bootstrap" in path.read_text(encoding="utf-8", errors="ignore"):
                offenders.append(str(path.relative_to(REPO)))
    assert offenders == []


def test_no_migration_workflow_or_serving_view_was_added():
    for path in (REPO / "supabase").glob("*.sql"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert "vehicle_identity_aliases" not in text and "vehicle_identity_provenance" not in text and "identity_state" not in text, path.name
    for path in (REPO / ".github" / "workflows").glob("*.yml"):
        assert "identity_bootstrap" not in path.read_text(encoding="utf-8", errors="ignore"), f"{path.name}: no workflow may run this subsystem yet"


def test_identity_resolution_is_not_modified_or_imported_by_this_package():
    # PR #200 is a read-only reference. This package must neither import it nor ship a copy of its files.
    assert not (PKG / "identity_resolution").exists()
    assert "identity_resolution" not in "".join(p.read_text(encoding="utf-8") for p in py_files(PKG))


def test_no_production_data_in_the_corpus():
    text = (S.CONTRACT_DIR / "cases.jsonl").read_text(encoding="utf-8")
    for needle in ("ltvwzkffmpudpjfjomrg", "service_role", "eyJ"):
        assert needle not in text


def test_the_oracle_lives_only_under_tests():
    assert (VM / "tests" / "identity_bootstrap" / "ib_reference.py").exists()
    assert not list(PKG.rglob("ib_reference.py"))
