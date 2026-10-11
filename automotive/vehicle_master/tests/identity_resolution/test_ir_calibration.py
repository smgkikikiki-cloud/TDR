"""The R6 calibration milestone: recovered first-run rows, the calibration dataset, the owner-adjudication sheet and the report.

What these tests hold in place:

* the committed inputs are exactly the read-only extracts that were taken (hashes), and they are the first-run R6 rows;
* an offline replay of the legacy matcher reproduces every stored row (so the legacy numbers and windows are the run's own);
* the Contract v1 side is a DRY RUN under `binding: false`, built through the provider boundary with absent rows UNKNOWN (never zero);
* the owner columns are blank and the legacy decision is kept apart from them; the sheet follows the owner's seven priorities;
* every committed output is what `calibration.build` produces from the committed inputs (nothing hand-edited, nothing stale);
* the calibration code never reaches a network or a database.

They do not say the thresholds are right: nothing is calibrated until the owner's labels exist.
"""
from __future__ import annotations

import csv
import functools
import hashlib
import io
import json
import re
from collections import Counter

import pytest

import ir_reference as REF
import ir_support as S
from identity_resolution.calibration import adapters as A
from identity_resolution.calibration import build, columns, legacy, report, review, sensitivity
from identity_resolution.contract import loader

CAL = A.CALIBRATION_DIR
PACKAGE = A.REPO_ROOT / A.PACKAGE_RELATIVE

needs_package = pytest.mark.skipif(not PACKAGE.exists(), reason="the archived M7.0 package is not in this checkout")


def read_csv(name: str) -> tuple[list[str], list[dict]]:
    text = (CAL / name).read_text(encoding="utf-8-sig")
    reader = csv.DictReader(io.StringIO(text, newline=""))
    rows = list(reader)
    return list(reader.fieldnames), rows


@functools.lru_cache(maxsize=None)
def ext() -> dict:
    return A.load_extracts()


@functools.lru_cache(maxsize=None)
def ice() -> dict:
    return A.load_ice_package()


@functools.lru_cache(maxsize=None)
def built() -> dict:
    return build.build()


# --------------------------------------------------------------------------------------------------------------- inputs
def test_inputs_are_exactly_the_extracts_the_manifest_describes():
    manifest = json.loads((A.INPUTS_DIR / "MANIFEST.json").read_text(encoding="utf-8"))
    on_disk = {p.name for p in A.INPUTS_DIR.iterdir() if p.name != "MANIFEST.json"}
    assert on_disk == set(manifest["files"]), "inputs/ and MANIFEST.json disagree about which files exist"
    for name, meta in manifest["files"].items():
        raw = (A.INPUTS_DIR / name).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == meta["sha256"], f"{name} was edited after it was extracted"
        assert len(raw) == meta["bytes"]
    assert manifest["access"].startswith("SELECT only")
    assert manifest["first_run"]["artifact"]["downloaded"] is False, "the artifact was not downloaded; the manifest must say so"


def test_the_extract_shows_the_inputs_did_not_change_after_the_run():
    meta = ext()["meta"]["meta"]
    assert meta["registrations_rows_created_after_run_start"] == 0
    assert meta["vehicle_models_updated_after_run_start"] == 0
    assert meta["vehicle_generations_updated_after_run_start"] == 0


def test_the_crosswalk_rows_are_the_first_run_and_nobody_has_reviewed_them():
    rows = ext()["crosswalk"]
    assert len(rows) == 490 and len({r["id"] for r in rows}) == 490
    assert Counter((r["status"], r["match_method"]) for r in rows) == {
        ("AUTO", "SERIES"): 82, ("PROPOSED", "SERIES"): 12, ("PROPOSED", "NAME"): 395, ("PROPOSED", "ADMIN"): 1}
    assert {r["master_version"] for r in rows} == {"7.0"}
    assert all("2026-10-10T15:4" in r["created_at"] and r["created_at"] == r["updated_at"] for r in rows), "every row was written once, by the 2026-10-10 run"
    assert not [r for r in rows if r["status"] in ("APPROVED", "LOCKED", "REJECTED")], "an owner decision exists in the database: the label set is no longer empty"
    assert len(ext()["redirects"]) == 50


