from __future__ import annotations

import json

import pytest

from tools.price_coverage_backfill import (
    EvidenceTier,
    GradeClassification,
    GradeEvidence,
    LineupStatus,
    Manifest,
    ModelManifestEntry,
    TerminalState,
    build_append_price_batch,
    classify_grade,
    discover_media_grade,
    load_manifest_dict,
)
from vehreg.catalog import Model
from vehreg.input_pipeline import CanonicalInputBatch
from vehreg.price_fetch import HttpResponse
from vehreg.price_match import TrimMatchMethod, TrimMatchResult, TrimMatchState
from vehreg.pricing import PriceType


J5_MODEL_ID = "jaecoo.jaecoo_5_ev"
J5_ULTRA_TRIM = "jaecoo.jaecoo_5_ev.j5.trim.ultra_bev"


def _evidence(*, amount_thb=699_000, price_type=PriceType.LIST_PRICE,
              tier=EvidenceTier.OEM_CURRENT_MODEL_PAGE, semantics_clear=True,
              raw_grade="ULTRA") -> GradeEvidence:
    return GradeEvidence(
        raw_grade=raw_grade, amount_thb=amount_thb, extracted_price_type=price_type,
        evidence_tier=tier, source_ref="https://example.com", observed_at="2026-09-24",
        semantics_clear=semantics_clear,
    )


def _match(*, state=TrimMatchState.EXACT, method=TrimMatchMethod.EXACT_NAME,
           trim_id=J5_ULTRA_TRIM) -> TrimMatchResult:
    resolved = trim_id if state is TrimMatchState.EXACT else None
    return TrimMatchResult(
        state=state, model_id=J5_MODEL_ID, trim_id=resolved,
        candidate_ids=(trim_id,) if trim_id else (), method=method,
        reason="test fixture", normalized_trim_raw="ULTRA",
    )


# ------------------------------------------------------- classify_grade


def test_no_evidence_tier_is_no_source():
    evidence = _evidence(tier=EvidenceTier.NONE, amount_thb=None, price_type=None)
    result = classify_grade(evidence, None, existing_list_price_thb=None)
    assert result.terminal_state is TerminalState.NO_SOURCE


def test_unclear_semantics_is_semantic_blocked():
    evidence = _evidence(semantics_clear=False)
    result = classify_grade(evidence, _match(), existing_list_price_thb=None)
    assert result.terminal_state is TerminalState.SEMANTIC_BLOCKED


def test_missing_price_type_is_semantic_blocked():
    evidence = _evidence(price_type=None)
    result = classify_grade(evidence, _match(), existing_list_price_thb=None)
    assert result.terminal_state is TerminalState.SEMANTIC_BLOCKED


def test_unknown_price_type_is_semantic_blocked():
    evidence = _evidence(price_type=PriceType.UNKNOWN)
    result = classify_grade(evidence, _match(), existing_list_price_thb=None)
    assert result.terminal_state is TerminalState.SEMANTIC_BLOCKED


@pytest.mark.parametrize("price_type", [
    PriceType.CAMPAIGN_PRICE, PriceType.FINANCE_PRICE, PriceType.ESTIMATED_PRICE,
    PriceType.DEALER_PRICE, PriceType.ECO_STICKER_PRICE, PriceType.INTRODUCTORY_PRICE,
])
def test_non_list_price_type_is_campaign_only_never_price_conflict(price_type):
    evidence = _evidence(price_type=price_type)
    result = classify_grade(evidence, _match(), existing_list_price_thb=650_000)
    assert result.terminal_state is TerminalState.CAMPAIGN_ONLY


def test_no_match_is_identity_blocked():
    evidence = _evidence()
    result = classify_grade(evidence, None, existing_list_price_thb=None)
    assert result.terminal_state is TerminalState.IDENTITY_BLOCKED


def test_ambiguous_match_is_identity_blocked():
    evidence = _evidence()
    match = _match(state=TrimMatchState.AMBIGUOUS, method=TrimMatchMethod.AMBIGUOUS_PARTIAL,
                   trim_id=None)
    result = classify_grade(evidence, match, existing_list_price_thb=None)
    assert result.terminal_state is TerminalState.IDENTITY_BLOCKED


