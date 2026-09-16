import json

from vehreg.catalog import Catalog, CatalogError
from vehreg.taxonomy import Powertrain
from vehreg.trim_reconciliation import (
    TrimResolutionStatus,
    apply_canonical_trim_overlay,
    generation_powertrain_mismatches,
    make_candidate,
    release_reconciliation_report,
    validate_reconciliation_state,
)


def catalog_with(*powertrains: str) -> Catalog:
    variants = []
    for index, powertrain in enumerate(powertrains, start=1):
        row = {
            "name": f"line-{index}",
            "powertrain": powertrain,
            "drivetrain": "FWD",
            "import_type": "CBU",
            "origin_country": "CN",
        }
        if powertrain == "BEV":
            row["battery_kwh"] = 60
        elif powertrain in {"PHEV", "REEV"}:
            row["engine_cc"] = 1500
            row["battery_kwh"] = 30
        elif powertrain == "HEV":
            row["engine_cc"] = 1800
            row["battery_kwh"] = 1.5
        else:
            row["engine_cc"] = 1500
        variants.append(row)
    payload = {
        "brand": {
            "id": "acme",
            "name_en": "Acme",
            "brand_origin": "CN",
            "brand_segment": "MASS",
            "oem_group": "Acme",
        },
        "models": [{
            "id": "echo",
            "name_en": "Echo",
            "body_type": "CROSSOVER",
            "generations": [{
                "code": "E1",
                "segment": "C",
                "variants": variants,
            }],
        }],
    }
    catalog = Catalog(2026)
    catalog.add_brand_payload(payload, source="<reconciliation-test>")
    catalog.build_indexes()
    return catalog


def candidate(catalog, *, name, source_text):
    return make_candidate(
        model_id="acme.echo",
        generation_id="acme.echo.e1",
        raw_name=name,
        source_ref="owner:test:001",
        source_powertrain_text=source_text,
        catalog=catalog,
    )


def trim_root(root):
    path = root / "2026" / "market" / "trims"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_state(root, models):
    path = trim_root(root) / "reconciliation.json"
    path.write_text(json.dumps({"schema_version": 1, "models": models}), encoding="utf-8")


def write_overlay(root, trims):
    path = trim_root(root) / "canonical.json"
    path.write_text(json.dumps({"schema_version": 1, "trims": trims}), encoding="utf-8")


def release(*trims):
    return {
        "year": 2026,
        "as_of": "2026-09-16",
        "brands": [{"canonical_id": "acme", "name_en": "Acme"}],
        "models": [{
            "canonical_id": "acme.echo",
            "brand_id": "acme",
            "name_en": "Echo",
        }],
        "generations": [{
            "canonical_id": "acme.echo.e1",
            "model_id": "acme.echo",
        }],
        "market_trims": list(trims),
        "counts": {"market_trims": len(trims)},
    }


def test_exact_source_model_powertrain_resolves_generic_trim():
    row = candidate(catalog_with("BEV"), name="520 Luxury", source_text="Electric SUV BEV 62 kWh")
    assert row.status is TrimResolutionStatus.READY
    assert row.resolved_powertrain is Powertrain.BEV


def test_trim_ev_token_disambiguates_mixed_source_model():
    row = candidate(
        catalog_with("BEV", "REEV"),
        name="S05 EV 510 Pro",
        source_text="Electric / EREV SUV BEV / EREV",
    )
    assert row.status is TrimResolutionStatus.READY
    assert row.resolved_powertrain is Powertrain.BEV


def test_trim_erev_token_disambiguates_mixed_source_model():
    row = candidate(
        catalog_with("BEV", "REEV"),
        name="S05 REEV 1200 Max",
        source_text="Electric / EREV SUV BEV / EREV",
    )
    assert row.status is TrimResolutionStatus.READY
    assert row.resolved_powertrain is Powertrain.REEV


