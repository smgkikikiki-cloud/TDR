from __future__ import annotations

from inspect import getsource
from types import SimpleNamespace


def test_safe_backfill_aggregates_oem_and_preserves_media_provenance(monkeypatch):
    import importlib
    import tools.price_coverage_backfill as base
    from vehreg.price_match import TrimMatchMethod, TrimMatchResult, TrimMatchState
    from vehreg.price_sources import SourceKind, TargetRole
    from vehreg.pricing import PriceType

    originals = {
        "GradeEvidence": base.GradeEvidence,
        "discover_media_grades": base.discover_media_grades,
        "discover_oem_grades": base.discover_oem_grades,
        "discover_model": base.discover_model,
        "to_dict": base.GradeClassification.to_dict,
    }
    try:
        follow = importlib.import_module("tools.price_coverage_backfill_safe")
        # Force a reload so this test is deterministic even if another test imported it.
        follow = importlib.reload(follow)

        targets = {
            "a": SimpleNamespace(
                id="a", source_id="oem", url="https://oem.example/a",
                role=TargetRole.CURRENT_MODEL_PAGE, adapter="", poll_minutes=None,
                enabled=True, model_hint="brand.model", lineup_complete=False,
            ),
            "b": SimpleNamespace(
                id="b", source_id="oem", url="https://oem.example/b",
                role=TargetRole.CURRENT_MODEL_PAGE, adapter="", poll_minutes=None,
                enabled=True, model_hint="brand.model", lineup_complete=False,
            ),
        }
        registry = SimpleNamespace(
            targets=targets,
            profiles={"oem": SimpleNamespace(kind=SourceKind.OEM)},
        )

        class Adapter:
            def fetch(self, target):
                return SimpleNamespace(not_modified=False, document=object())

        monkeypatch.setattr(base, "adapter_for", lambda *args, **kwargs: Adapter())

        def extraction(target, result):
            suffix = "A" if target.id == "a" else "B"
            amount = 500_000 if target.id == "a" else 600_000
            return SimpleNamespace(claims=[SimpleNamespace(
                price_type=PriceType.LIST_PRICE,
                trim_raw=suffix,
                amount_thb=amount,
            )])

        monkeypatch.setattr(base, "extract_oem_price_claims", extraction)
        model = SimpleNamespace(id="brand.model")
        result = follow.discover_oem_grades(model, registry, transport=object())
        assert result is not None
        lineup_status, source, grades = result
        assert lineup_status is base.LineupStatus.PARTIAL
        assert [grade.raw_grade for grade in grades] == ["A", "B"]
        assert source["urls"] == ["https://oem.example/a", "https://oem.example/b"]
        assert source["lineup_complete"] is False

        evidence = follow.GradeEvidence(
            raw_grade="Premium",
            amount_thb=699_000,
            extracted_price_type=PriceType.LIST_PRICE,
            evidence_tier=base.EvidenceTier.MEDIA_TWO_AGREE,
            source_ref="https://autolifethailand.tv/a",
            observed_at="2026-09-25",
            source_refs=("https://autolifethailand.tv/a", "https://www.headlightmag.com/b"),
            source_ids=("autolifethailand", "headlightmag"),
        )
        match = TrimMatchResult(
            state=TrimMatchState.EXACT,
            model_id="brand.model",
            trim_id="brand.model.gen.trim.premium",
            candidate_ids=("brand.model.gen.trim.premium",),
            method=TrimMatchMethod.EXACT_NAME,
            reason="test",
            normalized_trim_raw="premium",
        )
        classified = base.classify_grade(
            evidence, match, existing_list_price_thb=None,
            generation_id="brand.model.gen")
        payload = classified.to_dict()
        assert payload["source_ref"] == "https://autolifethailand.tv/a"
        assert payload["source_refs"] == [
            "https://autolifethailand.tv/a", "https://www.headlightmag.com/b"]
        assert payload["source_ids"] == ["autolifethailand", "headlightmag"]
    finally:
        base.GradeEvidence = originals["GradeEvidence"]
        base.discover_media_grades = originals["discover_media_grades"]
        base.discover_oem_grades = originals["discover_oem_grades"]
        base.discover_model = originals["discover_model"]
        base.GradeClassification.to_dict = originals["to_dict"]


def test_scheduled_pricefeed_scopes_to_observed_at():
    from tools import pricefeed_write

    source = getsource(pricefeed_write.run)
    parsed = source.index("as_of = date.fromisoformat(observed_at)")
    scoped = source.index("scoped_siblings_by_model(")
    assert parsed < scoped
    assert "as_of=as_of" in source[scoped:source.index("result = pricefeed.run", scoped)]
