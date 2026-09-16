from datetime import date

from tools.media_target_audit import (
    EXCLUDE_HISTORICAL,
    EXCLUDE_NON_MARKET,
    REVIEW_UNVERIFIED,
    TARGET_CURRENT,
    audit_release,
    classify_generation,
)


def _model(status="UNVERIFIED"):
    return {"canonical_id": "brand.model", "brand_id": "brand", "name_en": "Model", "status": status}


def _generation(**overrides):
    row = {"canonical_id": "brand.model.gen1", "model_id": "brand.model", "started": None, "ended": None}
    row.update(overrides)
    return row


def _trim(status):
    return {"generation_id": "brand.model.gen1", "status": status}


def test_current_trim_targets_generation():
    disposition, _ = classify_generation(
        _generation(), model=_model(), trims=[_trim("CURRENT")],
        reconciliation={"status": "CANONICAL"}, as_of=date(2026, 9, 16),
    )
    assert disposition == TARGET_CURRENT


def test_ended_generation_stays_historical_even_with_current_trim():
    disposition, _ = classify_generation(
        _generation(ended="2025-12-31"), model=_model(), trims=[_trim("CURRENT")],
        reconciliation={"status": "CANONICAL"}, as_of=date(2026, 9, 16),
    )
    assert disposition == EXCLUDE_HISTORICAL


def test_non_market_reconciliation_excluded_when_not_current():
    disposition, _ = classify_generation(
        _generation(), model=_model(), trims=[],
        reconciliation={"status": "NON_MARKET"}, as_of=date(2026, 9, 16),
    )
    assert disposition == EXCLUDE_NON_MARKET


def test_unknown_evidence_is_review_not_current():
    disposition, _ = classify_generation(
        _generation(), model=_model(), trims=[_trim("UNVERIFIED")],
        reconciliation={"status": "RECONCILED"}, as_of=date(2026, 9, 16),
    )
    assert disposition == REVIEW_UNVERIFIED


def test_audit_release_emits_only_evidence_backed_target():
    release = {
        "release_id": "vehicle-2026-test",
        "canonical_revision": "abc",
        "source_hash": "hash",
        "as_of": "2026-09-16",
        "models": [
            {"canonical_id": "brand.current", "brand_id": "brand", "name_en": "Current", "status": "UNVERIFIED"},
            {"canonical_id": "brand.old", "brand_id": "brand", "name_en": "Old", "status": "HISTORICAL"},
        ],
        "generations": [
            {"canonical_id": "brand.current.gen1", "model_id": "brand.current", "ended": None},
            {"canonical_id": "brand.old.gen1", "model_id": "brand.old", "ended": None},
        ],
        "market_trims": [
            {"canonical_id": "brand.current.gen1.trim.a", "model_id": "brand.current", "generation_id": "brand.current.gen1", "status": "CURRENT"},
        ],
        "trim_reconciliation": {"models": []},
    }
    report = audit_release(release)
    assert report["counts"] == {EXCLUDE_HISTORICAL: 1, TARGET_CURRENT: 1}
    by_id = {row["generation_id"]: row for row in report["rows"]}
    assert by_id["brand.current.gen1"]["media_disposition"] == TARGET_CURRENT
    assert by_id["brand.old.gen1"]["media_disposition"] == EXCLUDE_HISTORICAL
