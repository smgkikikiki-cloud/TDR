"""Generate or compile a Retail Lineup Bootstrap workbook.

Examples:
    python -m tools.retail_lineup_bootstrap_workbook generate \
      --model-id toyota.camry --model-id honda.accord \
      --base-release-id vehicle-2026-... --out lineup.xlsx

    python -m tools.retail_lineup_bootstrap_workbook compile lineup.xlsx

Chunk 3 is compile-only: there is intentionally no apply command here.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from vehreg.catalog import DATA_DIR, DEFAULT_YEAR
from vehreg.retail_lineup_workbook import (
    compile_retail_lineup_workbook,
    generate_retail_lineup_workbook,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    generate = sub.add_parser("generate", help="export the three-sheet owner workbook")
    generate.add_argument("--model-id", action="append", required=True, dest="model_ids")
    generate.add_argument("--base-release-id", required=True)
    generate.add_argument("--out", type=Path, required=True)
    generate.add_argument("--year", type=int, default=DEFAULT_YEAR)
    generate.add_argument("--data-dir", type=Path, default=DATA_DIR)
    generate.add_argument("--generated-at")
    generate.add_argument("--as-of")

    compile_parser = sub.add_parser("compile", help="validate workbook and emit immutable plan")
    compile_parser.add_argument("file", type=Path)
    compile_parser.add_argument("--year", type=int)
    compile_parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    compile_parser.add_argument("--report", type=Path)

    args = parser.parse_args(argv)
    if args.command == "generate":
        result = generate_retail_lineup_workbook(
            args.out,
            model_ids=args.model_ids,
            base_release_id=args.base_release_id,
            data_dir=args.data_dir,
            year=args.year,
            generated_at=args.generated_at,
            as_of=args.as_of,
        )
    else:
        result = compile_retail_lineup_workbook(
            args.file,
            data_dir=args.data_dir,
            expected_year=args.year,
        ).as_dict()
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
