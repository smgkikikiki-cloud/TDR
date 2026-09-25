from __future__ import annotations

import json
from pathlib import Path

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
    build_append_price_batches,
    classify_grade,
    discover_media_grades,
    discover_oem_grades,
    load_manifest_dict,
    revalidate_manifest_for_apply,
    run_apply,
)
from vehreg.catalog import Catalog, Model
from vehreg.entities import MarketTrim
from vehreg.input_pipeline import CanonicalInputBatch
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
J5_GEN_ID = J5_MODEL_ID + ".j5"
J5_ULTRA_TRIM = J5_GEN_ID + ".trim.ultra_bev"


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
    result = classify_grade(
        _evidence(tier=EvidenceTier.NONE, amount_thb=None, price_type=None),
        None, existing_list_price_thb=None)
    assert result.terminal_state is TerminalState.NO_SOURCE


@pytest.mark.parametrize("price_type", [None, PriceType.UNKNOWN])
def test_unclear_or_unknown_price_semantics_block(price_type):
    result = classify_grade(
        _evidence(price_type=price_type), _match(), existing_list_price_thb=None)
    assert result.terminal_state is TerminalState.SEMANTIC_BLOCKED


def test_explicit_semantics_clear_false_blocks():
    result = classify_grade(
        _evidence(semantics_clear=False), _match(), existing_list_price_thb=None)
    assert result.terminal_state is TerminalState.SEMANTIC_BLOCKED


@pytest.mark.parametrize("price_type", [
    PriceType.CAMPAIGN_PRICE, PriceType.FINANCE_PRICE, PriceType.ESTIMATED_PRICE,
    PriceType.DEALER_PRICE, PriceType.ECO_STICKER_PRICE, PriceType.INTRODUCTORY_PRICE,
])
def test_non_list_price_types_never_auto_write(price_type):
    result = classify_grade(
        _evidence(price_type=price_type), _match(), existing_list_price_thb=None)
    assert result.terminal_state is TerminalState.CAMPAIGN_ONLY


@pytest.mark.parametrize("state,method", [
    (TrimMatchState.UNMAPPED, TrimMatchMethod.NO_GRADE_MATCH),
    (TrimMatchState.AMBIGUOUS, TrimMatchMethod.AMBIGUOUS_PARTIAL),
])
def test_non_exact_identity_blocks(state, method):
    result = classify_grade(
        _evidence(), _match(state=state, method=method, trim_id=None),
        existing_list_price_thb=None)
    assert result.terminal_state is TerminalState.IDENTITY_BLOCKED


def test_partial_grade_inference_blocks_even_when_unique():
    result = classify_grade(
        _evidence(), _match(method=TrimMatchMethod.PARTIAL_GRADE),
        existing_list_price_thb=None)
    assert result.terminal_state is TerminalState.IDENTITY_BLOCKED


@pytest.mark.parametrize("method", [TrimMatchMethod.EXACT_NAME, TrimMatchMethod.EXACT_ALIAS])
def test_exact_current_list_price_fact_can_auto_ready_without_exhaustive_lineup(method):
    result = classify_grade(
        _evidence(), _match(method=method), existing_list_price_thb=None)
    assert result.terminal_state is TerminalState.AUTO_READY


def test_existing_equal_price_is_complete_and_different_price_conflicts():
    equal = classify_grade(_evidence(), _match(), existing_list_price_thb=699_000)
    different = classify_grade(_evidence(), _match(), existing_list_price_thb=650_000)
    assert equal.terminal_state is TerminalState.COMPLETE
    assert different.terminal_state is TerminalState.PRICE_CONFLICT


# ------------------------------------------------- model completeness


def _classification(state, *, applied=False, method=TrimMatchMethod.EXACT_NAME,
                    trim_id=J5_ULTRA_TRIM) -> GradeClassification:
    return GradeClassification(
        evidence=_evidence(), match=_match(method=method, trim_id=trim_id),
        terminal_state=state, existing_list_price_thb=None, applied=applied,
    )