@needs_package
def test_the_ice_side_is_the_archived_m7_package_and_equals_what_is_live():
    data = ice()
    assert data["sha256"] == A.PACKAGE_SHA256 and len(data["groups"]) == 1200 and data["trend_rows"] == 262985
    manifest = json.loads((A.INPUTS_DIR / "MANIFEST.json").read_text(encoding="utf-8"))["verification"]["package_equals_live"]
    lines = [f"{g}|{p}|{int(v)}" for g, cells in sorted(data["cells"].items()) for p, v in sorted(cells.items())]
    assert len(lines) == manifest["ice_reg_trend_cells"]
    assert hashlib.md5("\n".join(lines).encode()).hexdigest() == manifest["ice_reg_trend_cells_md5"], "the package no longer equals the cells that were live when the rows were extracted"
    dims = [f"{r['model_group_id']}|{r['model_name']}|{r['brand']}|{r['reg_total_all']}|{r['segment']}|{r['body']}" for r in sorted(data["groups"], key=lambda r: r["model_group_id"])]
    assert hashlib.md5("\n".join(dims).encode()).hexdigest() == manifest["ice_dims_model_group_md5"]


@needs_package
def test_a_legacy_replay_reproduces_every_stored_row_exactly():
    verification = legacy.verify_against_stored(legacy.replay(ice(), ext()), ext()["crosswalk"])
    assert verification["mismatches"] == []
    assert verification["reproduced_exactly"] == 489 == verification["stored_matcher_rows"]
    assert verification["no_candidate_and_nothing_stored"] == 711
    assert verification["stored_admin_rows"] == 1


# ---------------------------------------------------------------------------------------------------------- the v1 side
@needs_package
def test_the_snapshot_passes_the_provider_boundary_and_never_zero_fills_an_absent_row():
    from identity_resolution.providers import base
    snap = A.build_snapshot(ice(), ext())
    base.validate_snapshot(snap)    # record.schema.json and the capability data (I4a)
    declared = loader.load_capabilities()["sources"]
    assert declared["ice"]["series.absent_row"]["status"] == "unconfirmed" and declared["tdr_registrations"]["series.absent_row"]["status"] == "unconfirmed"
    for owner in (snap["subjects"], snap["targets"]):
        for item in owner:
            series = item.get("series")
            if not series:
                continue
            block = series["absent_rows"]
            assert block["semantics"] == "UNKNOWN" and block["confirmed"] is False
            start = A.pidx(series["start"])
            for m in block["months"]:
                assert series["counts"][A.pidx(m) - start] is None, f"{m} is an absent row and must be null, not 0"
    assert snap["existing_mappings"] == [], "the evaluation is fresh: no stored claim may influence the evidence"


@needs_package
def test_the_dataset_is_a_dry_run_under_the_current_adoption_gate():
    assert S.adoption()["binding"] is False
    for g in report_summary()["v1_outcomes"]["groups_all"]:
        assert g in S.OUTCOMES
    assert report_summary()["v1_outcomes"]["binding"] is False


# --------------------------------------------------------------------------------------------------------------- outputs
@needs_package
def test_every_committed_output_is_what_the_build_produces_from_the_committed_inputs():
    stale = [name for name, text in built().items() if (CAL / name).read_text(encoding="utf-8-sig") != text]
    assert not stale, f"stale or hand-edited outputs: {stale}; run: python -m identity_resolution.calibration.build"


def report_summary() -> dict:
    return json.loads((CAL / "calibration_summary.json").read_text(encoding="utf-8"))


