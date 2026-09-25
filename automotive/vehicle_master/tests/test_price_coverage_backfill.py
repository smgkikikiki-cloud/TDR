from __future__ import annotations

import json

import pytest

from pathlib import Path

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
    discover_media_grades,
    discover_oem_grades,
    load_manifest_dict,
    revalidate_manifest_for_apply,
    run_apply,
)
from vehreg.catalog import Catalog, Model
from vehreg.entities import MarketTrim
from vehreg.input_pipeline import CanonicalInputBatch, CanonicalInputPipeline
from vehreg.model_operational_state import upsert_model_operational_state
from vehreg.price_fetch import HttpResponse
from vehreg.price_match import TrimMatchMethod, TrimMatchResult, TrimMatchState
from vehreg.price_sources import (
    SourceKind, SourceProfile, SourceTarget, SourceTargetRegistry, TargetRole,
)
from vehreg.pricefeed import Source, Tier
from vehreg.pricing import PriceType
from vehreg.taxonomy import Powertrain


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


# ------------------------------------------------------------ discover_media_grades


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


def _official_hit(amount_thb: int, *, grade: str = "ULTRA") -> dict:
    return {
        "title": f"JAECOO 5 EV {grade} ราคาอย่างเป็นทางการ {amount_thb:,} บาท",
        "url": "https://example.com/j5-price",
    }


def _trim(name: str, trim_id: str = J5_ULTRA_TRIM) -> MarketTrim:
    return MarketTrim(id=trim_id, generation_id=f"{J5_MODEL_ID}.j5", name=name,
                      powertrain=Powertrain.BEV)


def test_discover_media_grades_requires_both_sources_to_agree_on_a_known_grade():
    model = Model(id=J5_MODEL_ID, brand_id="JAECOO", name_en="JAECOO 5 EV")
    transport = _FakeMediaTransport({
        "autolifethailand.tv": [_official_hit(699_000, grade="ULTRA")],
        "headlightmag.com": [_official_hit(699_000, grade="ULTRA")],
    })
    evidence = discover_media_grades(model, [_trim("Ultra")], transport=transport)
    assert len(evidence) == 1
    assert evidence[0].raw_grade == "Ultra"
    assert evidence[0].amount_thb == 699_000
    assert evidence[0].evidence_tier is EvidenceTier.MEDIA_TWO_AGREE


def test_discover_media_grades_never_invents_a_grade_from_the_model_name():
    """Regression: the earlier design set raw_grade=model.name_en whenever
    both sources merely agreed on *an* amount, without either source
    naming an actual grade. Evidence must only ever be produced for one of
    the model's own known current MarketTrims."""
    model = Model(id=J5_MODEL_ID, brand_id="JAECOO", name_en="JAECOO 5 EV")
    hit = {"title": "JAECOO 5 EV ราคาอย่างเป็นทางการ 699,000 บาท", "url": "https://example.com/j5"}
    transport = _FakeMediaTransport({
        "autolifethailand.tv": [hit],
        "headlightmag.com": [hit],
    })
    evidence = discover_media_grades(model, [_trim("Ultra")], transport=transport)
    assert evidence == []


def test_discover_media_grades_returns_nothing_without_siblings():
    model = Model(id=J5_MODEL_ID, brand_id="JAECOO", name_en="JAECOO 5 EV")
    transport = _FakeMediaTransport({
        "autolifethailand.tv": [_official_hit(699_000, grade="ULTRA")],
        "headlightmag.com": [_official_hit(699_000, grade="ULTRA")],
    })
    # An empty siblings list is what a blocked/out-of-scope model gets --
    # discovery must not fall back to searching for anything at all.
    assert discover_media_grades(model, [], transport=transport) == []


