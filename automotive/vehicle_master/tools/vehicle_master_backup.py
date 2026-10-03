"""Daily backup of the Vehicle DB v3 master tables (Phase 0 step 6).

    python -m tools.vehicle_master_backup --out /tmp/vehicle-master.json.gz   # dry run, local copy only
    python -m tools.vehicle_master_backup --apply                            # upload to Storage

Read-only against every ``vehicle_*`` table: this module only ever issues
``GET`` requests through PostgREST. It builds one deterministic, canonical
JSON document (§ below), gzips it, and -- only with ``--apply``, and only
after the whole export and its checksum have been built successfully --
uploads it to the private ``vehicle-master-backups`` Storage bucket
(migration_v61) at an immutable, timestamped path. It never writes to any
table, never touches ``current_*`` serving, ``registrations*``, the legacy
uuid ``models``/``trims``, registration aliases, or any closed legacy
input-queue/release RPC (Phase 0 step 5).

Backup shape::

    {
      "format": "tdr-vehicle-master-backup",
      "format_version": 1,
      "exported_at": "YYYY-MM-DDTHH:MM:SSZ",
      "checksum": {"algorithm": "sha256", "value": "<hex>"},
      "payload": {
        "vehicle_master_seed": {...} | null,   # the single vehicle_master_state row
        "tables": ["vehicle_master_state", "vehicle_brands", ...],
        "row_counts": {"vehicle_brands": 62, ...},
        "data": {"vehicle_brands": [...], ...}  # rows sorted by primary key
      }
    }

``checksum.value`` is the sha256 of the canonical JSON (UTF-8, sorted keys,
compact separators) of ``payload`` alone -- never of the envelope that
contains the checksum itself. ``tools.vehicle_master_backup_verify``
recomputes it the same way.

Storage object path (immutable, never overwritten -- ``x-upsert: false``)::

    vehicle-master/YYYY-MM-DD/vehicle-master-<UTC timestamp>.json.gz

``canonical_write_revisions`` is deliberately not included: Phase 0 only
ever wrote legacy file/release-path revisions to it, and the legacy write
path is closed (migration_v60). It carries no Vehicle Master mutation
history yet -- Phase 1 reuses it as the master change log, at which point a
later step should reconsider including it.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from tools.canonical_input_worker import _clean_env_value, _env, _request

BUCKET = "vehicle-master-backups"
FORMAT_NAME = "tdr-vehicle-master-backup"
FORMAT_VERSION = 1
PAGE_SIZE = 1000

#: Explicit allowlist (Phase 0 step 2, migration_v57). Order is the FK/build
#: order and also the order the backup lists and serializes tables in.
#: Deliberately excludes vehicle_master_seed_runs (seed-process bookkeeping,
#: not state needed to reconstruct the catalog) and every registration_*/
#: legacy uuid models/trims table (out of scope, never to be added here).
TABLES: dict[str, tuple[str, ...]] = {
    "vehicle_master_state": ("scope",),
    "vehicle_brands": ("canonical_id",),
    "vehicle_models": ("canonical_id",),
    "vehicle_generations": ("canonical_id",),
    "vehicle_variants": ("canonical_id",),
    "vehicle_trims": ("canonical_id",),
    "vehicle_facts": ("fact_id",),
    "vehicle_price_ledger": ("record_id",),
    "vehicle_campaigns": ("campaign_id",),
    "vehicle_promotions": ("campaign_id", "option_id"),
    "vehicle_eco_evidence": ("trim_id",),
    "vehicle_current_retail_sets": ("model_id",),
    "vehicle_trim_lifecycle_decisions": ("trim_id",),
    "vehicle_model_operational_states": ("model_id",),
    "vehicle_legacy_identities": (
        "namespace", "external_entity_type", "external_id", "canonical_entity_type"),
}

RestCall = Callable[..., Any]
StorageUpload = Callable[[str, bytes], None]
NowFn = Callable[[], datetime]


class VehicleMasterBackupError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Deterministic serialization
# ---------------------------------------------------------------------------

def canonical_json_bytes(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sort_key(value: Any) -> tuple:
    if value is None:
        return (0, "")
    if isinstance(value, (list, dict)):
        return (1, json.dumps(value, sort_keys=True, ensure_ascii=False))
    return (1, str(value))


def sort_rows(rows: list[dict], pk_cols: tuple[str, ...]) -> list[dict]:
    """Stable sort by the table's own primary key, independent of fetch order."""
    return sorted(rows, key=lambda row: tuple(_sort_key(row.get(col)) for col in pk_cols))


# ---------------------------------------------------------------------------
# Read-only fetch
# ---------------------------------------------------------------------------

