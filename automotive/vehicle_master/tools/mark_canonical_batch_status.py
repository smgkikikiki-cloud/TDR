"""Move one canonical_input_batches row to a terminal review/reject status.

There is no dedicated "reject a batch" action anywhere in this codebase --
NEEDS_REVIEW and REJECTED are already-declared-valid values in the table's
own check constraint (supabase/migration_v22_unified_vehicle_input.sql),
referenced only as read-only filters elsewhere (lib/canonical-vehicle-create.ts,
lib/canonical-pending-overlay.ts), but nothing ever writes them. This is the
existing supported *mechanism* for every other status transition in the
system: `_patch()`, the same optimistic-concurrency PATCH
tools/canonical_input_worker.py already uses for pull()'s claim,
mark_staged(), mark_published(), and tools/requeue_canonical_result.py.
This script just points it at NEEDS_REVIEW/REJECTED instead.

Only status/updated_at/error are ever written. payload, payload_sha256,
batch_key, and every other column are left untouched -- this changes what
state the batch is in, never what it said.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from urllib.parse import quote
from urllib.request import Request, urlopen

from tools.canonical_input_worker import _env, _patch

_ALLOWED_TARGET_STATUSES = {"NEEDS_REVIEW", "REJECTED"}


def _current_row(batch_key: str) -> dict | None:
    url, key = _env()
    headers = {"apikey": key, "accept": "application/json"}
    if key.startswith("eyJ"):
        headers["authorization"] = f"Bearer {key}"
    request = Request(
        f"{url}/rest/v1/canonical_input_batches"
        f"?select=id,status&batch_key=eq.{quote(batch_key)}",
        headers=headers, method="GET",
    )
    with urlopen(request, timeout=60) as response:
        rows = json.loads(response.read().decode() or "[]")
    return rows[0] if rows else None


def mark(batch_key: str, status: str, reason: str) -> int:
    if status not in _ALLOWED_TARGET_STATUSES:
        raise SystemExit(f"status must be one of {sorted(_ALLOWED_TARGET_STATUSES)}")
    row = _current_row(batch_key)
    if row is None:
        raise SystemExit(f"no canonical_input_batches row for batch_key {batch_key!r}")
    current_status = str(row["status"])
    patched = _patch(str(row["id"]), current_status, {
        "status": status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "error": reason[:2000],
    })
    if not patched:
        raise SystemExit(
            f"row {row['id']} is no longer at status {current_status!r} -- "
            "another process changed it first; re-run to see its current state"
        )
    print(json.dumps({
        "batch_key": batch_key, "id": row["id"],
        "previous_status": current_status, "new_status": status,
    }, ensure_ascii=False))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-key", required=True)
    parser.add_argument("--status", required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args(argv)
    return mark(args.batch_key, args.status, args.reason)


if __name__ == "__main__":
    raise SystemExit(main())