def test_discover_media_grades_returns_nothing_on_amount_disagreement():
    model = Model(id=J5_MODEL_ID, brand_id="JAECOO", name_en="JAECOO 5 EV")
    transport = _FakeMediaTransport({
        "autolifethailand.tv": [_official_hit(699_000, grade="ULTRA")],
        "headlightmag.com": [_official_hit(650_000, grade="ULTRA")],
    })
    assert discover_media_grades(model, [_trim("Ultra")], transport=transport) == []


def test_discover_media_grades_returns_nothing_with_only_one_source_naming_the_grade():
    model = Model(id=J5_MODEL_ID, brand_id="JAECOO", name_en="JAECOO 5 EV")
    transport = _FakeMediaTransport({
        "autolifethailand.tv": [_official_hit(699_000, grade="ULTRA")],
        # headlightmag.com: no matching hits at all
    })
    assert discover_media_grades(model, [_trim("Ultra")], transport=transport) == []


def test_discover_media_grades_ignores_used_and_predicted_titles():
    model = Model(id=J5_MODEL_ID, brand_id="JAECOO", name_en="JAECOO 5 EV")
    bad_hit = {
        "title": "JAECOO 5 EV ULTRA มือสอง ราคาพิเศษ 500,000 บาท",
        "url": "https://example.com/used",
    }
    transport = _FakeMediaTransport({
        "autolifethailand.tv": [bad_hit],
        "headlightmag.com": [bad_hit],
    })
    assert discover_media_grades(model, [_trim("Ultra")], transport=transport) == []


def test_discover_media_grades_attributes_each_hit_to_its_own_grade():
    """Two siblings, two grades independently confirmed by both sources --
    each grade's evidence must carry its own amount, never the other's."""
    model = Model(id=J5_MODEL_ID, brand_id="JAECOO", name_en="JAECOO 5 EV")
    ultra_trim = f"{J5_MODEL_ID}.j5.trim.ultra_bev"
    standard_trim = f"{J5_MODEL_ID}.j5.trim.standard_bev"
    transport = _FakeMediaTransport({
        "autolifethailand.tv": [_official_hit(699_000, grade="ULTRA"),
                                _official_hit(599_000, grade="STANDARD")],
        "headlightmag.com": [_official_hit(699_000, grade="ULTRA"),
                             _official_hit(599_000, grade="STANDARD")],
    })
    siblings = [_trim("Ultra", ultra_trim), _trim("Standard", standard_trim)]
    evidence = discover_media_grades(model, siblings, transport=transport)
    by_grade = {row.raw_grade: row.amount_thb for row in evidence}
    assert by_grade == {"Ultra": 699_000, "Standard": 599_000}


# --------------------------------------------------------------- discover_oem_grades


class _FakeOemTransport:
    """Serves one fixed HTML body for any URL, as the real OEM host would."""

    def __init__(self, html: str):
        self._html = html.encode("utf-8")

    def fetch(self, url, *, headers, timeout):
        return HttpResponse(status=200, url=url,
                            headers={"content-type": "text/html; charset=utf-8"},
                            body=self._html)


def _oem_registry(target: SourceTarget) -> SourceTargetRegistry:
    return SourceTargetRegistry(
        sources={"official_jaecoo_th": Source(
            id="official_jaecoo_th", name="Jaecoo TH", tier=Tier.A,
            adapter="omoda_jaecoo_th")},
        profiles=[SourceProfile(source_id="official_jaecoo_th", kind=SourceKind.OEM)],
        targets=[target],
    )


