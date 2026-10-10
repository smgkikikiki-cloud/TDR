"""Tests for tools/ice_crosswalk_match.py -- the DB-wired M3 matching engine -- against
a FakeRest double that mimics the real migration_v63 RPC semantics closely enough to
exercise the orchestration logic end to end (pagination, candidate selection, the
many-TDR-models-to-one-group sum, protected/unchanged-rejection skipping, the review CSV,
and id_changes dispatch). The real SQL itself is exercised separately against a real
Postgres server in tests/test_ice_crosswalk_migration_v63.py; no complete real Ice
delivery exists yet (docs/WORK_STATE.md), so every fixture here is synthetic.
"""
from __future__ import annotations

import csv
import io

from tools import ice_crosswalk_match as matcher
from vehreg import ice_crosswalk as xwalk

PERIODS = [f"2569-0{i}" for i in range(1, 7)]  # 2569-01 .. 2569-06
GREGORIAN_PERIODS = [f"2026-0{i}-01" for i in range(1, 7)]


class FakeRest:
    def __init__(self):
        self.tables: dict[str, list[dict]] = {
            "ice_dims_model_group": [], "ice_reg_trend": [], "registrations": [],
            "vehicle_models": [], "vehicle_brands": [], "ice_brand_aliases": [],
            "ice_model_crosswalk": [], "ice_known_model_groups": [],
        }
        self._next_id = 1
        self.rpc_calls: list[tuple[str, dict]] = []

    def __call__(self, method: str, path: str, payload=None, *, prefer: str | None = None):
        if method == "GET":
            return self._get(path)
        if method == "POST" and path == "rpc/ice_crosswalk_upsert_match":
            self.rpc_calls.append((path, payload))
            return self._upsert_match(payload)
        if method == "POST" and path == "rpc/ice_crosswalk_apply_id_change":
            self.rpc_calls.append((path, payload))
            return self._apply_id_change(payload)
        if method == "POST" and path == "ice_known_model_groups":
            return self._insert_known_groups(payload, prefer)
        raise AssertionError(f"unexpected FakeRest call: {method} {path}")

    def _get(self, path: str) -> list[dict]:
        table_part, _, query = path.partition("?")
        params = dict(p.split("=", 1) for p in query.split("&") if p and "=" in p)
        rows = list(self.tables[table_part])
        if table_part == "registrations" and params.get("canonical_model_id") == "not.is.null":
            rows = [r for r in rows if r.get("canonical_model_id") is not None]
        offset = int(params.get("offset", 0))
        limit = int(params.get("limit", len(rows) or 1))
        return rows[offset:offset + limit]

    def _find(self, model_group_id: str, canonical_model_id: str | None) -> dict | None:
        for row in self.tables["ice_model_crosswalk"]:
            if row["model_group_id"] == model_group_id and row["canonical_model_id"] == canonical_model_id:
                return row
        return None

    def _upsert_match(self, payload: dict) -> dict:
        model_group_id = payload["p_model_group_id"]
        canonical_model_id = payload["p_canonical_model_id"]
        existing = self._find(model_group_id, canonical_model_id)
        if existing and (existing["status"] == "APPROVED" or existing["match_method"] == "ADMIN"):
            return {"applied": False, "conflict": "protected_admin_row"}
        if canonical_model_id is not None and payload["p_status"] in ("AUTO", "APPROVED"):
            for row in self.tables["ice_model_crosswalk"]:
                if (row["canonical_model_id"] == canonical_model_id and row["model_group_id"] != model_group_id
                        and row["status"] in ("AUTO", "APPROVED")):
                    return {"applied": False, "conflict": "canonical_model_already_active_elsewhere"}
        if existing:
            existing.update(
                match_method=payload["p_match_method"], score=payload["p_score"], status=payload["p_status"],
                master_version=payload["p_master_version"],
                decision_fingerprint=payload["p_decision_fingerprint"], reason=payload["p_reason"])
        else:
            self.tables["ice_model_crosswalk"].append({
                "id": self._next_id, "model_group_id": model_group_id, "canonical_model_id": canonical_model_id,
                "match_method": payload["p_match_method"], "score": payload["p_score"],
                "status": payload["p_status"], "master_version": payload["p_master_version"],
                "decision_fingerprint": payload["p_decision_fingerprint"], "reason": payload["p_reason"],
            })
            self._next_id += 1
        return {"applied": True, "conflict": None}

    def _apply_id_change(self, payload: dict) -> dict:
        old, new, change_type = payload["p_old_model_group_id"], payload["p_new_model_group_id"], payload["p_type"]
        moved, proposals = 0, 0
        if change_type in ("เปลี่ยนรหัส", "รวม"):
            to_move = [r for r in self.tables["ice_model_crosswalk"] if r["model_group_id"] == old]
            for row in to_move:
                if self._find(new, row["canonical_model_id"]) is None:
                    row["model_group_id"] = new
                    moved += 1
                else:
                    self.tables["ice_model_crosswalk"].remove(row)
        else:
            for row in list(self.tables["ice_model_crosswalk"]):
                if (row["model_group_id"] == old and row["canonical_model_id"] is not None
                        and row["status"] in ("AUTO", "APPROVED") and self._find(new, row["canonical_model_id"]) is None):
                    self.tables["ice_model_crosswalk"].append({
                        "id": self._next_id, "model_group_id": new, "canonical_model_id": row["canonical_model_id"],
                        "match_method": "ADMIN", "score": None, "status": "PROPOSED",
                        "master_version": payload["p_master_version"], "decision_fingerprint": None,
                        "reason": payload["p_reason"] or f"id_changes แยก: {old} -> {new}",
                    })
                    self._next_id += 1
                    proposals += 1
        return {"type": change_type, "old_model_group_id": old, "new_model_group_id": new,
                "moved": moved, "structure_proposals": proposals}

    def _insert_known_groups(self, payload: list[dict], prefer: str | None) -> None:
        existing_ids = {r["model_group_id"] for r in self.tables["ice_known_model_groups"]}
        for row in payload:
            if row["model_group_id"] not in existing_ids:
                self.tables["ice_known_model_groups"].append(row)
        return None


