"""Read a pinned Ice Full Package without extracting it to disk. Verifies the pinned SHA-256 and each used panel's md5 before trusting a byte."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from pathlib import Path

PINNED = {"file": "TDR_FULL_2569-09_v3_M7.0.zip", "sha256": "c558d2d4cc3ed667f8b30ea028dbb66c4030cdce4e7daabe735df870cb94677d",
          "source_label": "ice:2569-09:v3:M7.0", "period": "2569-09"}
PANELS = {"dims": "panels/dims_2569-09_v3.zip", "reg_trend": "panels/reg_trend_2569-09_v3.zip"}


class PackageError(RuntimeError):
    pass


def _csv(data: bytes) -> list[dict]:
    return list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))


def load(path: Path) -> dict:
    raw = Path(path).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != PINNED["sha256"]:
        raise PackageError(f"package sha256 {digest} is not the pinned {PINNED['sha256']}")
    outer = zipfile.ZipFile(io.BytesIO(raw))
    index = json.loads(outer.read("full_package.json"))
    if index.get("status") != "พร้อมส่ง":
        raise PackageError("package status is not พร้อมส่ง")
    panels = {}
    for name, member in PANELS.items():
        blob = outer.read(member)
        panels[name] = zipfile.ZipFile(io.BytesIO(blob))
        md5 = hashlib.md5(blob).hexdigest()
        declared = next((v for v in index.get("panels", {}).values() if v.get("file") == Path(member).name), None)
        if declared is None or declared.get("md5") != md5:
            raise PackageError(f"{member}: md5 {md5} does not match the package index ({declared})")
    dims = _csv(panels["dims"].read("dims/model_group.csv"))
    id_changes = _csv(outer.read("id_changes.csv"))
    first, last, total, recent = {}, {}, {}, {}
    trend = _csv(panels["reg_trend"].read("data/reg_trend.csv"))
    periods = sorted({r["period"] for r in trend})
    newest = periods[-1]
    last12 = set(periods[-12:])
    for r in trend:
        gid, p, n = r["model_group_id"], r["period"], float(r["reg_count"])
        if gid not in first or p < first[gid]:
            first[gid] = p
        if gid not in last or p > last[gid]:
            last[gid] = p
        total[gid] = total.get(gid, 0.0) + n
        if p in last12:
            recent[gid] = recent.get(gid, 0.0) + n
    return {"sha256": digest, "dims": dims, "id_changes": id_changes, "first_seen": first, "last_seen": last, "trend_total": total,
            "last12": recent, "periods": (periods[0], newest), "index": {k: v for k, v in index.items() if k != "panels"}}