def test_mixed_source_with_generic_trim_stays_ambiguous():
    row = candidate(
        catalog_with("BEV"),
        name="Avatr 07 Max AWD",
        source_text="Premium SUV BEV / EREV",
    )
    assert row.status is TrimResolutionStatus.AMBIGUOUS_POWERTRAIN
    assert row.resolved_powertrain is None


def test_exact_source_beats_stale_analytical_variant_without_rewriting_it():
    catalog = catalog_with("PHEV")
    row = candidate(
        catalog,
        name="Hunter Long Range 4x4 Dual Motor",
        source_text="Extended-range electric pickup EREV",
    )
    assert row.status is TrimResolutionStatus.READY
    assert row.resolved_powertrain is Powertrain.REEV
    assert {v.powertrain for v in catalog.variants.values()} == {Powertrain.PHEV}


def test_single_analytical_powertrain_is_fallback_only_when_source_is_silent():
    row = candidate(catalog_with("BEV"), name="Premium", source_text="Compact crossover")
    assert row.status is TrimResolutionStatus.READY
    assert row.resolved_powertrain is Powertrain.BEV
    assert "source names no powertrain" in row.reason


def test_dedicated_canonical_overlay_preserves_serving_schema_and_counts(tmp_path):
    write_overlay(tmp_path, [{
        "id": "premium_bev",
        "model_id": "acme.echo",
        "generation_id": "acme.echo.e1",
        "name": "Premium",
        "powertrain": "BEV",
        "source_refs": {"owner_directory": ["owner:test:001"]},
        "aliases": ["Acme Echo Premium"],
    }])
    out = apply_canonical_trim_overlay(release(), data_dir=tmp_path, year=2026)
    assert out["counts"]["market_trims"] == 1
    trim = out["market_trims"][0]
    assert trim["canonical_id"] == "acme.echo.e1.trim.premium_bev"
    assert trim["variant_id"] is None
    assert trim["powertrain"] == "BEV"
    assert trim["status"] == "UNVERIFIED"
    assert trim["current_list_price"] is None
    assert trim["source_refs"]["owner_directory"] == ["owner:test:001"]
    assert trim["payload"]["specs"]["aliases"] == ["Acme Echo Premium"]


def test_overlay_cannot_replace_base_trim_or_guess_variant_link(tmp_path):
    write_overlay(tmp_path, [{
        "id": "premium_bev",
        "model_id": "acme.echo",
        "generation_id": "acme.echo.e1",
        "name": "Premium",
        "powertrain": "BEV",
        "variant_id": "acme.echo.e1.line_1",
        "source_refs": {"owner_directory": ["owner:test:001"]},
    }])
    try:
        apply_canonical_trim_overlay(release(), data_dir=tmp_path, year=2026)
    except CatalogError as exc:
        assert "variant_id must stay empty" in str(exc)
    else:
        raise AssertionError("overlay accepted an unreviewed analytical variant link")


def test_ready_source_evidence_with_zero_canonical_trims_blocks_release(tmp_path):
    write_state(tmp_path, [{
        "model_id": "acme.echo",
        "status": "READY",
        "source_trim_count": 3,
        "source_refs": ["owner:test:001"],
        "reason": "three exact BEV trims ready to promote",
    }])
    report = release_reconciliation_report(release(), data_dir=tmp_path, year=2026)
    assert report["blocker_count"] == 1
    assert report["blockers"][0]["blocker"] == "SOURCE_EVIDENCE_NOT_FULLY_PROMOTED"
    assert report["blockers"][0]["unresolved_source_trim_count"] == 3


def test_partial_ready_promotion_also_blocks(tmp_path):
    write_state(tmp_path, [{
        "model_id": "acme.echo",
        "status": "READY",
        "source_trim_count": 2,
        "source_refs": ["owner:test:001"],
        "reason": "both source rows are exact",
    }])
    one = {
        "canonical_id": "acme.echo.e1.trim.one",
        "model_id": "acme.echo",
        "source_refs": {"owner_directory": ["owner:test:001"]},
    }
    report = release_reconciliation_report(release(one), data_dir=tmp_path, year=2026)
    assert report["blocker_count"] == 1
    assert report["models"][0]["canonical_source_trim_count"] == 1
    assert report["models"][0]["unresolved_source_trim_count"] == 1