def _brand(canonical_id: str, name_en: str) -> dict:
    return {"canonical_id": canonical_id, "name_en": name_en}


def _model(canonical_id: str, name_en: str, brand_id: str) -> dict:
    return {"canonical_id": canonical_id, "name_en": name_en, "brand_id": brand_id}


def _group(model_group_id: str, model_name: str, brand: str) -> dict:
    return {"model_group_id": model_group_id, "model_name": model_name, "brand": brand}


def _ice_series_rows(model_group_id: str, values: list[float]) -> list[dict]:
    return [{"model_group_id": model_group_id, "period": p, "reg_count": v} for p, v in zip(PERIODS, values)]


def _legacy_rows(canonical_model_id: str, values: list[float]) -> list[dict]:
    return [
        {"period": p, "registrations": v, "canonical_model_id": canonical_model_id}
        for p, v in zip(GREGORIAN_PERIODS, values)
    ]


def _base_rest() -> FakeRest:
    rest = FakeRest()
    rest.tables["vehicle_brands"] = [_brand("toyota", "Toyota")]
    rest.tables["ice_brand_aliases"] = [
        {"brand": "Deepal", "alias_group": "deepal_changan"},
        {"brand": "Changan", "alias_group": "deepal_changan"},
    ]
    return rest


# ---------------------------------------------------------------------------
# Strong series + strong name -> AUTO, applied and never in the review sheet
# ---------------------------------------------------------------------------

def test_strong_match_is_applied_as_auto_and_excluded_from_review(tmp_path):
    rest = _base_rest()
    values = [100.0, 110.0, 120.0, 130.0, 140.0, 150.0]
    rest.tables["ice_dims_model_group"] = [_group("toyota-hilux-travo", "Hilux Travo", "Toyota")]
    rest.tables["ice_reg_trend"] = _ice_series_rows("toyota-hilux-travo", values)
    rest.tables["vehicle_models"] = [_model("toyota-hilux-travo-cab", "Hilux Travo", "toyota")]
    rest.tables["registrations"] = _legacy_rows("toyota-hilux-travo-cab", values)

    review_path = tmp_path / "review.csv"
    summary = matcher.run_match(rest, master_version="M5", review_csv_path=review_path)

    assert summary["applied"] == 1
    assert summary["review_rows"] == 0
    row = rest.tables["ice_model_crosswalk"][0]
    assert row["canonical_model_id"] == "toyota-hilux-travo-cab"
    assert row["status"] == "AUTO"
    assert row["match_method"] == "SERIES"
    assert review_path.read_text(encoding="utf-8-sig").strip().count("\n") == 0  # header only


# ---------------------------------------------------------------------------
# No candidate at all
# ---------------------------------------------------------------------------