def test_the_owner_columns_are_blank_and_the_legacy_decision_is_kept_apart():
    header, rows = read_csv("r6_owner_review.csv")
    assert header[-4:] == review.OWNER_COLUMNS == ["owner_verdict", "owner_link_type", "owner_canonical_model_id", "owner_notes"]
    for r in rows:
        assert all(r[c] == "" for c in review.OWNER_COLUMNS), f"row {r['review_rank']} has an owner value; owner labels must come from the owner"
    assert "legacy_r6_status" in header and "legacy_r6_match_method" in header
    assert not [c for c in header if c.startswith("owner_") and c not in review.OWNER_COLUMNS]
    legacy_values = {r["legacy_r6_status"] for r in rows if r["legacy_r6_status"]}
    assert legacy_values <= {"AUTO", "PROPOSED"}
    # nothing in the dataset or the group table may look like an owner label either
    for name in ("r6_calibration_dataset.csv", "r6_calibration_groups.csv"):
        head, _ = read_csv(name)
        assert not [c for c in head if c.startswith("owner_")], f"{name} must not carry owner columns"


def test_the_sheet_follows_the_owner_priorities():
    _, rows = read_csv("r6_owner_review.csv")
    tiers = [int(r["review_tier"]) for r in rows]
    assert tiers == sorted(tiers), "rows must be ordered by tier"
    assert [int(r["review_rank"]) for r in rows] == list(range(1, len(rows) + 1))
    assert all(review.TIER_LABELS[int(r["review_tier"])] == r["review_tier_label"] for r in rows)
    first = {int(r["review_tier"]) for r in rows}
    assert {1, 2, 3, 4, 7} <= first
    # tier 1 is exactly the legacy AUTO rows
    auto_ids = {str(r["id"]) for r in ext()["crosswalk"] if r["status"] == "AUTO"}
    assert {r["legacy_r6_row_id"] for r in rows if r["review_tier"] == "1"} == auto_ids
    # tier 2 is legacy PROPOSED rows with high volume
    for r in rows:
        if r["review_tier"] == "2":
            assert r["legacy_r6_status"] == "PROPOSED"
            assert int(r["ice_lifetime_units"]) >= review.HIGH_VOLUME_LIFETIME_UNITS or int(r["ice_units_last24m"]) >= review.HIGH_VOLUME_LAST24M_UNITS
    # inside a tier the newest-24-month volume never increases
    for tier in first:
        vols = [int(r["ice_units_last24m"]) for r in rows if int(r["review_tier"]) == tier]
        assert vols == sorted(vols, reverse=True)
    cum = [float(r["cumulative_unique_group_units_share"]) for r in rows]
    assert cum == sorted(cum) and cum[-1] <= 1.0
    # the tier is the FIRST matching priority
    assert all(int(r["review_tiers_matched"].split(";")[0]) == int(r["review_tier"]) for r in rows)


def test_every_stored_row_is_in_the_dataset_and_in_the_sheet():
    stored = {str(r["id"]) for r in ext()["crosswalk"]}
    _, dataset = read_csv("r6_calibration_dataset.csv")
    _, sheet = read_csv("r6_owner_review.csv")
    assert {r["legacy_row_id"] for r in dataset if r["legacy_row_id"]} == stored
    assert {r["legacy_r6_row_id"] for r in sheet if r["legacy_r6_row_id"]} == stored


def test_the_dataset_has_every_column_the_owner_asked_for():
    header, _ = read_csv("r6_calibration_dataset.csv")
    required = {
        "model_group_id", "ice_model_name", "ice_brand", "candidate_canonical_model_id", "tdr_brand", "tdr_model_name",
        "legacy_status", "legacy_match_method", "legacy_correlation", "legacy_ratio", "legacy_name_score",
        "legacy_window_first", "legacy_window_last", "legacy_window_months", "legacy_window_tdr_zero_filled_months",
        "v1_correlation", "v1_ratio", "v1_common_months", "v1_window_first", "v1_window_last", "v1_semantics_gap_months",
        "ice_lifetime_units", "ice_units_last12m", "ice_units_last24m", "tdr_lifetime_units", "tdr_units_last12m",
        "lineage_roles", "lineage_events", "lineage_ops", "v1_brand_relation", "v1_name_relation", "v1_link_candidate",
        "v1_codes_supporting", "v1_codes_blocking", "v1_codes_excluded", "v1_codes_info",
    }
    assert required <= set(header), sorted(required - set(header))