def test_model_complete_requires_explicit_exhaustive_lineup():
    partial = ModelManifestEntry(
        model_id=J5_MODEL_ID, lineup_status=LineupStatus.PARTIAL,
        evidence_tier=EvidenceTier.OEM_CURRENT_MODEL_PAGE, lineup_source={},
        grades=[_classification(TerminalState.COMPLETE)])
    assert partial.current_retail_model_complete is False


def test_topology_review_suppresses_lineup_complete_but_not_grade_fact():
    entry = ModelManifestEntry(
        model_id=J5_MODEL_ID, lineup_status=LineupStatus.EXHAUSTIVE,
        evidence_tier=EvidenceTier.OEM_CURRENT_MODEL_PAGE, lineup_source={},
        topology_review_required=True,
        grades=[_classification(TerminalState.COMPLETE)])
    assert entry.current_retail_model_complete is False
    assert entry.grades[0].terminal_state is TerminalState.COMPLETE


def test_model_complete_when_exhaustive_and_every_discovered_grade_has_price():
    entry = ModelManifestEntry(
        model_id=J5_MODEL_ID, lineup_status=LineupStatus.EXHAUSTIVE,
        evidence_tier=EvidenceTier.OEM_CURRENT_MODEL_PAGE, lineup_source={},
        grades=[
            _classification(TerminalState.COMPLETE),
            _classification(TerminalState.AUTO_READY, applied=True,
                            trim_id=J5_GEN_ID + ".trim.max_plus_bev"),
        ])
    assert entry.current_retail_model_complete is True


# --------------------------------------------------------------- Manifest / batches


def _manifest_dict_with_grades(grades: list[dict]) -> dict:
    return {"models": [{"evidence_tier": "OEM_CURRENT_MODEL_PAGE", "grades": grades}]}


def test_manifest_roundtrip(tmp_path):
    manifest = Manifest(
        generated_at="2026-09-24",
        models=[ModelManifestEntry(
            model_id=J5_MODEL_ID, lineup_status=LineupStatus.PARTIAL,
            evidence_tier=EvidenceTier.OEM_CURRENT_MODEL_PAGE,
            lineup_source={"url": "https://example.com"},
            grades=[_classification(TerminalState.AUTO_READY)])])
    out = tmp_path / "manifest.json"
    manifest.save(out)
    loaded = load_manifest_dict(out)
    assert loaded["summary"]["AUTO_READY"] == 1
    assert loaded["models"][0]["grades"][0]["trim_id"] == J5_ULTRA_TRIM


def test_build_append_price_batch_only_includes_unapplied_auto_ready_rows():
    manifest = _manifest_dict_with_grades([
        {"terminal_state": "AUTO_READY", "applied": False, "trim_id": "trim-a",
         "amount_thb": 699_000, "observed_at": "2026-09-24",
         "evidence_tier": "OEM_CURRENT_MODEL_PAGE"},
        {"terminal_state": "AUTO_READY", "applied": True, "trim_id": "trim-b",
         "amount_thb": 500_000},
        {"terminal_state": "COMPLETE", "applied": False, "trim_id": "trim-c",
         "amount_thb": 400_000},
    ])
    batch = build_append_price_batch(manifest, year=2026)
    assert batch is not None
    assert [command["canonical_id"] for command in batch["commands"]] == ["trim-a"]
    assert CanonicalInputBatch.from_dict(batch).source_kind == "PRICE_HARVEST"


def test_more_than_500_rows_are_split_into_deterministic_bounded_batches():
    grades = [
        {"terminal_state": "AUTO_READY", "applied": False,
         "trim_id": f"trim-{index:04d}", "amount_thb": 500_000 + index,
         "observed_at": "2026-09-24", "evidence_tier": "MEDIA_TWO_AGREE"}
        for index in range(901)
    ]
    manifest = _manifest_dict_with_grades(grades)
    batches = build_append_price_batches(manifest, year=2026)
    assert [len(batch["commands"]) for batch in batches] == [400, 400, 101]
    assert len({batch["batch_id"] for batch in batches}) == 3
    again = build_append_price_batches(manifest, year=2026)
    assert [batch["batch_id"] for batch in again] == [batch["batch_id"] for batch in batches]


# ------------------------------------------------------------ media discovery