def test_no_matching_brand_at_all_is_counted_as_no_candidate(tmp_path):
    rest = _base_rest()
    rest.tables["ice_dims_model_group"] = [_group("unrelated-group", "Something Else", "Honda")]
    rest.tables["ice_reg_trend"] = _ice_series_rows("unrelated-group", [10.0] * 6)
    rest.tables["vehicle_models"] = [_model("toyota-hilux-travo-cab", "Hilux Travo", "toyota")]
    rest.tables["registrations"] = []

    summary = matcher.run_match(rest, master_version="M5", review_csv_path=tmp_path / "review.csv")
    assert summary["no_candidate"] == 1
    assert rest.tables["ice_model_crosswalk"] == []


# ---------------------------------------------------------------------------
# Many TDR models -> one Ice group (the sum-consistently rule)
# ---------------------------------------------------------------------------

def test_second_tdr_model_joins_an_already_mapped_group_via_combined_series(tmp_path):
    rest = _base_rest()
    cab_values = [60.0, 66.0, 72.0, 78.0, 84.0, 90.0]
    double_cab_values = [40.0, 44.0, 48.0, 52.0, 56.0, 60.0]
    combined = [a + b for a, b in zip(cab_values, double_cab_values)]
    rest.tables["ice_dims_model_group"] = [_group("toyota-hilux-travo", "Hilux Travo", "Toyota")]
    rest.tables["ice_reg_trend"] = _ice_series_rows("toyota-hilux-travo", combined)
    rest.tables["vehicle_models"] = [
        _model("toyota-hilux-travo-cab", "Hilux Travo", "toyota"),
        _model("toyota-hilux-travo-double-cab", "Hilux Travo", "toyota"),
    ]
    rest.tables["registrations"] = (
        _legacy_rows("toyota-hilux-travo-cab", cab_values) + _legacy_rows("toyota-hilux-travo-double-cab", double_cab_values))
    # The first model is already actively mapped (as AUTO) from a prior run.
    rest.tables["ice_model_crosswalk"] = [{
        "id": 1, "model_group_id": "toyota-hilux-travo", "canonical_model_id": "toyota-hilux-travo-cab",
        "match_method": "SERIES", "score": 0.999, "status": "AUTO", "master_version": "M4",
        "decision_fingerprint": "x", "reason": "prior run",
    }]
    rest._next_id = 2

    summary = matcher.run_match(rest, master_version="M5", review_csv_path=tmp_path / "review.csv")
    assert summary["applied"] == 1
    rows = {r["canonical_model_id"]: r for r in rest.tables["ice_model_crosswalk"]}
    assert rows["toyota-hilux-travo-cab"]["status"] == "AUTO"
    assert rows["toyota-hilux-travo-double-cab"]["status"] == "AUTO"
    assert rows["toyota-hilux-travo-cab"]["model_group_id"] == rows["toyota-hilux-travo-double-cab"]["model_group_id"]


# ---------------------------------------------------------------------------
# One canonical model cannot actively map to two Ice groups
# ---------------------------------------------------------------------------

def test_one_canonical_model_cannot_actively_map_to_two_groups(tmp_path):
    rest = _base_rest()
    values = [100.0, 110.0, 120.0, 130.0, 140.0, 150.0]
    rest.tables["ice_dims_model_group"] = [
        _group("group-a", "Hilux Travo", "Toyota"), _group("group-b", "Hilux Travo", "Toyota"),
    ]
    rest.tables["ice_reg_trend"] = _ice_series_rows("group-a", values) + _ice_series_rows("group-b", values)
    rest.tables["vehicle_models"] = [_model("toyota-hilux-travo-cab", "Hilux Travo", "toyota")]
    rest.tables["registrations"] = _legacy_rows("toyota-hilux-travo-cab", values)

    summary = matcher.run_match(rest, master_version="M5", review_csv_path=tmp_path / "review.csv")
    assert summary["applied"] == 1
    assert summary["skipped_protected"] == 1
    active_rows = [r for r in rest.tables["ice_model_crosswalk"] if r["status"] == "AUTO"]
    assert len(active_rows) == 1


# ---------------------------------------------------------------------------
# Rejected mapping does not immediately reappear unchanged
# ---------------------------------------------------------------------------