def test_the_dataset_rows_use_only_contract_vocabulary():
    _, rows = read_csv("r6_calibration_dataset.csv")
    registry = set(S.codes())
    for r in rows:
        assert r["v1_link_candidate"] in S.LINK_TYPES
        assert r["v1_name_relation"] in S.NAME_RELATIONS
        assert r["v1_brand_relation"] in S.BRAND_RELATIONS
        assert r["v1_series_state"] in ("STRONG", "WEAK", "UNAVAILABLE")
        for col in ("v1_codes_supporting", "v1_codes_blocking", "v1_codes_excluded", "v1_codes_info"):
            for code in filter(None, r[col].split(";")):
                assert code in registry or code in ("SERIES_DECISIVELY_WRONG", "NAME_SIBLING_VARIANT", "NAME_CONTRADICTION"), f"{code} is not a registered reason code"
        if r["v1_series_state"] != "UNAVAILABLE":
            assert r["v1_correlation"] != "" and r["v1_ratio"] != ""
        gap = int(r["v1_semantics_gap_months"] or 0)
        if gap > 0:
            reported = ";".join([r["v1_codes_blocking"], r["v1_codes_info"], r["v1_codes_excluded"]]).split(";")
            assert "SER_MISSING_ROW_SEMANTICS_UNCONFIRMED" in reported or r["v1_link_candidate"] == "PART_OF", "a gap month must be reported (SPEC 6.2a)"
            parts = int(r["v1_gap_months_both_absent"]) + int(r["v1_gap_months_subject_only_absent"]) + int(r["v1_gap_months_target_only_absent"])
            assert parts == gap, "the gap breakdown must add up to semantics_gap_months"


def test_the_legacy_numbers_in_the_dataset_are_the_stored_numbers():
    _, rows = read_csv("r6_calibration_dataset.csv")
    n = 0
    for r in rows:
        if r["legacy_run_selected"] != "true":
            continue
        n += 1
        m = re.search(r"corr=([^,]+), ratio=([^)]+)\)", r["legacy_stored_reason"])
        corr, ratio = m.group(1), m.group(2)
        if r["legacy_stored_reason"].startswith("strong"):
            assert f"{float(r['legacy_correlation']):.4f}" == corr and f"{float(r['legacy_ratio']):.4f}" == ratio
        elif corr == "None":
            assert r["legacy_correlation"] == ""
        else:
            assert float(r["legacy_correlation"]) == float(corr) and float(r["legacy_ratio"]) == float(ratio)
    assert n == 489


def test_the_groups_table_accounts_for_every_ice_group():
    _, rows = read_csv("r6_calibration_groups.csv")
    assert len(rows) == 1200 and len({r["model_group_id"] for r in rows}) == 1200
    assert sum(int(r["ice_lifetime_units"]) for r in rows) == 4141987, "units in the groups table must equal the package's 4,141,987"
    assert Counter(r["v1_group_outcome"] for r in rows) == report_summary()["v1_outcomes"]["groups_all"]


