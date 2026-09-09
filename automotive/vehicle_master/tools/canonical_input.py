"""Apply one validated Vehicle Master input batch from JSON."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from vehreg.catalog import DATA_DIR
from vehreg.input_pipeline import CanonicalInputError, CanonicalInputPipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batch", type=Path)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.batch.read_text(encoding="utf-8"))
        result = CanonicalInputPipeline(args.data_dir).apply(payload)
    except (OSError, json.JSONDecodeError, CanonicalInputError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": True, **asdict(result)}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