def test_rejected_mapping_with_unchanged_inputs_is_not_reproposed(tmp_path):
    rest = _base_rest()
    values = [100.0, 110.0, 120.0, 130.0, 140.0, 150.0]
    rest.tables["ice_dims_model_group"] = [_group("toyota-hilux-travo", "Hilux Travo", "Toyota")]
    rest.tables["ice_reg_trend"] = _ice_series_rows("toyota-hilux-travo", values)
    rest.tables["vehicle_models"] = [_model("toyota-hilux-travo-cab", "Hilux Travo", "toyota")]
    rest.tables["registrations"] = _legacy_rows("toyota-hilux-travo-cab", values)

    series_eval = xwalk.evaluate_series(values, values)
    fingerprint = xwalk.decision_fingerprint(
        model_group_id="toyota-hilux-travo", canonical_model_id="toyota-hilux-travo-cab",
        correlation=series_eval.correlation, ratio=series_eval.ratio, name_score=1.0, master_version="M5")
    rest.tables["ice_model_crosswalk"] = [{
        "id": 1, "model_group_id": "toyota-hilux-travo", "canonical_model_id": "toyota-hilux-travo-cab",
        "match_method": "SERIES", "score": series_eval.correlation, "status": "REJECTED", "master_version": "M4",
        "decision_fingerprint": fingerprint, "reason": "admin rejected",
    }]

    summary = matcher.run_match(rest, master_version="M5", review_csv_path=tmp_path / "review.csv")
    assert summary["skipped_unchanged_rejection"] == 1
    assert summary["applied"] == 0
    assert rest.tables["ice_model_crosswalk"][0]["status"] == "REJECTED"


def test_rejected_mapping_is_reevaluated_once_the_master_version_changes(tmp_path):
    rest = _base_rest()
    values = [100.0, 110.0, 120.0, 130.0, 140.0, 150.0]
    rest.tables["ice_dims_model_group"] = [_group("toyota-hilux-travo", "Hilux Travo", "Toyota")]
    rest.tables["ice_reg_trend"] = _ice_series_rows("toyota-hilux-travo", values)
    rest.tables["vehicle_models"] = [_model("toyota-hilux-travo-cab", "Hilux Travo", "toyota")]
    rest.tables["registrations"] = _legacy_rows("toyota-hilux-travo-cab", values)
    rest.tables["ice_model_crosswalk"] = [{
        "id": 1, "model_group_id": "toyota-hilux-travo", "canonical_model_id": "toyota-hilux-travo-cab",
        "match_method": "SERIES", "score": 0.5, "status": "REJECTED", "master_version": "M4",
        "decision_fingerprint": "stale-fingerprint-from-an-older-delivery", "reason": "admin rejected",
    }]

    summary = matcher.run_match(rest, master_version="M5", review_csv_path=tmp_path / "review.csv")
    assert summary["skipped_unchanged_rejection"] == 0
    assert summary["applied"] == 1
    assert rest.tables["ice_model_crosswalk"][0]["status"] == "AUTO"


def test_rejected_mapping_is_reevaluated_when_only_the_ratio_evidence_changed(tmp_path):
    # Regression for PR #188 review round 2: before the fix, the orchestrator zeroed
    # out ratio before hashing, so a real-world ratio change (Ice revised a period's
    # numbers) could never by itself make a REJECTED mapping eligible for review again.
    rest = _base_rest()
    values = [100.0, 110.0, 120.0, 130.0, 140.0, 150.0]
    rest.tables["ice_dims_model_group"] = [_group("toyota-hilux-travo", "Hilux Travo", "Toyota")]
    rest.tables["ice_reg_trend"] = _ice_series_rows("toyota-hilux-travo", values)
    rest.tables["vehicle_models"] = [_model("toyota-hilux-travo-cab", "Hilux Travo", "toyota")]
    rest.tables["registrations"] = _legacy_rows("toyota-hilux-travo-cab", values)

    series_eval = xwalk.evaluate_series(values, values)
    stale_fingerprint = xwalk.decision_fingerprint(
        model_group_id="toyota-hilux-travo", canonical_model_id="toyota-hilux-travo-cab",
        correlation=series_eval.correlation, ratio=(series_eval.ratio or 0) + 1.0,  # only the ratio is wrong
        name_score=1.0, master_version="M5")
    rest.tables["ice_model_crosswalk"] = [{
        "id": 1, "model_group_id": "toyota-hilux-travo", "canonical_model_id": "toyota-hilux-travo-cab",
        "match_method": "SERIES", "score": series_eval.correlation, "status": "REJECTED", "master_version": "M5",
        "decision_fingerprint": stale_fingerprint, "reason": "admin rejected",
    }]

    summary = matcher.run_match(rest, master_version="M5", review_csv_path=tmp_path / "review.csv")
    assert summary["skipped_unchanged_rejection"] == 0
    assert summary["applied"] == 1


