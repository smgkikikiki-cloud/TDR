"""Put applied canonical batches back in QUEUED when pre-commit validation fails.

The worker mutates only its checkout until the commit step. If validation fails
before that commit, a PROCESSING batch has not reached durable canonical source
state yet and must be retried from the active main tree. Leaving it PROCESSING
would otherwise make the ordinary sweeper wait for stale-processing recovery.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from tools.canonical_input_worker import _patch


def requeue(result_file: Path, reason: str) -> int:
    payload = json.loads(result_file.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc).isoformat()
    count = 0
    for row in payload.get("applied", []):
        row_id = str(row.get("id") or "").strip()
        if not row_id:
            continue
        patched = _patch(row_id, "PROCESSING", {
            "status": "QUEUED",
            "processing_started_at": None,
            "updated_at": now,
            "error": reason[:2000],
        })
        count += len(patched)
    print(json.dumps({"requeued_batches": count, "reason": reason[:2000]}, ensure_ascii=False))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result-file", type=Path, required=True)
    parser.add_argument("--reason", default="pre-commit validation failed; queued for retry")
    args = parser.parse_args(argv)
    return requeue(args.result_file, args.reason)


if __name__ == "__main__":
    raise SystemExit(main())