class _FakeMediaTransport:
    def __init__(self, hits_by_host: dict[str, list[dict]],
                 article_bodies: dict[str, str] | None = None):
        self.hits_by_host = hits_by_host
        self.article_bodies = article_bodies or {}

    def fetch(self, url, *, headers, timeout):
        if "/wp-json/" in url:
            for host, hits in self.hits_by_host.items():
                if host in url:
                    return HttpResponse(
                        status=200, url=url, headers={},
                        body=json.dumps(hits).encode("utf-8"))
            return HttpResponse(status=404, url=url, headers={}, body=b"[]")
        if url in self.article_bodies:
            return HttpResponse(
                status=200, url=url, headers={"content-type": "text/html"},
                body=self.article_bodies[url].encode("utf-8"))
        return HttpResponse(status=404, url=url, headers={}, body=b"")


def _official_hit(amount_thb: int, *, grade: str = "ULTRA", url="https://example.com/a") -> dict:
    return {
        "title": f"JAECOO 5 EV {grade} ราคาอย่างเป็นทางการ {amount_thb:,} บาท",
        "url": url,
    }


def _trim(name: str, trim_id: str = J5_ULTRA_TRIM, aliases=()) -> MarketTrim:
    return MarketTrim(
        id=trim_id, generation_id=J5_GEN_ID, name=name,
        powertrain=Powertrain.BEV, aliases=tuple(aliases))


def _agreeing_media_transport(amount=699_000) -> _FakeMediaTransport:
    auto_url = "https://autolifethailand.tv/j5-ultra"
    head_url = "https://www.headlightmag.com/j5-ultra"
    return _FakeMediaTransport(
        {
            "autolifethailand.tv": [_official_hit(amount, url=auto_url)],
            "headlightmag.com": [_official_hit(amount, url=head_url)],
        },
        {
            auto_url: "independent autolife article words alpha beta gamma delta epsilon zeta eta",
            head_url: "headlight original report words one two three four five six seven eight",
        })


def test_media_requires_two_sources_to_agree_on_one_known_grade():
    model = Model(id=J5_MODEL_ID, brand_id="JAECOO", name_en="JAECOO 5 EV")
    evidence = discover_media_grades(
        model, [_trim("Ultra")], transport=_agreeing_media_transport())
    assert len(evidence) == 1
    assert evidence[0].raw_grade == "Ultra"
    assert evidence[0].amount_thb == 699_000


def test_media_never_invents_grade_from_model_name():
    model = Model(id=J5_MODEL_ID, brand_id="JAECOO", name_en="JAECOO 5 EV")
    hit = {"title": "JAECOO 5 EV ราคาอย่างเป็นทางการ 699,000 บาท",
           "url": "https://example.com/j5"}
    transport = _FakeMediaTransport({
        "autolifethailand.tv": [hit], "headlightmag.com": [hit]})
    assert discover_media_grades(model, [_trim("Ultra")], transport=transport) == []


def test_media_premium_does_not_bind_to_premium_luxury_title():
    model = Model(id=J5_MODEL_ID, brand_id="JAECOO", name_en="JAECOO 5 EV")
    premium = _trim("Premium", J5_GEN_ID + ".trim.premium")
    luxury = _trim("Premium Luxury", J5_GEN_ID + ".trim.premium_luxury")
    auto_url = "https://autolifethailand.tv/luxury"
    head_url = "https://www.headlightmag.com/luxury"
    transport = _FakeMediaTransport({
        "autolifethailand.tv": [_official_hit(899_000, grade="PREMIUM LUXURY", url=auto_url)],
        "headlightmag.com": [_official_hit(899_000, grade="PREMIUM LUXURY", url=head_url)],
    })
    assert discover_media_grades(model, [premium, luxury], transport=transport) == []


def test_two_media_reprints_count_as_one_voice_and_do_not_auto_ready():
    model = Model(id=J5_MODEL_ID, brand_id="JAECOO", name_en="JAECOO 5 EV")
    auto_url = "https://autolifethailand.tv/reprint"
    head_url = "https://www.headlightmag.com/reprint"
    copied = "same manufacturer press release copy with enough words alpha beta gamma delta epsilon zeta"
    transport = _FakeMediaTransport(
        {
            "autolifethailand.tv": [_official_hit(699_000, url=auto_url)],
            "headlightmag.com": [_official_hit(699_000, url=head_url)],
        }, {auto_url: copied, head_url: copied})
    assert discover_media_grades(model, [_trim("Ultra")], transport=transport) == []