@needs_package
def test_the_v1_series_numbers_in_the_dataset_equal_the_independent_reference_on_real_data():
    """Every single-target pair: recompute window, gap and statistics with the corpus tests' separate arithmetic reference (ir_reference)."""
    snap = A.build_snapshot(ice(), ext())
    subjects = {s["entity_id"]: s for s in snap["subjects"]}
    targets = {t["target_id"]: t for t in snap["targets"]}
    policy = S.policy()
    _, rows = read_csv("r6_calibration_dataset.csv")
    checked = 0
    for r in rows:
        if r["candidate_target_count"] != "1":
            continue
        subj, tgt = subjects[r["model_group_id"]].get("series"), targets[r["candidate_canonical_model_id"]].get("series")
        ref = REF.compare_series(subj, tgt, policy)
        assert ref["refusal"] is None
        assert ref["state"] == r["v1_series_state"], (r["model_group_id"], r["candidate_canonical_model_id"], ref["state"], r["v1_series_state"])
        assert ref["semantics_gap_months"] == int(r["v1_semantics_gap_months"])
        if ref["common_window"]:
            assert (ref["common_window"]["from"], ref["common_window"]["to"]) == (r["v1_window_first"], r["v1_window_last"])
        stats = ref["stats"]
        if stats and stats["correlation"] is not None:
            assert abs(stats["correlation"] - float(r["v1_correlation"])) <= 1e-6 and abs(stats["ratio"] - float(r["v1_ratio"])) <= 1e-6
            assert stats["common_months"] == int(r["v1_common_months"]) and stats["joint_nonzero_months"] == int(r["v1_joint_nonzero_months"])
            assert stats["subject_units"] == float(r["v1_subject_units"]) and stats["target_units"] == float(r["v1_target_units"])
        else:
            assert r["v1_correlation"] == "" and r["v1_ratio"] == ""
        checked += 1
    assert checked >= 1400, checked


# ----------------------------------------------------------------------------------------------- sensitivity and the report
def test_the_sensitivity_run_is_complete_and_consistent_with_the_dataset():
    doc = json.loads((CAL / "sensitivity_results.json").read_text(encoding="utf-8"))
    ids = {v["id"] for v in doc["variants"]}
    assert ids == {v[0] for v in sensitivity.VARIANTS} | {w[0] for w in sensitivity.WHAT_IFS}
    assert doc["groups"] == 1200 and sum(doc["baseline_outcomes"].values()) == 1200
    assert doc["baseline_outcomes"] == report_summary()["v1_outcomes"]["groups_all"], "the baseline run and the dataset disagree"
    assert all("refusal" not in v for v in doc["variants"])
    adoption_ids = {e["id"] for e in S.adoption()["entries"]}
    for v in doc["variants"]:
        if not v["hypothetical"]:
            assert v["adoption_entry"].split(" (")[0] in adoption_ids | {"series_strong", "series_window"}, v["adoption_entry"]
    for w in (v for v in doc["variants"] if v["hypothetical"]):
        assert w["id"].startswith("what-if:"), "a hypothesis about capability data must be labelled as one"


def test_the_sensitivity_harness_never_edits_a_contract_file():
    source = (CAL / "sensitivity.py").read_text(encoding="utf-8")
    assert "write_text" in source and source.count("write_text") == 1, "the only file the harness writes is its own results"
    assert "provider_capabilities" not in source.replace("capability data", "")


def test_every_pending_adoption_entry_is_classified_in_the_report():
    rows = report.entry_table(report_summary())
    pending = [e["id"] for e in S.adoption()["entries"] if e["status"] == "pending"]
    assert [r["id"] for r in rows] == pending
    needs = {r["id"]: r["needs"] for r in rows}
    assert needs["series_absent_row_gap"].startswith("ICE ANSWER")
    assert all(n in ("OWNER LABELS", "OWNER DECISION", "OWNER SIGN-OFF") or n.startswith("ICE ANSWER") for n in needs.values())
    assert S.adoption()["binding"] is False and all(e["status"] != "calibrated" for e in S.adoption()["entries"]), "this milestone calibrates nothing"