def fetch_table(
    name: str,
    pk_cols: tuple[str, ...],
    *,
    rest: RestCall = _request,
    page_size: int = PAGE_SIZE,
) -> list[dict]:
    """Every row of one table, GET-only, paged under PostgREST's row cap."""
    order = ",".join(f"{col}.asc" for col in pk_cols)
    rows: list[dict] = []
    offset = 0
    while True:
        page = rest("GET", f"{name}?select=*&order={order}&limit={page_size}&offset={offset}")
        page = page or []
        if not isinstance(page, list):
            raise VehicleMasterBackupError(f"unexpected response fetching {name}: {page!r}")
        rows.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
    return sort_rows(rows, pk_cols)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def build_export(*, rest: RestCall = _request, now: NowFn = _utcnow) -> dict:
    """Fetch every allowlisted table and assemble the canonical backup document."""
    exported_at = now()
    data: dict[str, list[dict]] = {}
    for name, pk_cols in TABLES.items():
        data[name] = fetch_table(name, pk_cols, rest=rest)

    seed_rows = data.get("vehicle_master_state") or []
    vehicle_master_seed = seed_rows[0] if seed_rows else None

    payload = {
        "vehicle_master_seed": vehicle_master_seed,
        "tables": list(TABLES.keys()),
        "row_counts": {name: len(rows) for name, rows in data.items()},
        "data": data,
    }
    checksum = sha256_hex(canonical_json_bytes(payload))
    return {
        "format": FORMAT_NAME,
        "format_version": FORMAT_VERSION,
        "exported_at": exported_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "checksum": {"algorithm": "sha256", "value": checksum},
        "payload": payload,
    }


def backup_object_path(exported_at: datetime) -> str:
    date_dir = exported_at.strftime("%Y-%m-%d")
    timestamp = exported_at.strftime("%Y%m%dT%H%M%SZ")
    return f"vehicle-master/{date_dir}/vehicle-master-{timestamp}.json.gz"


# ---------------------------------------------------------------------------
# Storage upload
# ---------------------------------------------------------------------------

def _storage_upload(path: str, content: bytes, *, bucket: str = BUCKET) -> None:
    url, api_key = _env()
    # Same dual-credential handling as tools/retail_lineup_workbook_export_worker.py:
    # the legacy service-role JWT belongs in Authorization; the newer sb_secret_*
    # key is a privileged apikey and must not be copied into a Bearer header.
    legacy_jwt = _clean_env_value(
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY"), "SUPABASE_SERVICE_ROLE_KEY")
    headers = {
        "apikey": api_key,
        "content-type": "application/gzip",
        "x-upsert": "false",  # the path is immutable; never overwrite a prior backup
    }
    if legacy_jwt.startswith("eyJ"):
        headers["authorization"] = f"Bearer {legacy_jwt}"
    elif api_key.startswith("eyJ"):
        headers["authorization"] = f"Bearer {api_key}"

    encoded = quote(path.strip("/"), safe="/")
    request = Request(
        f"{url}/storage/v1/object/{bucket}/{encoded}", data=content, method="POST", headers=headers)
    try:
        with urlopen(request, timeout=120) as response:
            if response.status not in (200, 201):
                raise VehicleMasterBackupError(f"storage upload returned HTTP {response.status}")
    except HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise VehicleMasterBackupError(f"storage upload failed ({exc.code}): {body[:500]}") from exc


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run(
    *,
    apply: bool,
    out: Path | None = None,
    rest: RestCall = _request,
    upload: StorageUpload | None = None,
    now: NowFn = _utcnow,
) -> dict:
    """Build the full export, then (only on success) write/upload it.

    Nothing is written anywhere until the export, its canonical JSON and its
    checksum have all been produced without error -- a partial or failed
    export never reaches local disk or Storage.
    """
    export = build_export(rest=rest, now=now)
    exported_at = datetime.strptime(export["exported_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc)
    body = canonical_json_bytes(export)
    compressed = gzip.compress(body, mtime=0)
    object_path = backup_object_path(exported_at)

    summary = {
        "format": export["format"],
        "format_version": export["format_version"],
        "exported_at": export["exported_at"],
        "checksum": export["checksum"],
        "tables": export["payload"]["tables"],
        "row_counts": export["payload"]["row_counts"],
        "object_path": object_path,
        "gzip_sha256": sha256_hex(compressed),
        "bytes": len(compressed),
        "uploaded": False,
    }

    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(compressed)
        summary["local_path"] = str(out)

    if apply:
        (upload or _storage_upload)(object_path, compressed)
        summary["uploaded"] = True

    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="upload to the private vehicle-master-backups bucket (default: dry run, no upload)")
    parser.add_argument(
        "--out", type=Path, default=None,
        help="also write the compressed backup to this local path")
    args = parser.parse_args(argv)
    # Never print row data/credentials -- only the manifest-shaped summary.
    summary = run(apply=args.apply, out=args.out)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