def test_media_amount_disagreement_returns_no_evidence():
    model = Model(id=J5_MODEL_ID, brand_id="JAECOO", name_en="JAECOO 5 EV")
    transport = _FakeMediaTransport({
        "autolifethailand.tv": [_official_hit(699_000)],
        "headlightmag.com": [_official_hit(650_000)],
    })
    assert discover_media_grades(model, [_trim("Ultra")], transport=transport) == []


# --------------------------------------------------------------- OEM discovery


class _FakeOemTransport:
    def __init__(self, html: str):
        self.html = html.encode("utf-8")

    def fetch(self, url, *, headers, timeout):
        return HttpResponse(
            status=200, url=url,
            headers={"content-type": "text/html; charset=utf-8"},
            body=self.html)


def _oem_registry(target: SourceTarget) -> SourceTargetRegistry:
    return SourceTargetRegistry(
        sources={"official_jaecoo_th": Source(
            id="official_jaecoo_th", name="Jaecoo TH", tier=Tier.A,
            adapter="omoda_jaecoo_th")},
        profiles=[SourceProfile(source_id="official_jaecoo_th", kind=SourceKind.OEM)],
        targets=[target],
    )


def _j5_price_html() -> str:
    return """
    <html><body>
      <section>JAECOO 5 EV ULTRA JAECOO 5 EV Price THB 699,000 Test drive More information</section>
      <section>JAECOO 5 EV MAX+ JAECOO 5 EV Price THB 899,000 Test drive More information</section>
    </body></html>
    """


def test_price_list_role_without_explicit_completeness_stays_partial():
    target = SourceTarget(
        id="jaecoo_price_list", source_id="official_jaecoo_th",
        url="https://www.omodajaecoo.co.th/th", role=TargetRole.PRICE_LIST,
        model_hint=J5_MODEL_ID)
    result = discover_oem_grades(
        Model(id=J5_MODEL_ID, brand_id="jaecoo", name_en="JAECOO 5 EV"),
        _oem_registry(target), transport=_FakeOemTransport(_j5_price_html()))
    assert result is not None
    assert result[0] is LineupStatus.PARTIAL


def test_explicit_reviewed_lineup_complete_signal_can_be_exhaustive():
    target = SourceTarget(
        id="jaecoo_price_list", source_id="official_jaecoo_th",
        url="https://www.omodajaecoo.co.th/th", role=TargetRole.PRICE_LIST,
        model_hint=J5_MODEL_ID, lineup_complete=True)
    result = discover_oem_grades(
        Model(id=J5_MODEL_ID, brand_id="jaecoo", name_en="JAECOO 5 EV"),
        _oem_registry(target), transport=_FakeOemTransport(_j5_price_html()))
    assert result is not None
    assert result[0] is LineupStatus.EXHAUSTIVE
    assert result[1]["lineup_complete"] is True


def test_blog_oem_page_cannot_establish_current_list_price_for_backfill():
    target = SourceTarget(
        id="jaecoo_blog", source_id="official_jaecoo_th",
        url="https://www.omodajaecoo.co.th/th/blog/j5", role=TargetRole.BLOG,
        model_hint=J5_MODEL_ID)
    result = discover_oem_grades(
        Model(id=J5_MODEL_ID, brand_id="jaecoo", name_en="JAECOO 5 EV"),
        _oem_registry(target), transport=_FakeOemTransport("ULTRA 699,000 MAX+ 899,000"))
    assert result is None