def test_rejected_mapping_is_reevaluated_when_only_the_name_score_evidence_changed(tmp_path):
    # Same regression, isolating name_score instead of ratio.
    rest = _base_rest()
    values = [100.0, 110.0, 120.0, 130.0, 140.0, 150.0]
    rest.tables["ice_dims_model_group"] = [_group("toyota-hilux-travo", "Hilux Travo", "Toyota")]
    rest.tables["ice_reg_trend"] = _ice_series_rows("toyota-hilux-travo", values)
    rest.tables["vehicle_models"] = [_model("toyota-hilux-travo-cab", "Hilux Travo", "toyota")]
    rest.tables["registrations"] = _legacy_rows("toyota-hilux-travo-cab", values)

    series_eval = xwalk.evaluate_series(values, values)
    stale_fingerprint = xwalk.decision_fingerprint(
        model_group_id="toyota-hilux-travo", canonical_model_id="toyota-hilux-travo-cab",
        correlation=series_eval.correlation, ratio=series_eval.ratio,
        name_score=0.0,  # the real name similarity for this fixture is 1.0 -- only this is wrong
        master_version="M5")
    rest.tables["ice_model_crosswalk"] = [{
        "id": 1, "model_group_id": "toyota-hilux-travo", "canonical_model_id": "toyota-hilux-travo-cab",
        "match_method": "SERIES", "score": series_eval.correlation, "status": "REJECTED", "master_version": "M5",
        "decision_fingerprint": stale_fingerprint, "reason": "admin rejected",
    }]

    summary = matcher.run_match(rest, master_version="M5", review_csv_path=tmp_path / "review.csv")
    assert summary["skipped_unchanged_rejection"] == 0
    assert summary["applied"] == 1


# ---------------------------------------------------------------------------
# Candidate ranking (PR #188 review round 2): never compare a SERIES
# correlation against a NAME name_score directly.
# ---------------------------------------------------------------------------

def test_a_strong_series_auto_candidate_beats_a_weak_series_name_only_candidate(tmp_path):
    rest = _base_rest()
    ice_values = [100.0, 110.0, 120.0, 130.0, 140.0, 150.0]
    rest.tables["ice_dims_model_group"] = [_group("toyota-hilux-travo", "Hilux Travo", "Toyota")]
    rest.tables["ice_reg_trend"] = _ice_series_rows("toyota-hilux-travo", ice_values)
    rest.tables["vehicle_models"] = [
        _model("candidate-a", "Hilux Travo", "toyota"),   # strong series, name >= 0.8 -> AUTO-eligible
        _model("candidate-b", "Hilux Travo", "toyota"),   # weak series, name 1.0 -> NAME-only PROPOSED
    ]
    rest.tables["registrations"] = (
        _legacy_rows("candidate-a", ice_values)
        + _legacy_rows("candidate-b", [5.0, 90.0, 3.0, 150.0, 20.0, 60.0]))

    summary = matcher.run_match(rest, master_version="M5", review_csv_path=tmp_path / "review.csv")
    assert summary["applied"] == 1
    rows = {r["canonical_model_id"]: r for r in rest.tables["ice_model_crosswalk"]}
    assert "candidate-a" in rows and rows["candidate-a"]["status"] == "AUTO"
    assert "candidate-b" not in rows


def test_series_proposed_beats_name_only_proposed_despite_a_numerically_higher_name_score(tmp_path):
    rest = _base_rest()
    ice_values = [100.0, 110.0, 120.0, 130.0, 140.0, 150.0]
    rest.tables["ice_dims_model_group"] = [_group("toyota-hilux-travo", "Hilux Travo", "Toyota")]
    rest.tables["ice_reg_trend"] = _ice_series_rows("toyota-hilux-travo", ice_values)
    rest.tables["vehicle_models"] = [
        # Strong series but a name that shares nothing with "Hilux Travo" -- PROPOSED/SERIES.
        _model("candidate-a", "Zephyr Nomad Expedition", "toyota"),
        # Weak series but an exact name match (name_score 1.0, numerically higher than
        # candidate-a's name score) -- PROPOSED/NAME. Must still lose to candidate-a.
        _model("candidate-b", "Hilux Travo", "toyota"),
    ]
    rest.tables["registrations"] = (
        _legacy_rows("candidate-a", ice_values)
        + _legacy_rows("candidate-b", [5.0, 90.0, 3.0, 150.0, 20.0, 60.0]))

    summary = matcher.run_match(rest, master_version="M5", review_csv_path=tmp_path / "review.csv")
    assert summary["applied"] == 1
    rows = {r["canonical_model_id"]: r for r in rest.tables["ice_model_crosswalk"]}
    assert rows["candidate-a"]["status"] == "PROPOSED"
    assert rows["candidate-a"]["match_method"] == "SERIES"
    assert "candidate-b" not in rows


