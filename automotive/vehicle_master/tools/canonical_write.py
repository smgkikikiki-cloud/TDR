"""Apply one canonical Vehicle Master write command from JSON.

This is the operational entrypoint for Phase C.  It deliberately writes only
to the canonical file-backed Vehicle Master.  Supabase command rows are a
server-side intake/shadow queue; a worker may export one of those rows into the
same command contract, but this tool never edits TDR serving tables directly.

Examples::

    python tools/canonical_write.py command.json
    python tools/canonical_write.py command.json --data-dir /path/to/vehreg/data

Exit 0 means the command was validated and applied (or was an idempotent replay).
Exit 2 means the canonical writer rejected it and no revision was committed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from vehreg.canonical_write import (
    CanonicalWriteError,
    CanonicalWritePipeline,
)
from vehreg.catalog import DATA_DIR


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Apply one validated/revisioned canonical vehicle command",
    )
    parser.add_argument("command", type=Path, help="JSON command file")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DATA_DIR,
        help="Vehicle Master data root (default: vehreg/data)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        payload = json.loads(args.command.read_text(encoding="utf-8"))
        result = CanonicalWritePipeline(args.data_dir).apply(payload)
    except (OSError, json.JSONDecodeError, CanonicalWriteError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2

    print(json.dumps({
        "ok": True,
        "command_id": result.command_id,
        "revision_id": result.revision_id,
        "topic": result.topic,
        "entity_type": result.entity_type,
        "entity_id": result.entity_id,
        "changed_files": list(result.changed_files),
        "idempotent_replay": result.idempotent_replay,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