# ----------------------------------------------- apply-time revalidation


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _seed_apply_fixture(tmp_path: Path, *, existing_price_thb: int | None = None) -> Path:
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
            "retail_status": "CURRENT", "retail_checked_at": "2026-09-11",
            "retail_source": "https://example.test/j5/model",
            "generations": [{
                "code": "J5", "segment": "B", "seats": 5,
                "launched": "2025-08-19", "ended": None,
                "variants": [{
                    "id": "bev_cbu", "name": "58.9 kWh BEV CBU", "powertrain": "BEV",
                    "drivetrain": "FWD", "battery_kwh": 58.9,
                    "import_type": "CBU", "origin_country": "CN", "aliases": [],
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
                                       generation_id=J5_GEN_ID) -> dict:
    return {
        "schema_version": 1,
        "models": [{
            "model_id": J5_MODEL_ID,
            "evidence_tier": "OEM_CURRENT_MODEL_PAGE",
            "grades": [{
                "raw_grade": "Ultra", "trim_id": J5_ULTRA_TRIM,
                "generation_id": generation_id, "amount_thb": amount_thb,
                "extracted_price_type": "LIST_PRICE", "match_state": "EXACT",
                "match_method": "EXACT_NAME", "evidence_tier": "OEM_CURRENT_MODEL_PAGE",
                "existing_list_price_thb": None, "terminal_state": "AUTO_READY",
                "note": "", "source_ref": "https://example.test/j5",
                "observed_at": "2026-09-24", "applied": False,
                "applied_command_id": None,
            }],
        }],
    }


def test_local_revalidation_still_blocks_human_maintenance(tmp_path: Path):
    data = _seed_apply_fixture(tmp_path)
    upsert_model_operational_state(
        data_dir=data, year=2026, model_id=J5_MODEL_ID,
        action="under_maintenance", reviewer="ops", reviewed_at="2026-09-24",
        write=True)
    manifest = _manifest_dict_with_auto_ready_row()
    assert revalidate_manifest_for_apply(manifest, data_dir=data, year=2026) == 1
    assert manifest["models"][0]["grades"][0]["terminal_state"] == "IDENTITY_BLOCKED"


def test_local_revalidation_detects_existing_price_conflict(tmp_path: Path):
    data = _seed_apply_fixture(tmp_path, existing_price_thb=650_000)
    manifest = _manifest_dict_with_auto_ready_row()
    assert revalidate_manifest_for_apply(manifest, data_dir=data, year=2026) == 1
    assert manifest["models"][0]["grades"][0]["terminal_state"] == "PRICE_CONFLICT"


def test_fresh_apply_revalidation_blocks_when_source_price_changed(tmp_path: Path):
    data = _seed_apply_fixture(tmp_path)
    manifest = _manifest_dict_with_auto_ready_row(amount_thb=699_000)
    changed_source = _agreeing_media_transport(amount=729_000)
    blocked = revalidate_manifest_for_apply(
        manifest, data_dir=data, year=2026, transport=changed_source,
        require_fresh_evidence=True)
    assert blocked == 1
    grade = manifest["models"][0]["grades"][0]
    assert grade["terminal_state"] == "PRICE_CONFLICT"
    assert "source changed" in grade["note"]


def test_run_apply_revalidates_fresh_evidence_and_writes(tmp_path: Path):
    data = _seed_apply_fixture(tmp_path)
    manifest_path = data / "manifest.json"
    _write_json(manifest_path, _manifest_dict_with_auto_ready_row())
    result = run_apply(
        data_dir=data, year=2026, manifest_path=manifest_path,
        transport=_agreeing_media_transport(amount=699_000))
    assert result["applied"] is True
    assert result["commands"] == 1
    catalog = Catalog.load(data, 2026)
    from vehreg.pricing import PriceLedger
    row = PriceLedger.load(data, year=2026, catalog=catalog).current_list_price(J5_ULTRA_TRIM)
    assert row is not None
    assert row.amount_thb == 699_000


def test_run_apply_never_writes_when_fresh_evidence_disappears(tmp_path: Path):
    data = _seed_apply_fixture(tmp_path)
    manifest_path = data / "manifest.json"
    _write_json(manifest_path, _manifest_dict_with_auto_ready_row())
    result = run_apply(
        data_dir=data, year=2026, manifest_path=manifest_path,
        transport=_FakeMediaTransport({}))
    assert result["applied"] is False
    assert result["revalidation_blocked"] == 1
    catalog = Catalog.load(data, 2026)
    from vehreg.pricing import PriceLedger
    assert PriceLedger.load(data, year=2026, catalog=catalog).current_list_price(J5_ULTRA_TRIM) is None