def test_discover_oem_grades_price_list_role_is_exhaustive_with_real_extraction():
    target = SourceTarget(
        id="jaecoo_price_list", source_id="official_jaecoo_th",
        url="https://www.omodajaecoo.co.th/th", role=TargetRole.PRICE_LIST,
        model_hint=J5_MODEL_ID,
    )
    html = """
    <html><body>
      <section>JAECOO 5 EV ULTRA JAECOO 5 EV
        Price THB 699,000 Test drive More information
      </section>
      <section>JAECOO 5 EV MAX+ JAECOO 5 EV
        Price THB 899,000 Test drive More information
      </section>
    </body></html>
    """
    model = Model(id=J5_MODEL_ID, brand_id="jaecoo", name_en="JAECOO 5 EV")
    result = discover_oem_grades(model, _oem_registry(target), transport=_FakeOemTransport(html))
    assert result is not None
    lineup_status, source, grades = result
    assert lineup_status is LineupStatus.EXHAUSTIVE
    assert source["role"] == "PRICE_LIST"
    assert len(grades) == 2


def test_discover_oem_grades_blog_role_is_never_exhaustive_even_with_two_grades():
    """Regression: the old heuristic classified EXHAUSTIVE from >=2 distinct
    grades in one fetch regardless of source role. A BLOG buyer-guide
    article covering two grades is not proof the full lineup was
    enumerated -- only an operator-tagged PRICE_LIST target is."""
    target = SourceTarget(
        id="jaecoo_blog", source_id="official_jaecoo_th",
        url="https://www.omodajaecoo.co.th/th", role=TargetRole.BLOG,
        model_hint=J5_MODEL_ID,
    )
    html = "<html><body><p>ULTRA 699,000 MAX+ 899,000</p></body></html>"
    model = Model(id=J5_MODEL_ID, brand_id="jaecoo", name_en="JAECOO 5 EV")
    result = discover_oem_grades(model, _oem_registry(target), transport=_FakeOemTransport(html))
    assert result is not None
    lineup_status, source, grades = result
    assert lineup_status is LineupStatus.PARTIAL
    assert len(grades) == 2