def test_unmapped_match_is_identity_blocked():
    evidence = _evidence()
    match = _match(state=TrimMatchState.UNMAPPED, method=TrimMatchMethod.NO_GRADE_MATCH,
                   trim_id=None)
    result = classify_grade(evidence, match, existing_list_price_thb=None)
    assert result.terminal_state is TerminalState.IDENTITY_BLOCKED


def test_partial_grade_match_is_identity_blocked_even_when_state_exact():
    """A PARTIAL_GRADE match that uniquely resolves to one trim is still
    inference, not identity -- the architecture explicitly forbids treating
    it as safe to auto-write, unlike EXACT_NAME/EXACT_ALIAS."""
    evidence = _evidence()
    match = _match(method=TrimMatchMethod.PARTIAL_GRADE)
    result = classify_grade(evidence, match, existing_list_price_thb=None)
    assert result.terminal_state is TerminalState.IDENTITY_BLOCKED


@pytest.mark.parametrize("method", [TrimMatchMethod.EXACT_NAME, TrimMatchMethod.EXACT_ALIAS])
def test_exact_match_with_no_existing_price_and_strong_evidence_is_auto_ready(method):
    evidence = _evidence()
    match = _match(method=method)
    result = classify_grade(evidence, match, existing_list_price_thb=None)
    assert result.terminal_state is TerminalState.AUTO_READY


def test_existing_price_equal_is_complete_not_auto_ready():
    evidence = _evidence(amount_thb=699_000)
    result = classify_grade(evidence, _match(), existing_list_price_thb=699_000)
    assert result.terminal_state is TerminalState.COMPLETE


def test_existing_price_different_is_price_conflict_never_auto_corrected():
    evidence = _evidence(amount_thb=699_000)
    result = classify_grade(evidence, _match(), existing_list_price_thb=650_000)
    assert result.terminal_state is TerminalState.PRICE_CONFLICT
    assert result.existing_list_price_thb == 650_000


def test_media_two_agree_tier_can_reach_auto_ready():
    evidence = _evidence(tier=EvidenceTier.MEDIA_TWO_AGREE)
    result = classify_grade(evidence, _match(), existing_list_price_thb=None)
    assert result.terminal_state is TerminalState.AUTO_READY


# ------------------------------------------------- current_retail_model_complete


def _classification(terminal_state, *, applied=False, method=TrimMatchMethod.EXACT_NAME,
                    trim_id=J5_ULTRA_TRIM, amount_thb=699_000) -> GradeClassification:
    evidence = _evidence(amount_thb=amount_thb)
    match = _match(method=method, trim_id=trim_id)
    return GradeClassification(
        evidence=evidence, match=match, terminal_state=terminal_state,
        existing_list_price_thb=None, applied=applied,
    )


def test_model_complete_false_when_lineup_not_exhaustive():
    entry = ModelManifestEntry(
        model_id=J5_MODEL_ID, lineup_status=LineupStatus.PARTIAL,
        evidence_tier=EvidenceTier.OEM_CURRENT_MODEL_PAGE, lineup_source={},
        grades=[_classification(TerminalState.COMPLETE)],
    )
    assert entry.current_retail_model_complete is False


def test_model_complete_false_when_no_grades_discovered():
    entry = ModelManifestEntry(
        model_id=J5_MODEL_ID, lineup_status=LineupStatus.EXHAUSTIVE,
        evidence_tier=EvidenceTier.OEM_CURRENT_MODEL_PAGE, lineup_source={}, grades=[],
    )
    assert entry.current_retail_model_complete is False


def test_model_complete_false_when_any_grade_is_not_an_exact_method():
    entry = ModelManifestEntry(
        model_id=J5_MODEL_ID, lineup_status=LineupStatus.EXHAUSTIVE,
        evidence_tier=EvidenceTier.OEM_CURRENT_MODEL_PAGE, lineup_source={},
        grades=[
            _classification(TerminalState.COMPLETE),
            _classification(TerminalState.IDENTITY_BLOCKED, method=TrimMatchMethod.PARTIAL_GRADE),
        ],
    )
    assert entry.current_retail_model_complete is False


