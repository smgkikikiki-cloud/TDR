"""Build every calibration output from the committed inputs and the archived Ice package. Offline; read-only on the repository inputs.

    cd automotive/vehicle_master && python -m identity_resolution.calibration.build            # writes the outputs next to this file
    python -m identity_resolution.calibration.build --check                                      # rebuild in memory, fail if a committed output differs

Outputs (all deterministic):
    r6_calibration_dataset.csv   one row per (Ice group, candidate) pair worth a look: legacy evidence, Contract v1 evidence, volumes, codes
    r6_calibration_groups.csv    one row per Ice group (1,200): legacy and v1 outcome, volumes, lineage
    r6_owner_review.csv          the owner-adjudication sheet: prioritised, machine evidence prefilled, owner columns BLANK
    calibration_summary.json     the numbers behind the report
    CALIBRATION_REPORT.md        the report
    DATA_DICTIONARY.md           the meaning of every column of the three CSVs
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from collections import defaultdict
from pathlib import Path

from . import adapters as A
from . import columns
from . import pairs as PR
from . import render_report, report as RP
from . import review as RV

OUT = A.CALIBRATION_DIR
SENSITIVITY = OUT / "sensitivity_results.json"

DATASET_COLUMNS_DROP = {"_legacy_group_status"}


def cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return repr(v)
    return str(v)


def csv_text(columns: list[str], rows: list[dict]) -> str:
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(columns)
    for r in rows:
        writer.writerow([cell(r.get(c)) for c in columns])
    return buf.getvalue()


def build(sensitivity_path: Path = SENSITIVITY) -> dict[str, str]:
    ice, ext = A.load_ice_package(), A.load_extracts()
    assembled = PR.assemble(ice, ext)
    if assembled["verification"]["mismatches"]:
        raise SystemExit(f"the legacy replay does not reproduce the stored rows: {assembled['verification']['mismatches'][:3]}")
    stored_by_group = defaultdict(list)
    for r in ext["crosswalk"]:
        stored_by_group[r["model_group_id"]].append(r)
    sheet = RV.build_sheet(assembled["pairs"], assembled["groups"], stored_by_group)
    sensitivity = json.loads(sensitivity_path.read_text(encoding="utf-8")) if sensitivity_path.exists() else None
    summary = RP.compute(assembled, sheet, sensitivity, ext, ice)

    pair_columns = [c for c in assembled["pairs"][0] if c not in DATASET_COLUMNS_DROP]
    group_columns = list(next(iter(assembled["groups"].values())))
    pairs_sorted = sorted(assembled["pairs"], key=lambda p: (p["model_group_id"], p["candidate_canonical_model_id"]))
    groups_sorted = [assembled["groups"][g] for g in sorted(assembled["groups"])]
    return {
        "r6_calibration_dataset.csv": csv_text(pair_columns, pairs_sorted),
        "r6_calibration_groups.csv": csv_text(group_columns, groups_sorted),
        "r6_owner_review.csv": csv_text(RV.SHEET_COLUMNS, sheet),
        "calibration_summary.json": json.dumps(summary, ensure_ascii=False, indent=1, sort_keys=False) + "\n",
        "CALIBRATION_REPORT.md": render_report.render(summary),
        "DATA_DICTIONARY.md": columns.render(),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="rebuild in memory and compare with the committed outputs")
    args = ap.parse_args(argv)
    outputs = build()
    if args.check:
        stale = [name for name, text in outputs.items() if not (OUT / name).exists() or (OUT / name).read_text(encoding="utf-8-sig") != text]
        if stale:
            print("stale outputs:", ", ".join(stale), file=sys.stderr)
            return 1
        print("calibration outputs are up to date")
        return 0
    for name, text in outputs.items():
        # utf-8-sig for the CSVs, like the legacy review sheet (Excel opens Thai names correctly)
        (OUT / name).write_text(text, encoding="utf-8-sig" if name.endswith(".csv") else "utf-8", newline="")
        print(f"wrote {name} ({len(text):,} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
