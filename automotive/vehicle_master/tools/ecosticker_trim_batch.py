#!/usr/bin/env python3
"""Export HUMAN-reviewed ECO Sticker MarketTrim decisions as canonical input.

This tool never applies the batch.  Feed the emitted JSON into the existing
canonical-input workflow/worker so staging validation, revision audit and PR
review stay identical to every other Vehicle Master write.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from vehreg.catalog import DATA_DIR, DEFAULT_YEAR
from vehreg.ecosticker_promote import (
    ECOTrimPromotionError,
    build_market_trim_input_batch,
    write_market_trim_input_batch,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Export HUMAN-approved ECO trim identities to CanonicalInputBatch JSON")
    parser.add_argument("review", help="human promotion review JSON")
    parser.add_argument("--snapshot-date", required=True, help="immutable ECO snapshot date YYYY-MM-DD")
    parser.add_argument("--data-dir", default=str(DATA_DIR))
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR)
    parser.add_argument("--out", help="write batch JSON here; omit to print only")
    args = parser.parse_args(argv)

    try:
        if args.out:
            batch = write_market_trim_input_batch(
                args.review, args.out, data_dir=args.data_dir, year=args.year,
                snapshot_date=args.snapshot_date)
        else:
            batch = build_market_trim_input_batch(
                args.review, data_dir=args.data_dir, year=args.year,
                snapshot_date=args.snapshot_date)
    except ECOTrimPromotionError as exc:
        parser.error(str(exc))
    print(json.dumps(batch, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