# ---------------------------------------------------------------------------
# Maxus/Mifa model-name alias, end to end (§14.2 known trap)
# ---------------------------------------------------------------------------

def test_maxus_7_auto_matches_mifa_7_with_a_strong_series(tmp_path):
    rest = _base_rest()
    rest.tables["ice_brand_aliases"] = [
        {"brand": "MG Maxus", "alias_group": "maxus_mifa"}, {"brand": "MAXUS", "alias_group": "maxus_mifa"}]
    rest.tables["vehicle_brands"] = [_brand("maxus", "MAXUS")]
    values = [100.0, 110.0, 120.0, 130.0, 140.0, 150.0]
    rest.tables["ice_dims_model_group"] = [_group("mg-maxus-7", "7", "MG Maxus")]
    rest.tables["ice_reg_trend"] = _ice_series_rows("mg-maxus-7", values)
    rest.tables["vehicle_models"] = [_model("maxus-mifa-7", "MAXUS Mifa 7", "maxus")]
    rest.tables["registrations"] = _legacy_rows("maxus-mifa-7", values)

    summary = matcher.run_match(rest, master_version="M5", review_csv_path=tmp_path / "review.csv")
    assert summary["applied"] == 1
    assert rest.tables["ice_model_crosswalk"][0]["status"] == "AUTO"


def test_maxus_9_auto_matches_mifa_9_with_a_strong_series(tmp_path):
    rest = _base_rest()
    rest.tables["ice_brand_aliases"] = [
        {"brand": "MG Maxus", "alias_group": "maxus_mifa"}, {"brand": "MAXUS", "alias_group": "maxus_mifa"}]
    rest.tables["vehicle_brands"] = [_brand("maxus", "MAXUS")]
    values = [100.0, 110.0, 120.0, 130.0, 140.0, 150.0]
    rest.tables["ice_dims_model_group"] = [_group("mg-maxus-9", "9", "MG Maxus")]
    rest.tables["ice_reg_trend"] = _ice_series_rows("mg-maxus-9", values)
    rest.tables["vehicle_models"] = [_model("maxus-mifa-9", "MAXUS Mifa 9", "maxus")]
    rest.tables["registrations"] = _legacy_rows("maxus-mifa-9", values)

    summary = matcher.run_match(rest, master_version="M5", review_csv_path=tmp_path / "review.csv")
    assert summary["applied"] == 1
    assert rest.tables["ice_model_crosswalk"][0]["status"] == "AUTO"


def test_maxus_7_does_not_auto_match_mifa_9_with_a_weak_series(tmp_path):
    rest = _base_rest()
    rest.tables["ice_brand_aliases"] = [
        {"brand": "MG Maxus", "alias_group": "maxus_mifa"}, {"brand": "MAXUS", "alias_group": "maxus_mifa"}]
    rest.tables["vehicle_brands"] = [_brand("maxus", "MAXUS")]
    rest.tables["ice_dims_model_group"] = [_group("mg-maxus-7", "7", "MG Maxus")]
    rest.tables["ice_reg_trend"] = _ice_series_rows("mg-maxus-7", [10.0, 20.0, 15.0, 25.0, 12.0, 30.0])
    rest.tables["vehicle_models"] = [_model("maxus-mifa-9", "MAXUS Mifa 9", "maxus")]
    rest.tables["registrations"] = _legacy_rows("maxus-mifa-9", [12.0, 3.0, 40.0, 5.0, 60.0, 8.0])

    summary = matcher.run_match(rest, master_version="M5", review_csv_path=tmp_path / "review.csv")
    # The weak series blocks AUTO regardless of how similar "mifa 7"/"mifa 9" look as
    # short strings -- a PROPOSED row (for human review) is an acceptable outcome, an
    # AUTO row is not.
    active_rows = [r for r in rest.tables["ice_model_crosswalk"] if r["status"] == "AUTO"]
    assert active_rows == []
    for row in rest.tables["ice_model_crosswalk"]:
        assert row["status"] != "AUTO"


# ---------------------------------------------------------------------------
# Protected rows (APPROVED / ADMIN) are never overwritten by the matcher
# ---------------------------------------------------------------------------

