#!/usr/bin/env python3
"""Registry -> `canonical_object_map` reconciliation and sync — Phase 1 completion.

    python tools/sync_external_identity_registry.py                # dry run (default)
    python tools/sync_external_identity_registry.py --apply         # apply safe mutations, then reread and prove convergence

Steps performed, always in this order:

    1. validate the Git registry offline (schema + invariants; fails closed,
       refuses to reconcile against an invalid registry)
    2. read live `canonical_object_map`, and read live existence of each
       registry binding's legacy source row (models/brands/model_powertrains/trims)
    3. reconcile (pure logic, tdr_bridge.external_identity_sync) and print
       proposed mutations
    4. (only with --apply) apply the safe mutations -- pure INSERTs of rows
       that step 3 confirmed are absent; nothing else is ever written
    5. (only with --apply) reread live state and reconcile again, to prove
       convergence -- exits nonzero if anything still needs attention

Dry-run (no --apply) performs zero writes -- it is safe to run at any time,
including in a read-only credential context, and never mutates anything.

Safety boundary: this tool can only ever INSERT a `canonical_object_map` row
for a key the Git registry actually contains, and only when that row does
not already exist. It never UPDATEs an existing row (a conflict with Git is
reported, never overwritten), never touches a row whose key is outside the
registry (review-state rows, Phase-E projection-owned rows, operational-only
verified rows of unknown origin, retired-operational-only rows), and never
imports anything from `canonical_object_map` back into the Git registry.

Requires the same server-side credentials as every other Supabase-reading
tool in this repository: SUPABASE_URL (or NEXT_PUBLIC_SUPABASE_URL) plus
SUPABASE_SECRET_KEY (or legacy SUPABASE_SERVICE_ROLE_KEY). Without them this
tool fails closed and performs no read or write at all.

Exit 0: fully reconciled (every registry binding in_sync, no blockers).
Exit 1: something needs attention -- a blocker (conflict / missing source
row), or (dry-run only) a pending safe mutation not yet applied.
Exit 2: could not run at all (no credentials, invalid registry, request failure).
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vehreg.catalog import Catalog, DATA_DIR, DEFAULT_YEAR, CatalogError  # noqa: E402
from tdr_bridge.external_identity_registry import (  # noqa: E402
    DEFAULT_REGISTRY_PATH,
    RegistryError,
    load_registry,
    validate_registry,
)
from tdr_bridge.external_identity_sync import (  # noqa: E402
    EXTERNAL_ENTITY_TYPE_TO_SOURCE_TABLE,
    OperationalRow,
    ReconciliationReport,
    reconcile,
)


# --------------------------------------------------------------------------- Supabase REST
# Same minimal urllib-based PostgREST client pattern as
# tools/canonical_input_worker.py -- no new dependency.

def _strip_wrapper_quotes(value: str) -> str:
    cleaned = value.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
        return cleaned[1:-1].strip()
    return cleaned


def _clean_env_value(value: str | None, *names: str) -> str:
    cleaned = _strip_wrapper_quotes(value or "")
    if "=" in cleaned:
        prefix, remainder = cleaned.split("=", 1)
        if prefix.strip() in names:
            cleaned = remainder.strip()
    return _strip_wrapper_quotes(cleaned)


class CredentialsError(RuntimeError):
    pass


def _env() -> tuple[str, str]:
    url = _clean_env_value(
        os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL"),
        "SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL",
    )
    key = _clean_env_value(
        os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
        "SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY",
    )
    if not url or not key:
        raise CredentialsError(
            "SUPABASE_URL (or NEXT_PUBLIC_SUPABASE_URL) and SUPABASE_SECRET_KEY "
            "(or SUPABASE_SERVICE_ROLE_KEY) are required"
        )
    return url.rstrip("/"), key


def _request(method: str, path: str, payload=None, *, prefer: str | None = None):
    url, key = _env()
    headers = {"apikey": key, "accept": "application/json"}
    if key.startswith("eyJ"):
        headers["authorization"] = f"Bearer {key}"
    body = None
    if payload is not None:
        headers["content-type"] = "application/json"
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    if prefer:
        headers["prefer"] = prefer
    request = Request(f"{url}/rest/v1/{path}", data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=60) as response:
            content = response.read().decode()
    except HTTPError as exc:
        content = exc.read().decode(errors="replace")
        raise RuntimeError(f"Supabase request failed ({exc.code}) for {method} {path}: {content[:1000]}") from exc
    return json.loads(content) if content else None


def fetch_operational_rows() -> list[OperationalRow]:
    rows = _request(
        "GET",
        "canonical_object_map?select=source_table,source_id,canonical_entity_type,canonical_id,"
        "status,verified_by,verified_at,match_basis,notes",
    ) or []
    return [
        OperationalRow(
            source_table=row["source_table"],
            source_id=row["source_id"],
            canonical_entity_type=row["canonical_entity_type"],
            canonical_id=row.get("canonical_id"),
            status=row["status"],
            verified_by=row.get("verified_by"),
            verified_at=row.get("verified_at"),
            match_basis=row.get("match_basis") or {},
            notes=row.get("notes"),
        )
        for row in rows
    ]


def fetch_source_row_exists(source_table: str, source_id: str) -> bool:
    rows = _request("GET", f"{quote(source_table)}?id=eq.{quote(source_id)}&select=id&limit=1")
    return bool(rows)


def insert_operational_row(payload: dict) -> None:
    # Deliberately POST (plain insert), never an upsert/on-conflict -- if the
    # row somehow already exists by write time (a race with something else),
    # this must fail loudly rather than silently overwrite it.
    _request("POST", "canonical_object_map", payload, prefer="return=minimal")


# --------------------------------------------------------------------------- reporting

def _print_report(report: ReconciliationReport, *, label: str) -> None:
    summary = report.summary()
    print(f"\n{label}", file=sys.stderr)
    print(f"  bindings: {summary['bindings_total']}", file=sys.stderr)
    for classification, count in summary["bindings_by_classification"].items():
        print(f"    {classification}: {count}", file=sys.stderr)
    print(f"  operational-only rows: {summary['operational_only_total']}", file=sys.stderr)
    for classification, count in summary["operational_only_by_classification"].items():
        print(f"    {classification}: {count}", file=sys.stderr)
    print(f"  proposed mutations: {summary['proposed_mutations']}", file=sys.stderr)
    if report.has_blockers:
        print("  BLOCKERS PRESENT -- see per-binding detail below; nothing here is auto-resolved.", file=sys.stderr)
        for r in report.binding_results:
            if r.classification in ("canonical_target_conflict", "operational_status_conflict", "missing_external_source_row"):
                print(f"    - {r.key}: {r.classification}: {r.detail}", file=sys.stderr)
    if report.proposed_mutations:
        print("  proposed (not yet applied unless --apply was given):", file=sys.stderr)
        for m in report.proposed_mutations:
            print(f"    - INSERT canonical_object_map {m.key} -> status={m.payload['status']!r}", file=sys.stderr)


def _report_to_json(report: ReconciliationReport) -> dict:
    return {
        "summary": report.summary(),
        "bindings": [
            {
                "key": list(r.key),
                "classification": r.classification,
                "desired_status": r.desired_status,
                "detail": r.detail,
            }
            for r in report.binding_results
        ],
        "operational_only": [
            {"key": list(r.row.key), "classification": r.classification}
            for r in report.operational_only
        ],
        "proposed_mutations": [
            {"key": list(m.key), "payload": m.payload} for m in report.proposed_mutations
        ],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR)
    parser.add_argument("--apply", action="store_true", help="apply safe mutations (default: dry run only)")
    parser.add_argument("--json-out", type=Path, default=None, help="also write the final JSON report to this path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    try:
        doc = load_registry(args.registry)
    except RegistryError as exc:
        print(f"registry sync: REGISTRY INVALID (structural): {exc}", file=sys.stderr)
        return 2

    try:
        catalog = Catalog.load(args.data_dir, args.year)
    except CatalogError as exc:
        print(f"registry sync: cannot load canonical catalog: {exc}", file=sys.stderr)
        return 2

    problems = validate_registry(doc, catalog)
    if problems:
        print(f"registry sync: REGISTRY INVALID ({len(problems)} problem(s)) -- refusing to reconcile:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 2

    try:
        operational_rows = fetch_operational_rows()
        source_row_exists = {}
        for binding in doc.bindings:
            source_table = EXTERNAL_ENTITY_TYPE_TO_SOURCE_TABLE.get(binding.external_entity_type)
            if source_table is None:
                continue
            source_row_exists[(source_table, binding.external_id)] = fetch_source_row_exists(
                source_table, binding.external_id,
            )
    except CredentialsError as exc:
        print(f"registry sync: no server-side Supabase credentials found ({exc}). "
              "Nothing was read. Exiting without a report.", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"registry sync: live read failed: {exc}", file=sys.stderr)
        return 2

    report = reconcile(doc, operational_rows, source_row_exists)
    _print_report(report, label="dry-run reconciliation" if not args.apply else "reconciliation (pre-apply)")

    final_report = report
    if args.apply:
        if not report.proposed_mutations:
            print("\n--apply: nothing to do (no safe mutations pending).", file=sys.stderr)
        else:
            print(f"\n--apply: applying {len(report.proposed_mutations)} safe mutation(s)...", file=sys.stderr)
            for mutation in report.proposed_mutations:
                try:
                    insert_operational_row(mutation.payload)
                    print(f"  applied: {mutation.key}", file=sys.stderr)
                except RuntimeError as exc:
                    print(f"  FAILED to apply {mutation.key}: {exc}", file=sys.stderr)
                    print("  Stopping -- not attempting further mutations this run.", file=sys.stderr)
                    return 2

        # Reread and prove convergence.
        try:
            operational_rows_after = fetch_operational_rows()
        except RuntimeError as exc:
            print(f"registry sync: re-read after apply failed: {exc}", file=sys.stderr)
            return 2
        final_report = reconcile(doc, operational_rows_after, source_row_exists)
        _print_report(final_report, label="reconciliation (post-apply, proving convergence)")

    if args.json_out:
        args.json_out.write_text(json.dumps(_report_to_json(final_report), indent=2, sort_keys=True), encoding="utf-8")
        print(f"\nwrote JSON report to {args.json_out}", file=sys.stderr)
    else:
        print(json.dumps(_report_to_json(final_report), indent=2, sort_keys=True))

    if final_report.is_fully_reconciled:
        print("\nOK — fully reconciled.", file=sys.stderr)
        return 0
    if final_report.has_blockers:
        print("\nBLOCKERS remain — see above. Nothing was overwritten automatically.", file=sys.stderr)
        return 1
    print("\nPending mutations exist. Rerun with --apply to create the missing rows.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