def test_model_complete_false_when_auto_ready_grade_not_yet_applied():
    entry = ModelManifestEntry(
        model_id=J5_MODEL_ID, lineup_status=LineupStatus.EXHAUSTIVE,
        evidence_tier=EvidenceTier.OEM_CURRENT_MODEL_PAGE, lineup_source={},
        grades=[_classification(TerminalState.AUTO_READY, applied=False)],
    )
    assert entry.current_retail_model_complete is False


def test_model_complete_true_when_exhaustive_and_every_grade_has_a_current_price():
    entry = ModelManifestEntry(
        model_id=J5_MODEL_ID, lineup_status=LineupStatus.EXHAUSTIVE,
        evidence_tier=EvidenceTier.OEM_CURRENT_MODEL_PAGE, lineup_source={},
        grades=[
            _classification(TerminalState.COMPLETE, trim_id=J5_ULTRA_TRIM),
            _classification(TerminalState.AUTO_READY, applied=True,
                            trim_id="jaecoo.jaecoo_5_ev.j5.trim.max_plus_bev"),
        ],
    )
    assert entry.current_retail_model_complete is True


def test_model_complete_never_uses_the_full_canonical_catalog_as_denominator():
    """Section 5 of the approved architecture: completeness is scoped to this
    model's own discovered lineup, never to the global 1,502-trim catalog."""
    entry = ModelManifestEntry(
        model_id=J5_MODEL_ID, lineup_status=LineupStatus.EXHAUSTIVE,
        evidence_tier=EvidenceTier.OEM_CURRENT_MODEL_PAGE, lineup_source={},
        grades=[_classification(TerminalState.COMPLETE, trim_id=J5_ULTRA_TRIM)],
    )
    assert entry.current_retail_model_complete is True


# --------------------------------------------------------------- Manifest


def test_manifest_roundtrip_and_summary(tmp_path):
    entry = ModelManifestEntry(
        model_id=J5_MODEL_ID, lineup_status=LineupStatus.EXHAUSTIVE,
        evidence_tier=EvidenceTier.OEM_CURRENT_MODEL_PAGE,
        lineup_source={"url": "https://example.com"},
        grades=[_classification(TerminalState.AUTO_READY, applied=False)],
    )
    manifest = Manifest(generated_at="2026-09-24", models=[entry])
    out = tmp_path / "manifest.json"
    manifest.save(out)

    loaded = load_manifest_dict(out)
    assert loaded["schema_version"] == 1
    assert loaded["summary"]["AUTO_READY"] == 1
    assert loaded["summary"]["total_models"] == 1
    assert loaded["models"][0]["grades"][0]["trim_id"] == J5_ULTRA_TRIM