def test_approved_row_is_never_touched_by_the_matcher(tmp_path):
    rest = _base_rest()
    values = [100.0, 110.0, 120.0, 130.0, 140.0, 150.0]
    rest.tables["ice_dims_model_group"] = [_group("toyota-hilux-travo", "Hilux Travo", "Toyota")]
    rest.tables["ice_reg_trend"] = _ice_series_rows("toyota-hilux-travo", values)
    rest.tables["vehicle_models"] = [_model("toyota-hilux-travo-cab", "Hilux Travo", "toyota")]
    rest.tables["registrations"] = _legacy_rows("toyota-hilux-travo-cab", values)
    rest.tables["ice_model_crosswalk"] = [{
        "id": 1, "model_group_id": "toyota-hilux-travo", "canonical_model_id": "toyota-hilux-travo-cab",
        "match_method": "ADMIN", "score": None, "status": "APPROVED", "master_version": "M1",
        "decision_fingerprint": None, "reason": "admin set this by hand",
    }]

    summary = matcher.run_match(rest, master_version="M5", review_csv_path=tmp_path / "review.csv")
    # The only TDR candidate for this group is already an approved mapping, so there is
    # no *other* candidate left to evaluate -- the matcher never attempts to touch it.
    assert summary["applied"] == 0
    assert summary["no_candidate"] == 1
    row = rest.tables["ice_model_crosswalk"][0]
    assert row["status"] == "APPROVED" and row["match_method"] == "ADMIN"


# ---------------------------------------------------------------------------
# Discovery (new / provisional groups)
# ---------------------------------------------------------------------------

def test_a_first_seen_group_is_flagged_new_and_recorded_in_the_ledger(tmp_path):
    rest = _base_rest()
    rest.tables["ice_dims_model_group"] = [_group("brand-new-group", "Something", "Toyota")]
    rest.tables["ice_reg_trend"] = []
    rest.tables["vehicle_models"] = []
    rest.tables["registrations"] = []

    summary = matcher.run_match(rest, master_version="M5", review_csv_path=tmp_path / "review.csv")
    assert {"model_group_id": "brand-new-group", "flags": ["NEW"]} in summary["discovery"]
    assert any(r["model_group_id"] == "brand-new-group" for r in rest.tables["ice_known_model_groups"])


def test_an_already_known_group_is_not_flagged_new_on_the_next_run(tmp_path):
    rest = _base_rest()
    rest.tables["ice_dims_model_group"] = [_group("already-known", "Something", "Toyota")]
    rest.tables["ice_known_model_groups"] = [{"model_group_id": "already-known", "first_seen_master_version": "M4"}]
    rest.tables["ice_reg_trend"] = []
    rest.tables["vehicle_models"] = []
    rest.tables["registrations"] = []

    summary = matcher.run_match(rest, master_version="M5", review_csv_path=tmp_path / "review.csv")
    assert summary["discovery"] == []


def test_a_provisional_group_is_flagged_even_if_already_known(tmp_path):
    rest = _base_rest()
    rest.tables["ice_dims_model_group"] = [_group("toyota-camry__provisional", "Camry (new)", "Toyota")]
    rest.tables["ice_known_model_groups"] = [
        {"model_group_id": "toyota-camry__provisional", "first_seen_master_version": "M4"}]
    rest.tables["ice_reg_trend"] = []
    rest.tables["vehicle_models"] = []
    rest.tables["registrations"] = []

    summary = matcher.run_match(rest, master_version="M5", review_csv_path=tmp_path / "review.csv")
    assert {"model_group_id": "toyota-camry__provisional", "flags": ["PROVISIONAL"]} in summary["discovery"]


# ---------------------------------------------------------------------------
# Review sheet
# ---------------------------------------------------------------------------

