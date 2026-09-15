#!/usr/bin/env python3
"""Offline validation for the Git-backed external-identity registry.

    python tools/validate_external_identity_registry.py
    python tools/validate_external_identity_registry.py --registry path/to/file.json --year 2026

Loads `integration_data/external_identity_registry.json` (or an explicit
--registry path), validates its schema and every invariant in
`tdr_bridge.external_identity_registry.validate_registry`, prints a
deterministic counts summary, and exits nonzero on any violation.

Requires no Supabase credentials, no network access, and no write of any
kind — this only reads the registry file and the local canonical catalog on
disk. The registry itself is year-independent (a pinned decision does not
expire), but offline canonical-target validation is checked against one
catalog year — by default `vehreg.catalog.DEFAULT_YEAR` — since canonical
IDs are stable and never recycled (see docs/vehicle-platform/INVARIANTS.md
rule 5), so a target valid in the current year is the practical, available
check; pass --year to check against a different one.

Exit 0: registry is structurally and semantically valid.
Exit 1: a structural (malformed file) or semantic (invariant) problem exists.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vehreg.catalog import Catalog, DATA_DIR, DEFAULT_YEAR, CatalogError  # noqa: E402
from tdr_bridge.external_identity_registry import (  # noqa: E402
    DEFAULT_REGISTRY_PATH,
    RegistryError,
    load_registry,
    summarize,
    validate_registry,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH,
                         help="registry JSON path (default: integration_data/external_identity_registry.json)")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR,
                         help="Vehicle Master data root (default: vehreg/data)")
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR,
                         help=f"catalog year to validate canonical targets against (default: {DEFAULT_YEAR})")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    try:
        doc = load_registry(args.registry)
    except RegistryError as exc:
        print(f"REGISTRY INVALID (structural): {exc}", file=sys.stderr)
        return 1

    try:
        catalog = Catalog.load(args.data_dir, args.year)
    except CatalogError as exc:
        print(f"cannot load canonical catalog for validation: {exc}", file=sys.stderr)
        return 1

    problems = validate_registry(doc, catalog)
    if problems:
        print(f"REGISTRY INVALID ({len(problems)} problem(s)):", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    summary = summarize(doc)
    print(f"schema_version: {summary['schema_version']}")
    print(f"bindings: {summary['bindings']}")
    print(f"active: {summary['active']}")
    print(f"retired: {summary['retired']}")
    print("namespaces:")
    for namespace, count in summary["namespaces"].items():
        print(f"  {namespace}: {count}")
    print("authority_basis:")
    for basis, count in summary["authority_basis"].items():
        print(f"  {basis}: {count}")
    print(f"\nOK — registry valid against catalog year {args.year}, no invariant violations.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
