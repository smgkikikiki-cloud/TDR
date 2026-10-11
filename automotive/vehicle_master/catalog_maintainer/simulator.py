"""Fixture-only simulation and stable report writers."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .planner import plan

CSV_FIELDS = ["job_key", "model_id", "work_kind", "eligibility", "tier", "score",
              "reason_codes", "generation_ids", "field_groups", "document_bundle_key", "status"]


def simulate(fixture_path: str | Path, output_dir: str | Path, *, budget: int | None = None) -> dict:
    root = Path(__file__).parent
    fixture = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
    policy = json.loads((root / "contract" / "policy.yaml").read_text(encoding="utf-8"))
    result = plan(fixture, policy, budget=budget)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "queue.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        for row in result["queue"]:
            writer.writerow({k: json.dumps(row[k], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                             if isinstance(row[k], (list, dict)) else row[k] for k in CSV_FIELDS})
    with (out / "decisions.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for row in result["decisions"]:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    (out / "summary.json").write_text(json.dumps(result["summary"], ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result