def test_a_proposed_decision_is_written_to_the_review_csv(tmp_path):
    rest = _base_rest()
    # Uncorrelated series -> not strong -> falls to name-only -> PROPOSED.
    ice_values = [100.0, 50.0, 200.0, 10.0, 80.0, 30.0]
    legacy_values = [5.0, 90.0, 3.0, 150.0, 20.0, 60.0]
    rest.tables["ice_dims_model_group"] = [_group("toyota-hilux-travo", "Hilux Travo", "Toyota")]
    rest.tables["ice_reg_trend"] = _ice_series_rows("toyota-hilux-travo", ice_values)
    rest.tables["vehicle_models"] = [_model("toyota-hilux-travo-cab", "Hilux Travo", "toyota")]
    rest.tables["registrations"] = _legacy_rows("toyota-hilux-travo-cab", legacy_values)

    review_path = tmp_path / "review.csv"
    summary = matcher.run_match(rest, master_version="M5", review_csv_path=review_path)
    assert summary["review_rows"] == 1

    with review_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["model_group_id"] == "toyota-hilux-travo"
    assert rows[0]["proposed_canonical_model_id"] == "toyota-hilux-travo-cab"
    assert rows[0]["proposed_status"] == "PROPOSED"


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def test_fetch_all_pages_through_results_past_a_single_page(monkeypatch):
    monkeypatch.setattr(matcher, "PAGE_SIZE", 2)
    rest = FakeRest()
    rest.tables["ice_dims_model_group"] = [
        _group(f"group-{i}", f"Model {i}", "Toyota") for i in range(5)]
    rows = matcher.fetch_ice_groups(rest)
    assert len(rows) == 5
    assert [r["model_group_id"] for r in rows] == [f"group-{i}" for i in range(5)]


# ---------------------------------------------------------------------------
# id_changes.csv dispatch
# ---------------------------------------------------------------------------

def test_process_id_changes_csv_dispatches_one_rpc_call_per_row():
    rest = FakeRest()
    rest.tables["ice_model_crosswalk"] = [{
        "id": 1, "model_group_id": "old-id", "canonical_model_id": "toyota-hilux-travo-cab",
        "match_method": "SERIES", "score": 0.99, "status": "AUTO", "master_version": "M4",
        "decision_fingerprint": "f", "reason": "r",
    }]
    csv_text = (
        "old_model_group_id,new_model_group_id,reg_moved_all_periods,share_of_old_pct,type\n"
        "old-id,new-id,true,100,เปลี่ยนรหัส\n"
    )
    results = matcher.process_id_changes_csv(rest, csv_text.encode("utf-8-sig"), master_version="M5")
    assert len(results) == 1
    assert results[0]["moved"] == 1
    assert rest.tables["ice_model_crosswalk"][0]["model_group_id"] == "new-id"


# ---------------------------------------------------------------------------
# --check-live-import: the read-only preflight the R6 workflow calls
# ---------------------------------------------------------------------------

class ImportsRest:
    """Answers only the one GET the preflight may make; records every call."""

    def __init__(self, rows):
        self.rows = rows
        self.calls: list[tuple] = []

    def __call__(self, method, path, payload=None, *, prefer=None):
        self.calls.append((method, path, payload))
        assert method == "GET" and path.startswith("ice_package_imports?"), (method, path)
        return self.rows


def test_check_live_import_accepts_the_matching_master_version_with_one_read():
    rest = ImportsRest([{"master_version": "7.0", "period": "2569-09", "package_version": 3}])
    assert matcher.check_live_import(rest, master_version="7.0")["period"] == "2569-09"
    assert [call[0] for call in rest.calls] == ["GET"]  # read-only: a single GET, no write


def test_check_live_import_refuses_another_master_version_or_no_import():
    import pytest

    with pytest.raises(matcher.LiveImportMismatch, match="expected master_version '7.0'"):
        matcher.check_live_import(
            ImportsRest([{"master_version": "6.0", "period": "2569-08", "package_version": 1}]),
            master_version="7.0")
    with pytest.raises(matcher.LiveImportMismatch, match="nothing has been imported"):
        matcher.check_live_import(ImportsRest([]), master_version="7.0")


def test_check_live_import_cli_exit_codes_and_it_needs_no_review_csv(monkeypatch, capsys):
    ok = ImportsRest([{"master_version": "7.0", "period": "2569-09", "package_version": 3}])
    monkeypatch.setattr(matcher, "_request", ok)
    assert matcher.main(["--check-live-import", "--master-version", "7.0"]) == 0
    assert '"live_import"' in capsys.readouterr().out

    monkeypatch.setattr(matcher, "_request", ImportsRest([{"master_version": "6.0"}]))
    assert matcher.main(["--check-live-import", "--master-version", "7.0"]) == 1
    assert capsys.readouterr().out.startswith("INVALID:")

    monkeypatch.setattr(matcher, "_request", ImportsRest([]))
    assert matcher.main(["--check-live-import", "--master-version", "7.0"]) == 1


def test_the_preflight_mode_cannot_be_combined_with_a_writing_mode():
    import pytest

    with pytest.raises(SystemExit) as caught:
        matcher.main(["--check-live-import", "--match", "--master-version", "7.0"])
    assert caught.value.code == 2
