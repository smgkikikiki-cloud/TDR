from __future__ import annotations

import json
from pathlib import Path

import pytest

from vehreg.input_pipeline import CanonicalInputError, CanonicalInputPipeline
from vehreg.retail_lifecycle_review import (
    RetailLifecycleReviewError,
    load_trim_lifecycle_decisions,
    upsert_trim_lifecycle_disposition,
)

YEAR = 2026
MODEL_ID = "jaecoo.jaecoo_5_ev"
GEN_ID = MODEL_ID + ".j5"
TRIM_ID = GEN_ID + ".trim.ultra_bev"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _seed(tmp_path: Path, *, parent_status: str = "CURRENT") -> Path:
    data = tmp_path / "data"
    _write_json(data / str(YEAR) / "models" / "jaecoo.json", {
        "brand": {
            "id": "jaecoo", "name_en": "Jaecoo", "name_th": "เจคู",
            "brand_segment": "MASS", "oem_group": "Chery", "brand_origin": "CN",
            "trim_detail": True, "aliases": [],
        },
        "models": [{
            "id": "jaecoo_5_ev", "name_en": "Jaecoo 5 EV", "name_th": "เจคู 5",
            "nameplate": "Jaecoo 5", "body_type": "CROSSOVER",
            "cab_type": "NOT_APPLICABLE", "registration_type": "",
            "market_scope": "CORE", "aliases": [],
            "retail_status": parent_status,
            "retail_checked_at": "2026-09-11",
            "retail_source": "https://example.test/j5/model",
            "generations": [{
                "code": "J5", "segment": "B", "seats": 5,
                "launched": "2025-08-19", "ended": None,
                "variants": [{
                    "id": "bev_cbu", "name": "58.9 kWh BEV CBU", "powertrain": "BEV",
                    "drivetrain": "FWD", "engine_cc": None, "battery_kwh": 58.9,
                    "price_thb": None, "price_min_thb": None, "price_max_thb": None,
                    "import_type": "CBU", "origin_country": "CN",
                    "price_note": "retail price lives on MarketTrim", "aliases": [],
                }],
                "trims": [{
                    "id": "ultra_bev", "name": "Ultra", "variant": "58.9 kWh BEV CBU",
                    "powertrain": "BEV", "drivetrain": "FWD", "battery_kwh": 58.9,
                    "seats": 5, "aliases": [],
                    "source_refs": {"oem": ["https://example.test/j5"]},
                }],
            }],
        }],
    })
    _write_json(data / str(YEAR) / "market" / "retail_lifecycle" / "trim_review.json", {
        "schema_version": 1, "decisions": [],
    })
    # Pre-existing canonical audit files expose the historical changed_files bug:
    # a review-only batch must not report these as changed just because they exist.
    state = data / str(YEAR) / "canonical_state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "revisions.jsonl").write_text('{"old":true}\n', encoding="utf-8")
    (state / "outbox.jsonl").write_text('{"old":true}\n', encoding="utf-8")
    _write_json(state / "shadow" / "old.json", {"old": True})
    return data


def _batch(action: str = "current", *, actor: str = "retail-reviewer", batch_id: str = "trim-current") -> dict:
    payload = {
        "trim_id": TRIM_ID,
        "action": action,
        "notes": "official Thai lineup evidence",
    }
    if action != "reopen":
        payload["source_ref"] = "https://example.test/j5/official"
    return {
        "schema_version": 1,
        "batch_id": batch_id,
        "year": YEAR,
        "source": {"kind": "ADMIN", "ref": "https://example.test/j5/official"},
        "actor": actor,
        "reason": "retail lifecycle review",
        "submitted_at": "2026-09-11T05:00:00+00:00",
        "commands": [{
            "operation": "UPSERT_TRIM_RETAIL_LIFECYCLE_REVIEW",
            "payload": payload,
        }],
    }


