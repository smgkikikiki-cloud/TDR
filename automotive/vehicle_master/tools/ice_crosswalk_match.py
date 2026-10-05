"""Wire the pure matcher (vehreg/ice_crosswalk.py) to real data for Market Track M3.

    python -m tools.ice_crosswalk_match --match --master-version M5 \\
        --review-csv data/packages/crosswalk_review_M5.csv
    python -m tools.ice_crosswalk_match --process-id-changes id_changes.csv \\
        --master-version M5

No real Ice Full Package has been imported yet (docs/WORK_STATE.md, M2 state) -- the
``ice_reg_trend``/``ice_dims_model_group`` tables this module reads are empty in
production, so ``--match`` run for real would currently write nothing (every group
would be "no candidate"). This module exists as package-independent infrastructure and
is exercised in tests with synthetic fixtures (``tests/test_ice_crosswalk_match.py``);
it must not be run against production until a real package has been imported, and even
then only the owner's explicit go starts seeding real mappings.

``--match``:
1. Fetches every Ice model group (``ice_dims_model_group``), its monthly ``reg_trend``
   series, the legacy ``registrations`` monthly series for every TDR canonical model
   (joined via ``registrations.canonical_model_id``), the brand-alias table, and every
   existing crosswalk row.
2. For each Ice group, evaluates every brand-matching TDR canonical model as a
   candidate (skipping one already actively (AUTO/APPROVED) mapped to a *different*
   group), picks the strongest decision via ``vehreg.ice_crosswalk.decide_match``, and
   writes it with ``ice_crosswalk_upsert_match`` -- never touching a row the RPC itself
   protects (APPROVED, or ``match_method = 'ADMIN'``), and never silently re-proposing a
   REJECTED row whose ``decision_fingerprint`` has not changed.
3. Updates the discovery ledger (``ice_known_model_groups``) and writes the one-time
   review sheet (every PROPOSED decision from this run) to ``--review-csv``.

``--process-id-changes PATH`` reads an Ice ``id_changes.csv`` (SKILL.md §3) and calls
``ice_crosswalk_apply_id_change`` once per row.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path
from typing import Any, Callable

from tools.canonical_input_worker import _request
from vehreg import ice_crosswalk as xwalk

RestCall = Callable[..., Any]

#: Last N months considered for the series fingerprint (§14.2 "last 24 monthly totals").
SERIES_WINDOW_MONTHS = 24

PAGE_SIZE = 1000


def _fetch_all(rest: RestCall, path: str) -> list[dict]:
    """GET every row of `path`, paginating with limit/offset -- PostgREST's own page
    cap must never silently truncate a production fetch."""
    rows: list[dict] = []
    offset = 0
    separator = "&" if "?" in path else "?"
    while True:
        page = rest("GET", f"{path}{separator}limit={PAGE_SIZE}&offset={offset}")
        if not page:
            break
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return rows


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def fetch_ice_groups(rest: RestCall) -> list[dict]:
    return _fetch_all(rest, "ice_dims_model_group?select=model_group_id,model_name,brand")


def fetch_ice_monthly_series(rest: RestCall) -> dict[str, dict[str, float]]:
    """model_group_id -> {period: total reg_count across every province/reg_type/brand row}."""
    rows = _fetch_all(rest, "ice_reg_trend?select=model_group_id,period,reg_count")
    series: dict[str, dict[str, float]] = {}
    for row in rows:
        by_period = series.setdefault(row["model_group_id"], {})
        by_period[row["period"]] = by_period.get(row["period"], 0.0) + float(row["reg_count"])
    return series


def fetch_legacy_monthly_series(rest: RestCall) -> dict[str, dict[str, float]]:
    """canonical_model_id -> {buddhist period: total registrations}."""
    rows = _fetch_all(
        rest, "registrations?select=period,registrations,canonical_model_id&canonical_model_id=not.is.null")
    series: dict[str, dict[str, float]] = {}
    for row in rows:
        period = xwalk.gregorian_date_to_buddhist_period(row["period"])
        by_period = series.setdefault(row["canonical_model_id"], {})
        by_period[period] = by_period.get(period, 0.0) + float(row["registrations"])
    return series


def fetch_vehicle_models(rest: RestCall) -> dict[str, dict[str, str]]:
    rows = _fetch_all(rest, "vehicle_models?select=canonical_id,name_en,brand_id")
    return {row["canonical_id"]: row for row in rows}


def fetch_vehicle_brands(rest: RestCall) -> dict[str, str]:
    rows = _fetch_all(rest, "vehicle_brands?select=canonical_id,name_en")
    return {row["canonical_id"]: row["name_en"] for row in rows}


def fetch_brand_aliases(rest: RestCall) -> dict[str, str]:
    rows = _fetch_all(rest, "ice_brand_aliases?select=brand,alias_group")
    return {" ".join(row["brand"].strip().lower().split()): row["alias_group"] for row in rows}


def fetch_existing_crosswalk(rest: RestCall) -> dict[tuple[str, str | None], dict]:
    rows = _fetch_all(rest, "ice_model_crosswalk?select=*")
    return {(row["model_group_id"], row["canonical_model_id"]): row for row in rows}


def fetch_known_model_group_ids(rest: RestCall) -> set[str]:
    rows = _fetch_all(rest, "ice_known_model_groups?select=model_group_id")
    return {row["model_group_id"] for row in rows}


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def _recent_periods(ice_series: dict[str, float], window: int = SERIES_WINDOW_MONTHS) -> list[str]:
    return sorted(ice_series)[-window:]


def _actively_mapped_canonical_ids(
    existing: dict[tuple[str, str | None], dict], model_group_id: str,
) -> list[str]:
    return [
        canonical_id for (group, canonical_id), row in existing.items()
        if group == model_group_id and canonical_id is not None and row["status"] in ("AUTO", "APPROVED")
    ]


def _canonical_actively_mapped_elsewhere(
    existing: dict[tuple[str, str | None], dict], canonical_model_id: str, model_group_id: str,
) -> bool:
    return any(
        group != model_group_id and canonical_id == canonical_model_id and row["status"] in ("AUTO", "APPROVED")
        for (group, canonical_id), row in existing.items()
    )


def match_one_group(
    *, group: dict, ice_series: dict[str, float], legacy_series_by_canonical: dict[str, dict[str, float]],
    vehicle_models: dict[str, dict[str, str]], vehicle_brands: dict[str, str],
    alias_map: dict[str, str], existing: dict[tuple[str, str | None], dict],
) -> tuple[str, xwalk.MatchDecision] | None:
    """Evaluate every brand-matching TDR canonical model against one Ice group and
    return (canonical_model_id, decision) for the strongest candidate, or None if no
    candidate clears even the PROPOSED floor. Pure given its already-fetched inputs --
    no DB access here; only the fetch_* functions above touch the network."""
    model_group_id = group["model_group_id"]
    group_brand_key = xwalk.normalize_brand(group["brand"], alias_map)
    periods = _recent_periods(ice_series)
    already_mapped = _actively_mapped_canonical_ids(existing, model_group_id)
    already_mapped_series = [legacy_series_by_canonical.get(cid, {}) for cid in already_mapped]

    best: tuple[str, xwalk.MatchDecision] | None = None
    for canonical_id, model in vehicle_models.items():
        candidate_brand = vehicle_brands.get(model["brand_id"], "")
        if xwalk.normalize_brand(candidate_brand, alias_map) != group_brand_key:
            continue
        if canonical_id in already_mapped:
            continue
        if _canonical_actively_mapped_elsewhere(existing, canonical_id, model_group_id):
            continue

        legacy_combined = xwalk.sum_monthly_series(
            already_mapped_series + [legacy_series_by_canonical.get(canonical_id, {})])
        ice_values, legacy_values = xwalk.build_paired_series(periods, ice_series, legacy_combined)
        series_eval = xwalk.evaluate_series(ice_values, legacy_values)

        name_score = xwalk.name_similarity(
            xwalk.normalize_model_name(model["name_en"], candidate_brand),
            xwalk.normalize_model_name(group["model_name"], group["brand"]))

        decision = xwalk.decide_match(series=series_eval, name_score=name_score)
        if decision is None:
            continue
        if best is None or (decision.score or 0) > (best[1].score or 0):
            best = (canonical_id, decision)
    return best


def run_match(
    rest: RestCall, *, master_version: str, review_csv_path: Path | None = None,
) -> dict[str, Any]:
    groups = fetch_ice_groups(rest)
    ice_series_by_group = fetch_ice_monthly_series(rest)
    legacy_series_by_canonical = fetch_legacy_monthly_series(rest)
    vehicle_models = fetch_vehicle_models(rest)
    vehicle_brands = fetch_vehicle_brands(rest)
    alias_map = fetch_brand_aliases(rest)
    existing = fetch_existing_crosswalk(rest)
    known_ids_before = fetch_known_model_group_ids(rest)

    applied, skipped_protected, skipped_unchanged_rejection, no_candidate = 0, 0, 0, 0
    review_records: list[dict[str, Any]] = []
    discovery: list[dict[str, Any]] = []

    for group in groups:
        model_group_id = group["model_group_id"]
        flags = xwalk.discovery_flags(model_group_id, known_ids_before)
        if flags:
            discovery.append({"model_group_id": model_group_id, "flags": flags})

        result = match_one_group(
            group=group, ice_series=ice_series_by_group.get(model_group_id, {}),
            legacy_series_by_canonical=legacy_series_by_canonical,
            vehicle_models=vehicle_models, vehicle_brands=vehicle_brands,
            alias_map=alias_map, existing=existing)
        if result is None:
            no_candidate += 1
            continue
        canonical_id, decision = result

        existing_row = existing.get((model_group_id, canonical_id))
        if existing_row is not None and existing_row["status"] == "APPROVED":
            skipped_protected += 1
            continue
        if existing_row is not None and existing_row.get("match_method") == "ADMIN":
            skipped_protected += 1
            continue

        correlation = decision.score if decision.match_method == "SERIES" else None
        fingerprint = xwalk.decision_fingerprint(
            model_group_id=model_group_id, canonical_model_id=canonical_id,
            correlation=correlation, ratio=None,
            name_score=decision.score if decision.match_method == "NAME" else 0.0,
            master_version=master_version)
        if (existing_row is not None and existing_row["status"] == "REJECTED"
                and existing_row.get("decision_fingerprint") == fingerprint):
            skipped_unchanged_rejection += 1
            continue

        outcome = rest("POST", "rpc/ice_crosswalk_upsert_match", {
            "p_model_group_id": model_group_id,
            "p_canonical_model_id": canonical_id,
            "p_match_method": decision.match_method,
            "p_score": decision.score,
            "p_status": decision.status,
            "p_master_version": master_version,
            "p_decision_fingerprint": fingerprint,
            "p_reason": decision.reason,
        })
        if outcome and outcome.get("applied"):
            applied += 1
        else:
            skipped_protected += 1

        if decision.status == "PROPOSED":
            review_records.append({
                "model_group_id": model_group_id, "model_name": group["model_name"], "brand": group["brand"],
                "proposed_canonical_model_id": canonical_id,
                "proposed_model_name": vehicle_models[canonical_id]["name_en"],
                "series_correlation": correlation, "total_ratio": None,
                "name_similarity": decision.score if decision.match_method == "NAME" else None,
                "proposed_status": decision.status, "match_method": decision.match_method,
                "master_version": master_version, "reason": decision.reason,
            })

    newly_seen = [
        {"model_group_id": g["model_group_id"], "first_seen_master_version": master_version}
        for g in groups if g["model_group_id"] not in known_ids_before
    ]
    if newly_seen:
        rest("POST", "ice_known_model_groups", newly_seen, prefer="resolution=ignore-duplicates")

    if review_csv_path is not None:
        write_review_csv(review_csv_path, review_records)

    return {
        "groups": len(groups), "applied": applied, "skipped_protected": skipped_protected,
        "skipped_unchanged_rejection": skipped_unchanged_rejection, "no_candidate": no_candidate,
        "discovery": discovery, "review_rows": len(review_records),
    }


def write_review_csv(path: Path, records: list[dict[str, Any]]) -> None:
    ordered = xwalk.build_review_rows(records)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(xwalk.REVIEW_SHEET_COLUMNS))
        writer.writeheader()
        for row in ordered:
            writer.writerow(row)


# ---------------------------------------------------------------------------
# id_changes.csv (SKILL.md §3)
# ---------------------------------------------------------------------------

def process_id_changes_csv(rest: RestCall, csv_bytes: bytes, *, master_version: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.TextIOWrapper(io.BytesIO(csv_bytes), encoding="utf-8-sig"))
    results = []
    for raw_row in reader:
        row = xwalk.parse_id_change_row(raw_row)
        outcome = rest("POST", "rpc/ice_crosswalk_apply_id_change", {
            "p_old_model_group_id": row.old_model_group_id,
            "p_new_model_group_id": row.new_model_group_id,
            "p_type": row.type,
            "p_master_version": master_version,
            "p_reason": None,
        })
        results.append(outcome)
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--match", action="store_true", help="run the auto-match pass")
    mode.add_argument("--process-id-changes", metavar="PATH", type=Path,
                       help="apply an Ice id_changes.csv (SKILL.md §3)")
    parser.add_argument("--master-version", default="", help="Ice master_version this run is evaluated against")
    parser.add_argument("--review-csv", type=Path, default=None,
                         help="where to write the one-time review sheet (--match only; required with --match)")
    args = parser.parse_args(argv)

    if not args.master_version:
        print("INVALID: --master-version is required")
        return 1

    if args.match:
        if args.review_csv is None:
            print("INVALID: --review-csv is required with --match -- a real match run "
                  "must always produce the owner's review evidence, never skip it")
            return 1
        summary = run_match(_request, master_version=args.master_version, review_csv_path=args.review_csv)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    results = process_id_changes_csv(
        _request, args.process_id_changes.read_bytes(), master_version=args.master_version)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