def test_the_report_states_what_it_must():
    text = (CAL / "CALIBRATION_REPORT.md").read_text(encoding="utf-8")
    for heading in ("## 1. What was recovered", "## 3. Legacy zero-filled window", "## 4. Distributions", "## 5. Cases around each provisional boundary",
                    "## 6. How far the real decisions move", "## 7. Outcomes under the current non-binding", "## 8. Which provisional keys cannot be calibrated",
                    "## 9. What the owner needs to label", "## 10. Limits of this report"):
        assert heading in text, heading
    assert "binding: false" in text and "R6 was not re-run" in text
    for needle in ("not downloaded", "SELECT", "reproduces", "Nothing was copied into the owner columns"):
        assert needle in text, needle
    assert "exhaustive" not in text.lower()


def test_the_summary_agrees_with_the_inputs():
    s = report_summary()
    assert s["recovery"]["rows_total"] == 490 and s["recovery"]["groups_with_a_row"] == 489
    assert s["recovery"]["verification"]["reproduced_exactly"] == 489 and s["recovery"]["verification"]["mismatches"] == 0
    _, rows = read_csv("r6_owner_review.csv")
    assert s["review_sheet"]["rows"] == len(rows)
    assert sum(s["review_sheet"]["rows_by_tier"].values()) == len(rows)


# ---------------------------------------------------------------------------------------------------------------- hygiene
def test_the_calibration_code_cannot_reach_a_network_or_a_database():
    forbidden = re.compile(r"^\s*(?:from|import)\s+(?:requests|urllib|http|socket|supabase|psycopg2?|asyncpg|httpx|aiohttp|ftplib|smtplib)\b", re.M)
    for path in CAL.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not forbidden.search(text), f"{path.name} imports a network/database client"
        assert "ice_crosswalk_upsert_match" not in text and "ice_crosswalk_apply_id_change" not in text, f"{path.name} names a crosswalk write RPC"


def test_the_legacy_matcher_is_still_untouched_and_unaware_of_the_calibration():
    root = S.IR_ROOT.parent
    for relative in ("vehreg/ice_crosswalk.py", "tools/ice_crosswalk_match.py"):
        assert "calibration" not in (root / relative).read_text(encoding="utf-8").lower().replace("calibration of", "")


def test_every_output_column_is_documented_and_every_documented_column_exists():
    seen = set()
    for name in ("r6_calibration_dataset.csv", "r6_calibration_groups.csv", "r6_owner_review.csv"):
        header, _ = read_csv(name)
        seen |= set(header)
        missing = [c for c in header if c not in columns.DOC]
        assert not missing, f"{name}: undocumented columns {missing}"
    assert set(columns.DOC) <= seen, f"documented but never written: {sorted(set(columns.DOC) - seen)}"
    assert len(columns.DOC) == len(columns.COLUMNS), "a column is documented twice"


def test_the_per_entry_notes_in_the_report_agree_with_the_sensitivity_numbers():
    doc = json.loads((CAL / "sensitivity_results.json").read_text(encoding="utf-8"))
    by = {v["id"]: v for v in doc["variants"]}
    def moved(prefix):
        hits = [v for k, v in by.items() if k.startswith(prefix)]
        assert hits, prefix
        return [v["groups_changed"] for v in hits]
    assert moved("monthly_fit.") == [0, 0, 0, 0] and moved("margin.") == [0, 0, 0, 0] and moved("part_of.min_ratio_above") == [0, 0]
    assert by["auto.units=240"]["auto_lost"] > 0 and not any(moved("auto.common_months") + moved("auto.joint_nonzero") + moved("propose.common_months")), "the series_minimums note"
    assert by["what-if: Ice confirms absent = zero"]["groups_changed"] == 0 < by["what-if: Ice and TDR confirm absent = zero"]["groups_changed"], "the series_absent_row_gap note"
    assert max(moved("lifecycle.")) <= 12, "the attributes_lifecycle note"
    summary = report_summary()
    assert summary["gap_composition"]["sum_of_parts_equals_gap_everywhere"] is True
    gc = summary["gap_composition"]
    assert gc["gap_months"]["both_sources_absent"] > gc["gap_months"]["only_ice_absent"] + gc["gap_months"]["only_tdr_absent"], "most gap months must be months in which both sources lack the row"
