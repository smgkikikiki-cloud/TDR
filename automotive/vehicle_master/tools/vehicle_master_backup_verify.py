"""Load and verify a Vehicle Master backup (Phase 0 step 6).

    python -m tools.vehicle_master_backup_verify path/to/vehicle-master-*.json.gz
    python -m tools.vehicle_master_backup_verify path/to/file.json.gz --expect-sha256 <hex>

Read-only: decompresses the file, recomputes the payload checksum the same
way ``tools.vehicle_master_backup`` computed it, and checks the format tag,
format version, the table allowlist, and that every table's declared
``row_counts`` entry matches the number of rows actually present. It never
writes to local disk or to any database -- a full automated production
restore is out of scope for Phase 0 step 6 (see VEHICLE_DB_V3.md §2.6); this
is the dry-run checker that proves a backup is structurally loadable and
internally consistent.

Exit status 1 when the backup fails any check.
"""
from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

from tools.vehicle_master_backup import FORMAT_NAME, FORMAT_VERSION, TABLES, canonical_json_bytes, sha256_hex


class BackupVerificationError(RuntimeError):
    pass


def load_backup(raw: bytes) -> dict:
    try:
        text = gzip.decompress(raw)
    except OSError:
        text = raw  # allow an uncompressed .json for local testing
    return json.loads(text.decode("utf-8"))


def verify(export: dict) -> list[str]:
    """Return a list of problems; an empty list means the backup is valid."""
    problems: list[str] = []

    if export.get("format") != FORMAT_NAME:
        problems.append(f"format: expected {FORMAT_NAME!r}, got {export.get('format')!r}")
    if export.get("format_version") != FORMAT_VERSION:
        problems.append(
            f"format_version: expected {FORMAT_VERSION!r}, got {export.get('format_version')!r}")

    payload = export.get("payload")
    if not isinstance(payload, dict):
        problems.append("payload is missing or not an object")
        return problems

    checksum = export.get("checksum") or {}
    if checksum.get("algorithm") != "sha256":
        problems.append(f"checksum algorithm: expected 'sha256', got {checksum.get('algorithm')!r}")
    else:
        actual = sha256_hex(canonical_json_bytes(payload))
        if actual != checksum.get("value"):
            problems.append(f"checksum mismatch: manifest says {checksum.get('value')!r}, computed {actual!r}")

    expected_tables = list(TABLES.keys())
    tables = payload.get("tables")
    if tables != expected_tables:
        problems.append(f"table list mismatch: expected {expected_tables!r}, got {tables!r}")

    row_counts = payload.get("row_counts") or {}
    data = payload.get("data") or {}
    for name in expected_tables:
        actual_len = len(data.get(name) or [])
        declared = row_counts.get(name)
        if declared != actual_len:
            problems.append(f"row_counts[{name!r}] = {declared!r} but data has {actual_len} row(s)")

    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument(
        "--expect-sha256",
        help="also check the compressed file's own sha256 (the backup run's 'gzip_sha256')")
    args = parser.parse_args(argv)

    raw = args.path.read_bytes()
    if args.expect_sha256:
        actual = sha256_hex(raw)
        if actual.lower() != args.expect_sha256.lower():
            print(f"INVALID: file sha256 mismatch: expected {args.expect_sha256}, got {actual}")
            return 1

    export = load_backup(raw)
    problems = verify(export)
    if problems:
        for problem in problems:
            print(f"INVALID: {problem}")
        return 1

    payload = export["payload"]
    print(json.dumps({
        "valid": True,
        "format": export["format"],
        "format_version": export["format_version"],
        "exported_at": export["exported_at"],
        "tables": payload["tables"],
        "row_counts": payload["row_counts"],
        "checksum": export["checksum"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
