"""Wire the pure matcher (vehreg/ice_crosswalk.py) to real data for Market Track M3.

    python -m tools.ice_crosswalk_match --match --master-version M5 \\
        --review-csv data/packages/crosswalk_review_M5.csv
    python -m tools.ice_crosswalk_match --process-id-changes id_changes.csv \\
        --master-version M5

The M7.0 package is imported in production. The R6 production-crosswalk gate remains
closed while live-write provenance is reconciled. ``--match --dry-run`` is GET-only;
``--match`` without ``--dry-run`` performs writes and must remain behind the current
roadmap gate. Offline shadow recovery uses
``tools/ice_crosswalk_r6_offline_recovery.py`` and never calls this write path.

``--match``:
1. Fetches every Ice model group (``ice_dims_model_group``), its monthly ``reg_trend``
   series, the legacy ``registrations`` monthly series for every TDR canonical model
   (joined via ``registrations.canonical_model_id``), the brand-alias table, and every
   existing crosswalk row.
2. For each Ice group, applies exact owner approvals/exclusions and identity filters,
   then evaluates guarded same-brand candidates with the established series/name scorer.
   An owner-approved target is written as ``APPROVED/ADMIN`` regardless of score status;
   series evidence remains available as a diagnostic. The writer passes the full
   evidence tuple
   (correlation, ratio, name_score) into ``decision_fingerprint``. Never touches a row
   the RPC itself protects (APPROVED, or ``match_method = 'ADMIN'``), and never
   silently re-proposes a REJECTED row whose ``decision_fingerprint`` has not changed
   -- i.e. none of correlation/ratio/name_score actually moved since it was rejected.
3. Updates the discovery ledger (``ice_known_model_groups``) and writes the one-time
   review sheet (every PROPOSED decision from this run) to ``--review-csv``.

``--process-id-changes PATH`` reads an Ice ``id_changes.csv`` (SKILL.md §3) and calls
``ice_crosswalk_apply_id_change`` once per row.

``--check-live-import`` is read-only (one GET): it fails unless the latest
``ice_package_imports`` row is the ``--master-version`` this run is evaluated against. The
R6 workflow calls it as its preflight, so the workflow itself never has to reach into the
REST client.
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
    deterministic_identity_overrides: dict[str, str] | None = None,
    owner_approved_identity_overrides: dict[str, str] | None = None,
) -> tuple[str, xwalk.MatchDecision] | None:
    """Evaluate every brand-matching TDR canonical model against one Ice group and
    return (canonical_model_id, decision) for the strongest candidate, or None if no
    candidate clears even the PROPOSED floor. Pure given its already-fetched inputs --
    no DB access here; only the fetch_* functions above touch the network."""
    model_group_id = group["model_group_id"]
    # Explicit targets are used only after that canonical identity is materialized.
    # Owner-approved targets bypass score-based status changes; other deterministic
    # recoveries remain guarded by the original series/name acceptance table.
    approved_target = (owner_approved_identity_overrides or {}).get(model_group_id)
    owner_target = approved_target or (deterministic_identity_overrides or {}).get(model_group_id)
    if approved_target and deterministic_identity_overrides and model_group_id in deterministic_identity_overrides:
        if deterministic_identity_overrides[model_group_id] != approved_target:
            raise ValueError(f"owner-approved and deterministic targets conflict for {model_group_id}")
    if owner_target is not None and owner_target not in vehicle_models:
        return None
    group_brand_key = xwalk.normalize_brand(group["brand"], alias_map)
    periods = _recent_periods(ice_series)
    already_mapped = _actively_mapped_canonical_ids(existing, model_group_id)
    already_mapped_series = [legacy_series_by_canonical.get(cid, {}) for cid in already_mapped]

    best: tuple[str, xwalk.MatchDecision] | None = None
    for canonical_id, model in vehicle_models.items():
        if owner_target is not None and canonical_id != owner_target:
            continue
        candidate_brand = vehicle_brands.get(model["brand_id"], "")
        candidate_brand_key = xwalk.normalize_brand(candidate_brand, alias_map)
        raw_candidate_name = xwalk.normalize_model_name(model["name_en"], candidate_brand)
        raw_group_name = xwalk.normalize_model_name(group["model_name"], group["brand"])
        if candidate_brand_key == group_brand_key:
            raw_candidate_name = xwalk.strip_alias_brand_prefix(
                raw_candidate_name, group_brand_key, alias_map)
            raw_group_name = xwalk.strip_alias_brand_prefix(
                raw_group_name, group_brand_key, alias_map)
        cross_brand_alias = xwalk.is_explicit_cross_brand_alias(
            group_brand_key, raw_group_name, candidate_brand_key, raw_candidate_name)
        owner_approved = approved_target == canonical_id
        if candidate_brand_key != group_brand_key and not cross_brand_alias and not owner_approved:
            continue
        # Owner approval of an existing AUTO must reach the APPROVED decision.
        # The production UNIQUE active-canonical constraint is independently
        # enforced in run_match; owner approval is not a schema bypass.
        if not owner_approved and canonical_id in already_mapped:
            continue
        if not owner_approved and _canonical_actively_mapped_elsewhere(
                existing, canonical_id, model_group_id):
            continue

        # Avoid double-counting an already-active target in the series evidence.
        additional_series = ([] if canonical_id in already_mapped else
                             [legacy_series_by_canonical.get(canonical_id, {})])
        legacy_combined = xwalk.sum_monthly_series(
            already_mapped_series + additional_series)
        ice_values, legacy_values = xwalk.build_paired_series(periods, ice_series, legacy_combined)
        series_eval = xwalk.evaluate_series(ice_values, legacy_values)

        # apply_model_name_alias is a no-op outside the one scoped alias_group it
        # knows about (§14.2 Maxus/Mifa trap) -- safe to call unconditionally.
        candidate_name = xwalk.apply_model_name_alias(raw_candidate_name, group_brand_key)
        group_name = xwalk.apply_model_name_alias(raw_group_name, group_brand_key)
        candidate_name = xwalk.apply_owner_nameplate_alias(candidate_name, group_brand_key)
        group_name = xwalk.apply_owner_nameplate_alias(group_name, group_brand_key)
        exact_identity_name = cross_brand_alias or candidate_name == group_name
        if (owner_target != canonical_id
                and xwalk.owner_identity_separation(group_brand_key, group_name, candidate_name)):
            continue
        if not exact_identity_name and owner_target != canonical_id:
            # Owner rules are hard identity filters applied before original scoring.
            # They can block an invalid candidate but never select a replacement by
            # fuzzy name alone.
            if group_brand_key in xwalk.IDENTITY_LOCK_BRANDS or candidate_brand_key in xwalk.IDENTITY_LOCK_BRANDS:
                continue
            if xwalk.standalone_l_mismatch(candidate_name, group_name):
                continue
            if xwalk.latin_letter_distance(candidate_name, group_name) > 3:
                continue

        name_score = 1.0 if cross_brand_alias else xwalk.name_similarity(candidate_name, group_name)
        if owner_approved:
            decision = xwalk.MatchDecision(
                status="APPROVED", match_method="ADMIN",
                correlation=series_eval.correlation, ratio=series_eval.ratio,
                name_score=name_score,
                reason=("OWNER_APPROVED exact target; monthly series retained as diagnostic only "
                        f"(corr={series_eval.correlation}, ratio={series_eval.ratio})"),
            )
        else:
            # Explicit aliases still use the established scorer; they do not make a
            # weak or absent series signal an AUTO by themselves.
            decision = xwalk.decide_match(series=series_eval, name_score=name_score)
        if decision is None:
            continue
        if best is None or xwalk.decision_rank(decision) > xwalk.decision_rank(best[1]):
            best = (canonical_id, decision)
    return best


def run_match(
    rest: RestCall, *, master_version: str, review_csv_path: Path | None = None,
    dry_run: bool = False, deterministic_identity_overrides: dict[str, str] | None = None,
    owner_approved_identity_overrides: dict[str, str] | None = None,
    excluded_model_group_ids: set[str] | None = None,
) -> dict[str, Any]:
    all_groups = fetch_ice_groups(rest)
    excluded_ids = excluded_model_group_ids or set()
    excluded_groups = [g for g in all_groups if g["model_group_id"] in excluded_ids]
    groups = [g for g in all_groups if g["model_group_id"] not in excluded_ids]
    ice_series_by_group = fetch_ice_monthly_series(rest)
    legacy_series_by_canonical = fetch_legacy_monthly_series(rest)
    vehicle_models = fetch_vehicle_models(rest)
    vehicle_brands = fetch_vehicle_brands(rest)
    alias_map = fetch_brand_aliases(rest)
    existing = fetch_existing_crosswalk(rest)
    known_ids_before = fetch_known_model_group_ids(rest)

    applied, skipped_protected, skipped_unchanged_rejection, no_candidate = 0, 0, 0, 0
    approved_count, auto_count, proposed_count = 0, 0, 0
    review_records: list[dict[str, Any]] = []
    candidate_records: list[dict[str, Any]] = []
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
            alias_map=alias_map, existing=existing,
            deterministic_identity_overrides=deterministic_identity_overrides,
            owner_approved_identity_overrides=owner_approved_identity_overrides)
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

        # The full evidence tuple, always -- never zeroed out based on match_method
        # (fix for PR #188 review round 2): a REJECTED row must become eligible for
        # re-proposal if correlation, ratio, *or* name_score actually changed, and
        # the review sheet must show every candidate's real numbers regardless of
        # which signal decided it.
        fingerprint = xwalk.decision_fingerprint(
            model_group_id=model_group_id, canonical_model_id=canonical_id,
            correlation=decision.correlation, ratio=decision.ratio,
            name_score=decision.name_score, master_version=master_version)
        if (existing_row is not None and existing_row["status"] == "REJECTED"
                and existing_row.get("decision_fingerprint") == fingerprint):
            skipped_unchanged_rejection += 1
            continue

        if decision.status == "APPROVED":
            approved_count += 1
        elif decision.status == "AUTO":
            auto_count += 1
        else:
            proposed_count += 1
        candidate_records.append({
            "model_group_id": group["model_group_id"], "model_name": group["model_name"],
            "brand": group["brand"], "proposed_canonical_model_id": canonical_id,
            "proposed_model_name": vehicle_models[canonical_id]["name_en"],
            "series_correlation": decision.correlation, "total_ratio": decision.ratio,
            "name_similarity": decision.name_score, "proposed_status": decision.status,
            "match_method": decision.match_method, "master_version": master_version,
            "reason": decision.reason,
        })

        if not dry_run:
            outcome = rest("POST", "rpc/ice_crosswalk_upsert_match", {
                "p_model_group_id": model_group_id,
                "p_canonical_model_id": canonical_id,
                "p_match_method": decision.match_method,
                "p_score": decision.primary_score,
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
                "series_correlation": decision.correlation, "total_ratio": decision.ratio,
                "name_similarity": decision.name_score,
                "proposed_status": decision.status, "match_method": decision.match_method,
                "master_version": master_version, "reason": decision.reason,
            })

    newly_seen = [
        {"model_group_id": g["model_group_id"], "first_seen_master_version": master_version}
        for g in groups if g["model_group_id"] not in known_ids_before
    ]
    if newly_seen and not dry_run:
        rest("POST", "ice_known_model_groups", newly_seen, prefer="resolution=ignore-duplicates")

    if review_csv_path is not None:
        # Dry-run exports every candidate (AUTO and PROPOSED) for full comparison;
        # a production run keeps the established proposal-only review sheet.
        write_review_csv(review_csv_path, candidate_records if dry_run else review_records)

    return {
        "groups": len(all_groups), "processed_groups": len(groups),
        "excluded_groups": len(excluded_groups), "applied": applied, "skipped_protected": skipped_protected,
        "skipped_unchanged_rejection": skipped_unchanged_rejection, "no_candidate": no_candidate,
        "discovery": discovery, "review_rows": len(review_records),
        "owner_approved_candidates": approved_count,
        "auto_candidates": auto_count, "proposed_candidates": proposed_count,
        "dry_run": dry_run,
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
# Read-only preflight
# ---------------------------------------------------------------------------

class LiveImportMismatch(RuntimeError):
    """The live Ice import is not the master_version this crosswalk run is for."""


def check_live_import(rest: RestCall, *, master_version: str) -> dict[str, Any]:
    """Read-only: the latest ``ice_package_imports`` row must be ``master_version``.

    One GET, no write. A crosswalk run evaluated against the wrong (or no) live import
    would match one package's groups against another's evidence, so it refuses first."""
    rows = rest(
        "GET",
        "ice_package_imports?select=master_version,period,package_version&order=imported_at.desc&limit=1",
    ) or []
    if not rows:
        raise LiveImportMismatch("no ice_package_imports row: nothing has been imported to match against")
    latest = rows[0]
    if latest.get("master_version") != master_version:
        raise LiveImportMismatch(
            f"latest ice_package_imports is {latest!r}, expected master_version {master_version!r}")
    return latest


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
    mode.add_argument("--check-live-import", action="store_true",
                       help="read-only preflight: the latest live import must be --master-version")
    parser.add_argument("--dry-run", action="store_true",
                        help="with --match, read live inputs and write only the local review CSV; never POST to Supabase")
    parser.add_argument("--master-version", default="", help="Ice master_version this run is evaluated against")
    parser.add_argument("--review-csv", type=Path, default=None,
                         help="where to write the one-time review sheet (--match only; required with --match)")
    parser.add_argument("--deterministic-identity-overrides", type=Path, default=None,
                         help="offline target package with deterministic and owner-approved identity mappings")
    args = parser.parse_args(argv)

    if not args.master_version:
        print("INVALID: --master-version is required")
        return 1

    if args.check_live_import:
        try:
            latest = check_live_import(_request, master_version=args.master_version)
        except LiveImportMismatch as exc:
            print(f"INVALID: {exc}")
            return 1
        print(json.dumps({"live_import": latest}, ensure_ascii=False))
        return 0

    if args.match:
        if args.review_csv is None:
            print("INVALID: --review-csv is required with --match -- a real match run "
                  "must always produce the owner's review evidence, never skip it")
            return 1
        identity_overrides = None
        owner_approved_overrides: dict[str, str] = {}
        excluded_group_ids: set[str] = set()
        if args.deterministic_identity_overrides:
            payload = json.loads(args.deterministic_identity_overrides.read_text(encoding="utf-8"))
            identity_overrides = payload.get("deterministic_identity_overrides")
            if not isinstance(identity_overrides, dict) or any(
                not isinstance(k, str) or not isinstance(v, str) or not v
                for k, v in identity_overrides.items()
            ):
                print("INVALID: override file must contain a string-to-string deterministic_identity_overrides object")
                return 1
            owner_approved_overrides = payload.get("owner_approved_identity_overrides", {})
            if not isinstance(owner_approved_overrides, dict) or any(
                not isinstance(k, str) or not isinstance(v, str) or not v
                for k, v in owner_approved_overrides.items()
            ):
                print("INVALID: owner_approved_identity_overrides must be a string-to-string object")
                return 1
            excluded_rows = payload.get("owner_excluded_groups", [])
            if not isinstance(excluded_rows, list) or any(
                not isinstance(row, dict) or not isinstance(row.get("model_group_id"), str)
                for row in excluded_rows
            ):
                print("INVALID: owner_excluded_groups must be a list of objects with model_group_id strings")
                return 1
            excluded_group_ids = {row["model_group_id"] for row in excluded_rows}
        summary = run_match(_request, master_version=args.master_version,
                            review_csv_path=args.review_csv, dry_run=args.dry_run,
                            deterministic_identity_overrides=identity_overrides,
                            owner_approved_identity_overrides=owner_approved_overrides,
                            excluded_model_group_ids=excluded_group_ids)
        if args.dry_run:
            summary["discovery_count"] = len(summary.pop("discovery"))
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    results = process_id_changes_csv(
        _request, args.process_id_changes.read_bytes(), master_version=args.master_version)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