def test_current_review_is_sidecar_only_and_does_not_fake_canonical_audit_changes(tmp_path: Path):
    data = _seed(tmp_path)
    result = CanonicalInputPipeline(data).apply(_batch())
    assert result.status == "APPLIED"
    assert any(path.endswith("market/retail_lifecycle/trim_review.json") for path in result.changed_files)
    assert not any(path.endswith("canonical_state/revisions.jsonl") for path in result.changed_files)
    assert not any(path.endswith("canonical_state/outbox.jsonl") for path in result.changed_files)
    assert not any("canonical_state/shadow/old.json" in path for path in result.changed_files)

    assert load_trim_lifecycle_decisions(data_dir=data, year=YEAR) == [{
        "trim_id": TRIM_ID,
        "status": "CURRENT",
        "reviewer": "retail-reviewer",
        "reviewed_at": "2026-09-11",
        "source_ref": "https://example.test/j5/official",
        "notes": "official Thai lineup evidence",
    }]


def test_historical_then_reopen_clears_human_disposition(tmp_path: Path):
    data = _seed(tmp_path)
    CanonicalInputPipeline(data).apply(_batch("historical", batch_id="trim-historical"))
    assert load_trim_lifecycle_decisions(data_dir=data, year=YEAR)[0]["status"] == "HISTORICAL"
    CanonicalInputPipeline(data).apply(_batch("reopen", batch_id="trim-reopen"))
    assert load_trim_lifecycle_decisions(data_dir=data, year=YEAR) == []


def test_review_rejects_non_human_actor_and_non_admin_source(tmp_path: Path):
    data = _seed(tmp_path)
    with pytest.raises(CanonicalInputError, match="explicit HUMAN actor"):
        CanonicalInputPipeline(data).apply(_batch(actor="agent-proposed"))
    batch = _batch(batch_id="wrong-source")
    batch["source"]["kind"] = "OEM"
    with pytest.raises(CanonicalInputError, match="requires source.kind ADMIN"):
        CanonicalInputPipeline(data).apply(batch)


def test_current_and_historical_require_http_evidence(tmp_path: Path):
    data = _seed(tmp_path)
    batch = _batch()
    batch["commands"][0]["payload"]["source_ref"] = ""
    with pytest.raises(CanonicalInputError, match=r"requires http\(s\) source_ref"):
        CanonicalInputPipeline(data).apply(batch)


def test_non_reopen_review_requires_canonical_current_parent(tmp_path: Path):
    data = _seed(tmp_path, parent_status="UNVERIFIED")
    with pytest.raises(CanonicalInputError, match="parent model must be canonical CURRENT"):
        CanonicalInputPipeline(data).apply(_batch(batch_id="unverified-parent"))
    with pytest.raises(RetailLifecycleReviewError, match="parent model must be canonical CURRENT"):
        upsert_trim_lifecycle_disposition(
            data_dir=data, year=YEAR, trim_id=TRIM_ID, action="historical",
            reviewer="retail-reviewer", reviewed_at="2026-09-11",
            source_ref="https://example.test/evidence", write=True,
        )


def test_reopen_can_clear_stale_decision_after_parent_stops_being_current(tmp_path: Path):
    data = _seed(tmp_path, parent_status="UNVERIFIED")
    _write_json(data / str(YEAR) / "market" / "retail_lifecycle" / "trim_review.json", {
        "schema_version": 1,
        "decisions": [{
            "trim_id": TRIM_ID,
            "status": "CURRENT",
            "reviewer": "retail-reviewer",
            "reviewed_at": "2026-09-10",
            "source_ref": "https://example.test/old-current-evidence",
            "notes": "stale current decision",
        }],
    })
    result = CanonicalInputPipeline(data).apply(_batch("reopen", batch_id="stale-reopen"))
    assert result.status == "APPLIED"
    assert load_trim_lifecycle_decisions(data_dir=data, year=YEAR) == []


def test_direct_store_requires_known_trim_and_human_reviewer(tmp_path: Path):
    data = _seed(tmp_path)
    with pytest.raises(RetailLifecycleReviewError, match="unknown MarketTrim"):
        upsert_trim_lifecycle_disposition(
            data_dir=data, year=YEAR, trim_id="fake.trim", action="current",
            reviewer="retail-reviewer", reviewed_at="2026-09-11",
            source_ref="https://example.test/evidence", write=True,
        )
    with pytest.raises(RetailLifecycleReviewError, match="explicit HUMAN reviewer"):
        upsert_trim_lifecycle_disposition(
            data_dir=data, year=YEAR, trim_id=TRIM_ID, action="current",
            reviewer="system", reviewed_at="2026-09-11",
            source_ref="https://example.test/evidence", write=True,
        )