def test_ambiguous_partial_state_is_explicit_and_allowed(tmp_path):
    write_state(tmp_path, [{
        "model_id": "acme.echo",
        "status": "AMBIGUOUS_POWERTRAIN",
        "source_trim_count": 3,
        "source_refs": ["owner:test:001"],
        "reason": "one grade is exact; two generic grades remain BEV / EREV ambiguous",
    }])
    one = {
        "canonical_id": "acme.echo.e1.trim.exact",
        "model_id": "acme.echo",
        "source_refs": {"owner_directory": ["owner:test:001"]},
    }
    report = release_reconciliation_report(release(one), data_dir=tmp_path, year=2026)
    assert report["blocker_count"] == 0
    assert report["models"][0]["status"] == "AMBIGUOUS_POWERTRAIN"
    assert report["models"][0]["unresolved_source_trim_count"] == 2


def test_full_source_backed_promotion_becomes_canonical(tmp_path):
    write_state(tmp_path, [{
        "model_id": "acme.echo",
        "status": "READY",
        "source_trim_count": 1,
        "source_refs": ["owner:test:001"],
        "reason": "pending promotion",
    }])
    one = {
        "canonical_id": "acme.echo.e1.trim.premium",
        "model_id": "acme.echo",
        "source_refs": {"owner_directory": ["owner:test:001"]},
    }
    report = release_reconciliation_report(release(one), data_dir=tmp_path, year=2026)
    assert report["blocker_count"] == 0
    assert report["models"][0]["status"] == "CANONICAL"
    assert report["models"][0]["canonical_source_trim_count"] == 1
    assert report["models"][0]["unresolved_source_trim_count"] == 0


def test_reconciliation_state_validation_rejects_silent_or_broken_rows():
    catalog = catalog_with("BEV")
    state = {
        "schema_version": 1,
        "models": [
            {
                "model_id": "acme.echo",
                "status": "AMBIGUOUS_POWERTRAIN",
                "source_trim_count": 2,
                "source_refs": [],
                "reason": "",
            },
            {
                "model_id": "missing.model",
                "status": "READY",
                "source_trim_count": -1,
                "source_refs": ["source:x"],
                "reason": "bad row",
            },
        ],
    }
    problems = validate_reconciliation_state(catalog, state)
    assert any("nonempty source_refs required" in problem for problem in problems)
    assert any("reason required" in problem for problem in problems)
    assert any("unknown model_id missing.model" in problem for problem in problems)
    assert any("source_trim_count must be >= 0" in problem for problem in problems)


def test_generation_mismatch_report_does_not_require_variant_link():
    catalog = catalog_with("PHEV")
    payload = {
        "brand": {
            "id": "acme2",
            "name_en": "Acme2",
            "brand_origin": "CN",
            "brand_segment": "MASS",
            "oem_group": "Acme",
        },
        "models": [{
            "id": "truck",
            "name_en": "Truck",
            "body_type": "PICKUP",
            "cab_type": "DOUBLE_CAB",
            "generations": [{
                "code": "T1",
                "segment": "F",
                "variants": [{
                    "name": "1.5 PHEV",
                    "powertrain": "PHEV",
                    "drivetrain": "AWD",
                    "engine_cc": 1500,
                    "battery_kwh": 30,
                    "import_type": "CBU",
                    "origin_country": "CN",
                }],
                "trims": [{
                    "name": "Long Range",
                    "powertrain": "REEV",
                    "source_refs": {"owner_directory": ["owner:test:truck"]},
                }],
            }],
        }],
    }
    catalog.add_brand_payload(payload, source="<mismatch-test>")
    catalog.build_indexes()
    rows = generation_powertrain_mismatches(catalog)
    row = next(item for item in rows if item["model_id"] == "acme2.truck")
    assert row["trim_powertrain"] == "REEV"
    assert row["analytical_powertrains"] == ["PHEV"]
