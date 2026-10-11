"""Calibration adapters: turn the committed read-only extracts and the archived Ice package into a Contract v1 snapshot.

This is the *reference* adapter for calibration only (SPEC section 3.1, obligations A1-A12). It is not a production adapter: it has no
database access, it reads two things that are already in the repository (the archived Ice package and `calibration/inputs/`), and it
never writes anything. The two capability declarations it depends on (`ice`, `tdr_registrations`) are read from
`provider_capabilities.yaml`; both are UNKNOWN / unconfirmed today, so an absent row is written as `null` (never 0) and listed in
`absent_rows.months` (invariant I4a).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from collections import defaultdict
from pathlib import Path

from identity_resolution.contract import loader

CALIBRATION_DIR = Path(__file__).resolve().parent
INPUTS_DIR = CALIBRATION_DIR / "inputs"
REPO_ROOT = CALIBRATION_DIR.parents[3]

PACKAGE_RELATIVE = "data/packages/2569-09/v3_M7.0/TDR_FULL_2569-09_v3_M7.0.zip"
PACKAGE_SHA256 = "c558d2d4cc3ed667f8b30ea028dbb66c4030cdce4e7daabe735df870cb94677d"
PROVIDER = "ice"
ICE_SOURCE = "ice"
TDR_SOURCE = "tdr_registrations"

_EVENT_TYPE = {"เปลี่ยนรหัส": "RENAME", "รวม": "MERGE", "แยก": "SPLIT"}


def b2g(period: str) -> str:
    """Buddhist-era 'YYYY-MM' -> Gregorian 'YYYY-MM' (A1: converted exactly once, here)."""
    year, month = period.split("-")
    return f"{int(year) - 543:04d}-{month}"


def pidx(period: str) -> int:
    year, month = period.split("-")
    return int(year) * 12 + int(month) - 1


def pstr(index: int) -> str:
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def month_range(first: str, last: str) -> list[str]:
    return [pstr(i) for i in range(pidx(first), pidx(last) + 1)]


# ----------------------------------------------------------------------------------------------------------------- inputs
def read_json(name: str):
    return json.loads((INPUTS_DIR / name).read_text(encoding="utf-8"))


def load_extracts() -> dict:
    """The committed read-only extracts of the production tables (see inputs/MANIFEST.json for provenance)."""
    return {
        "crosswalk": read_json("r6_crosswalk_rows.json"),
        "redirects": read_json("r6_redirects.json"),
        "brand_aliases": read_json("ice_brand_aliases.json"),
        "brands": read_json("tdr_brands.json"),
        "models": read_json("tdr_models.json"),
        "generations": read_json("tdr_generations.json"),
        "tdr_series": read_json("tdr_registrations_series.json"),
        "tdr_period_totals": read_json("tdr_period_totals.json"),
        "meta": read_json("extract_meta.json"),
    }


def load_ice_package(path: Path | None = None) -> dict:
    """Read the archived M7.0 package (the one live since R5). Verifies the sha256 before reading anything from it."""
    path = Path(path) if path else REPO_ROOT / PACKAGE_RELATIVE
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != PACKAGE_SHA256:
        raise ValueError(f"{path} sha256 {digest} is not the archived M7.0 package ({PACKAGE_SHA256})")
    outer = zipfile.ZipFile(io.BytesIO(raw))

    def panel(prefix: str) -> zipfile.ZipFile:
        names = [n for n in outer.namelist() if n.startswith(f"panels/{prefix}_") and n.endswith(".zip")]
        if len(names) != 1:
            raise ValueError(f"expected exactly one panel zip for {prefix}, found {names}")
        return zipfile.ZipFile(io.BytesIO(outer.read(names[0])))

    def rows(archive: zipfile.ZipFile, member: str):
        return csv.DictReader(io.TextIOWrapper(io.BytesIO(archive.read(member)), encoding="utf-8-sig", newline=""))

    trend, dims = panel("reg_trend"), panel("dims")
    manifest = json.loads(trend.read("manifest.json"))
    cells: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    brands_observed: dict[str, set[str]] = defaultdict(set)
    n_rows = 0
    for r in rows(trend, "data/reg_trend.csv"):
        n_rows += 1
        cells[r["model_group_id"]][r["period"]] += float(r["reg_count"])
        brands_observed[r["model_group_id"]].add(r["brand"])
    groups = list(rows(dims, "dims/model_group.csv"))
    id_changes = list(csv.DictReader(io.TextIOWrapper(io.BytesIO(outer.read("id_changes.csv")), encoding="utf-8-sig", newline="")))
    return {
        "sha256": digest,
        "bytes": len(raw),
        "trend_rows": n_rows,
        "coverage_buddhist": {"from": manifest["period_from"], "to": manifest["period_to"]},
        "trend_manifest_md5": manifest["files"]["data/reg_trend.csv"]["md5"],
        "groups": groups,
        "cells": {g: dict(p) for g, p in cells.items()},
        "brands_observed": {g: sorted(b) for g, b in brands_observed.items()},
        "id_changes": id_changes,
    }


# ------------------------------------------------------------------------------------------------------------- the snapshot
def capability(source: str) -> dict:
    cap = loader.load_capabilities()["sources"][source]["series.absent_row"]
    return {"source": source, "semantics": cap["value"], "confirmed": cap["status"] == "confirmed"}


def identity_status(model_group_id: str) -> str:
    """A4: Ice id forms -> identity_status. 'BRAND|MODEL' = unmapped_name, '...__provisional' = provisional."""
    if "|" in model_group_id:
        return "unmapped_name"
    if model_group_id.endswith("__provisional"):
        return "provisional"
    return "settled"


def _dense(by_month: dict[str, float | None], months: list[str], cap: dict) -> dict:
    """A2: dense series over the declared coverage. An absent in-coverage month is null unless the capability is a CONFIRMED ABSENT_IS_ZERO."""
    zero_ok = cap["semantics"] == "ABSENT_IS_ZERO" and cap["confirmed"]
    counts, absent = [], []
    for m in months:
        v = by_month.get(m)
        if v is None:
            absent.append(m)
            counts.append(0 if zero_ok else None)
        else:
            counts.append(int(v) if float(v).is_integer() else float(v))
    return {"start": months[0], "counts": counts, "coverage_declared": True,
            "absent_rows": {"source": cap["source"], "semantics": cap["semantics"], "confirmed": cap["confirmed"], "months": absent}}


def build_subjects(ice: dict) -> list[dict]:
    cov = ice["coverage_buddhist"]
    months = month_range(b2g(cov["from"]), b2g(cov["to"]))
    cap = capability(ICE_SOURCE)
    subjects = []
    for g in sorted(ice["groups"], key=lambda r: r["model_group_id"]):
        gid = g["model_group_id"]
        by_month = {b2g(p): v for p, v in ice["cells"].get(gid, {}).items()}
        subject = {
            "entity_kind": "model_group",
            "entity_id": gid,
            "display_name": g["model_name"],
            "brand": g["brand"],
            "brands_observed": ice["brands_observed"].get(gid, []),
            "identity_status": identity_status(gid),
            "attributes": {"body": g["body"].strip() or None},
        }
        if by_month:
            subject["series"] = _dense(by_month, months, cap)
        subjects.append(subject)
    return subjects


def build_targets(ext: dict) -> list[dict]:
    brand_name = {b["canonical_id"]: b["name_en"] for b in ext["brands"]}
    gens = defaultdict(list)
    for g in ext["generations"]:
        if g["deleted"]:
            continue
        gens[g["model_id"]].append({"id": g["canonical_id"],
                                    "launched": g["launched"][:7] if g["launched"] else None,
                                    "ended": g["ended"][:7] if g["ended"] else None})
    ts = ext["tdr_series"]
    months = month_range(ts["start"], ts["end"])
    cap = capability(TDR_SOURCE)
    targets = []
    for m in sorted(ext["models"], key=lambda r: r["canonical_id"]):
        cid = m["canonical_id"]
        target = {
            "target_kind": "tdr_model",
            "target_id": cid,
            "brand": brand_name.get(m["brand_id"], ""),
            "display_name": m["name_en"],
            "status": m["status"],
            "deleted": bool(m["deleted"]),
            "body_type": m["body_type"],
            "generations": sorted(gens.get(cid, []), key=lambda g: g["id"]),
        }
        cells = ts["rows"].get(cid)
        if cells is not None:
            by_month = {mo: float(v) for mo, v in zip(months, cells.split(",")) if v != ""}
            target["series"] = _dense(by_month, months, cap)
        targets.append(target)
    return targets


def build_lineage(ice: dict, ext: dict) -> dict:
    events = []
    for r in ice["id_changes"]:
        share = r["share_of_old_pct"].strip()
        events.append({"event_type": _EVENT_TYPE[r["type"].strip()], "old_id": r["old_model_group_id"].strip(),
                       "new_id": r["new_model_group_id"].strip(), "share_of_old_pct": float(share) if share else None})
    # R6 phase 1 recorded the RENAME/MERGE redirects in ice_model_group_redirects; those events are already applied.
    applied = sorted(f"{_EVENT_TYPE[r['change_type']]}:{r['old_model_group_id']}>{r['new_model_group_id']}" for r in ext["redirects"])
    return {"source_present": True, "declared_identity_change": True, "events": events, "applied_event_keys": applied}


def build_snapshot(ice: dict, ext: dict) -> dict:
    pol = loader.load_policy()
    return {
        "contract_version": "v1",
        "policy_version": pol["policy"]["version"],
        "provider": PROVIDER,
        "source_version": {"label": "ice:2569-09:v3:M7.0", "attributes": {"period": "2569-09", "package_version": "3", "master_version": "7.0"}},
        "as_of_period": b2g(ice["coverage_buddhist"]["to"]),
        "subjects": build_subjects(ice),
        "targets": build_targets(ext),
        "existing_mappings": [],   # a fresh evaluation: what Contract v1 says with no stored state, not what the writer would do to the R6 rows
        "lineage": build_lineage(ice, ext),
    }