# ----------------------------------------------- apply-time revalidation (--apply)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _seed_apply_fixture(tmp_path: Path, *, existing_price_thb: int | None = None) -> Path:
    """One model, one current (non-ended) generation, one trim -- the same
    minimal Jaecoo 5 EV fixture used across the retail_scope tests, plus
    (optionally) an already-published current LIST_PRICE for the trim, so
    apply-time revalidation has something concrete to compare against."""
    data = tmp_path / "data"
    _write_json(data / "2026" / "models" / "jaecoo.json", {
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
            "retail_status": "CURRENT",
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
                    "price_note": "", "aliases": [],
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
    if existing_price_thb is not None:
        _write_json(data / "2026" / "market" / "prices" / "canonical_seed.json", {
            "prices": [{
                "trim_id": J5_ULTRA_TRIM, "amount_thb": existing_price_thb,
                "price_type": "LIST_PRICE", "effective_from": "2026-01-01",
                "observed_at": "2026-01-01", "source": "seed",
            }],
        })
    return data


def _manifest_dict_with_auto_ready_row(*, amount_thb=699_000,
                                       generation_id="jaecoo.jaecoo_5_ev.j5") -> dict:
    return {
        "schema_version": 1,
        "models": [{
            "model_id": J5_MODEL_ID,
            "evidence_tier": "OEM_CURRENT_MODEL_PAGE",
            "grades": [{
                "raw_grade": "Ultra", "trim_id": J5_ULTRA_TRIM, "generation_id": generation_id,
                "amount_thb": amount_thb, "extracted_price_type": "LIST_PRICE",
                "match_state": "EXACT", "match_method": "EXACT_NAME",
                "evidence_tier": "OEM_CURRENT_MODEL_PAGE", "existing_list_price_thb": None,
                "terminal_state": "AUTO_READY", "note": "", "source_ref": "https://example.test/j5",
                "observed_at": "2026-09-24", "applied": False, "applied_command_id": None,
            }],
        }],
    }


def test_revalidate_leaves_a_still_valid_row_untouched(tmp_path: Path):
    data = _seed_apply_fixture(tmp_path)
    manifest = _manifest_dict_with_auto_ready_row()
    downgraded = revalidate_manifest_for_apply(manifest, data_dir=data, year=2026)
    assert downgraded == 0
    assert manifest["models"][0]["grades"][0]["terminal_state"] == "AUTO_READY"


def test_revalidate_blocks_row_when_model_enters_maintenance(tmp_path: Path):
    data = _seed_apply_fixture(tmp_path)
    upsert_model_operational_state(
        data_dir=data, year=2026, model_id=J5_MODEL_ID, action="under_maintenance",
        reviewer="ops", reviewed_at="2026-09-24", write=True,
    )
    manifest = _manifest_dict_with_auto_ready_row()
    downgraded = revalidate_manifest_for_apply(manifest, data_dir=data, year=2026)
    assert downgraded == 1
    grade = manifest["models"][0]["grades"][0]
    assert grade["terminal_state"] == "IDENTITY_BLOCKED"
    assert "maintenance" in grade["note"].lower()


def test_revalidate_blocks_row_when_generation_changed(tmp_path: Path):
    data = _seed_apply_fixture(tmp_path)
    manifest = _manifest_dict_with_auto_ready_row(generation_id="jaecoo.jaecoo_5_ev.j4")
    downgraded = revalidate_manifest_for_apply(manifest, data_dir=data, year=2026)
    assert downgraded == 1
    assert manifest["models"][0]["grades"][0]["terminal_state"] == "IDENTITY_BLOCKED"


def test_revalidate_becomes_price_conflict_when_existing_price_now_differs(tmp_path: Path):
    data = _seed_apply_fixture(tmp_path, existing_price_thb=650_000)
    manifest = _manifest_dict_with_auto_ready_row(amount_thb=699_000)
    downgraded = revalidate_manifest_for_apply(manifest, data_dir=data, year=2026)
    assert downgraded == 1
    assert manifest["models"][0]["grades"][0]["terminal_state"] == "PRICE_CONFLICT"


def test_revalidate_becomes_complete_when_existing_price_now_matches(tmp_path: Path):
    data = _seed_apply_fixture(tmp_path, existing_price_thb=699_000)
    manifest = _manifest_dict_with_auto_ready_row(amount_thb=699_000)
    downgraded = revalidate_manifest_for_apply(manifest, data_dir=data, year=2026)
    assert downgraded == 1
    assert manifest["models"][0]["grades"][0]["terminal_state"] == "COMPLETE"


def test_run_apply_writes_a_freshly_valid_row(tmp_path: Path):
    data = _seed_apply_fixture(tmp_path)
    manifest_path = data / "manifest.json"
    _write_json(manifest_path, _manifest_dict_with_auto_ready_row())
    result = run_apply(data_dir=data, year=2026, manifest_path=manifest_path)
    assert result["applied"] is True
    assert result["revalidation_blocked"] == 0
    catalog = Catalog.load(data, 2026)
    from vehreg.pricing import PriceLedger
    ledger = PriceLedger.load(data, year=2026, catalog=catalog)
    row = ledger.current_list_price(J5_ULTRA_TRIM)
    assert row is not None
    assert row.amount_thb == 699_000


def test_run_apply_never_writes_a_row_blocked_by_revalidation(tmp_path: Path):
    data = _seed_apply_fixture(tmp_path)
    upsert_model_operational_state(
        data_dir=data, year=2026, model_id=J5_MODEL_ID, action="under_maintenance",
        reviewer="ops", reviewed_at="2026-09-24", write=True,
    )
    manifest_path = data / "manifest.json"
    _write_json(manifest_path, _manifest_dict_with_auto_ready_row())
    result = run_apply(data_dir=data, year=2026, manifest_path=manifest_path)
    assert result["applied"] is False
    assert result["revalidation_blocked"] == 1
    catalog = Catalog.load(data, 2026)
    from vehreg.pricing import PriceLedger
    ledger = PriceLedger.load(data, year=2026, catalog=catalog)
    assert ledger.current_list_price(J5_ULTRA_TRIM) is None