def test_load_manifest_dict_rejects_unsupported_schema_version(tmp_path):
    out = tmp_path / "manifest.json"
    out.write_text(json.dumps({"schema_version": 2}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_manifest_dict(out)


# ------------------------------------------------------ build_append_price_batch


def _manifest_dict_with_grades(grades: list[dict]) -> dict:
    return {"models": [{"evidence_tier": "OEM_CURRENT_MODEL_PAGE", "grades": grades}]}


def test_build_append_price_batch_only_includes_unapplied_auto_ready_rows():
    manifest_dict = _manifest_dict_with_grades([
        {"terminal_state": "AUTO_READY", "applied": False, "trim_id": "trim-a",
         "amount_thb": 699_000, "observed_at": "2026-09-24",
         "source_ref": "https://example.com"},
        {"terminal_state": "AUTO_READY", "applied": True, "trim_id": "trim-b",
         "amount_thb": 500_000},
        {"terminal_state": "COMPLETE", "applied": False, "trim_id": "trim-c",
         "amount_thb": 400_000},
        {"terminal_state": "AUTO_READY", "applied": False, "trim_id": None,
         "amount_thb": 100_000},
    ])
    batch = build_append_price_batch(manifest_dict, year=2026)
    assert batch is not None
    assert [c["canonical_id"] for c in batch["commands"]] == ["trim-a"]
    assert batch["commands"][0]["operation"] == "APPEND_PRICE"
    assert batch["commands"][0]["payload"]["amount_thb"] == 699_000


def test_build_append_price_batch_none_when_nothing_unapplied():
    manifest_dict = _manifest_dict_with_grades([
        {"terminal_state": "COMPLETE", "applied": False, "trim_id": "trim-a",
         "amount_thb": 400_000},
    ])
    assert build_append_price_batch(manifest_dict, year=2026) is None


def test_build_append_price_batch_parses_as_a_valid_canonical_input_batch():
    """Regression: an early draft of this batch omitted ``source``, which
    CanonicalInputBatch.from_dict requires to resolve source_kind -- every
    --apply run would have failed immediately with "unsupported source kind
    ''". This exercises the exact same parser --apply calls in production."""
    manifest_dict = _manifest_dict_with_grades([
        {"terminal_state": "AUTO_READY", "applied": False, "trim_id": J5_ULTRA_TRIM,
         "amount_thb": 699_000, "observed_at": "2026-09-24",
         "source_ref": "https://example.com"},
    ])
    batch = build_append_price_batch(manifest_dict, year=2026)
    parsed = CanonicalInputBatch.from_dict(batch)
    assert parsed.source_kind in {"ADMIN", "ECO", "OEM", "MEDIA", "PRICE_HARVEST", "MIGRATION", "API"}
    assert len(parsed.commands) == 1
    assert parsed.commands[0]["canonical_id"] == J5_ULTRA_TRIM


# ------------------------------------------------------------- discover_media_grade


class _FakeMediaTransport:
    """Maps a host substring to canned WordPress /wp-json/wp/v2/search hits."""

    def __init__(self, hits_by_host: dict[str, list[dict]]):
        self._hits_by_host = hits_by_host

    def fetch(self, url, *, headers, timeout):
        for host, hits in self._hits_by_host.items():
            if host in url:
                return HttpResponse(status=200, url=url, headers={},
                                    body=json.dumps(hits).encode("utf-8"))
        return HttpResponse(status=404, url=url, headers={}, body=b"[]")


def _official_hit(amount_thb: int) -> dict:
    return {
        "title": f"JAECOO 5 EV ราคาอย่างเป็นทางการ {amount_thb:,} บาท",
        "url": "https://example.com/j5-price",
    }


def test_discover_media_grade_requires_both_sources_to_agree():
    model = Model(id=J5_MODEL_ID, brand_id="JAECOO", name_en="JAECOO 5 EV")
    transport = _FakeMediaTransport({
        "autolifethailand.tv": [_official_hit(699_000)],
        "headlightmag.com": [_official_hit(699_000)],
    })
    evidence = discover_media_grade(model, transport=transport)
    assert evidence is not None
    assert evidence.amount_thb == 699_000
    assert evidence.evidence_tier is EvidenceTier.MEDIA_TWO_AGREE


def test_discover_media_grade_returns_none_on_disagreement():
    model = Model(id=J5_MODEL_ID, brand_id="JAECOO", name_en="JAECOO 5 EV")
    transport = _FakeMediaTransport({
        "autolifethailand.tv": [_official_hit(699_000)],
        "headlightmag.com": [_official_hit(650_000)],
    })
    assert discover_media_grade(model, transport=transport) is None


def test_discover_media_grade_returns_none_with_only_one_source_confirming():
    model = Model(id=J5_MODEL_ID, brand_id="JAECOO", name_en="JAECOO 5 EV")
    transport = _FakeMediaTransport({
        "autolifethailand.tv": [_official_hit(699_000)],
        # headlightmag.com: no matching hits at all
    })
    assert discover_media_grade(model, transport=transport) is None


def test_discover_media_grade_ignores_used_and_predicted_titles():
    model = Model(id=J5_MODEL_ID, brand_id="JAECOO", name_en="JAECOO 5 EV")
    bad_hit = {
        "title": "JAECOO 5 EV มือสอง ราคาพิเศษ 500,000 บาท",
        "url": "https://example.com/used",
    }
    transport = _FakeMediaTransport({
        "autolifethailand.tv": [bad_hit],
        "headlightmag.com": [bad_hit],
    })
    assert discover_media_grade(model, transport=transport) is None
