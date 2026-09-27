"""The owner-approved CURRENT-retail-set architecture, end to end.

Background: the old authority model let ANY source evidence (owner-directory
overlay rows, verified fragments, an old PriceLedger record) expand or
resurrect a model's CURRENT MarketTrim membership on every release build --
see Volvo EX40, whose owner-directory overlay kept re-adding three retired
grades no matter how many times a repair tried to remove them, because the
lifecycle handler that removes trims (vehreg/canonical_trim_delete.py,
vehreg/retail_lifecycle_review.py) only ever sees Catalog.trims and cannot
resolve an overlay-only identity at all.

The fix: vehreg/current_retail.py is a sparse, explicit sidecar
(market/trims/current_retail.json). A model absent from it keeps behaving
exactly as it does today (migration compatibility -- see
tdr_bridge/lifecycle.py's CURRENT-by-default policy, landed in
808cc1f "Use current-by-default retail lifecycle semantics"). A model present
in it is fully and exclusively governed by that approved set: nothing else
-- not price, not owner-directory rows, not verified fragments, not
reconciliation READY state -- may add a trim to it or bring a removed one
back. These tests prove that invariant at each of the four places it has to
hold: tdr_bridge/lifecycle.py (serving status), vehreg/retail_scope.py
(pricefeed matching scope), vehreg/pricefeed.py (the actual matcher, run
end-to-end), and vehreg/input_pipeline.py (the REPLACE_CURRENT_RETAIL_SET
write path, including materialize-then-approve in one batch).
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from tdr_bridge.lifecycle import apply_retail_lifecycle
from vehreg import pricefeed as pf
from vehreg.catalog import Catalog, CatalogError
from vehreg.current_retail import (
    CurrentRetailError,
    load_current_retail_index,
    replace_current_retail_set,
    resolve_approved_current_trim_ids,
)
from vehreg.input_pipeline import CanonicalInputError, CanonicalInputPipeline
from vehreg.retail_scope import scoped_siblings_by_model
from vehreg.trim_reconciliation import apply_canonical_trim_overlay, release_reconciliation_report

YEAR = 2026
MODEL_ID = "acme.echo"
GEN_ID = f"{MODEL_ID}.e1"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _seed_brand(tmp_path: Path, *, trims: list[dict], retail_status: str = "CURRENT") -> Path:
    """One model (acme.echo, generation e1) with the given base-Catalog trims."""
    data = tmp_path / "data"
    _write_json(data / str(YEAR) / "models" / "acme.json", {
        "brand": {"id": "acme", "name_en": "Acme", "brand_segment": "MASS",
                  "brand_origin": "US", "aliases": []},
        "models": [{
            "id": "echo", "name_en": "Echo", "name_th": "เอคโค่",
            "body_type": "SEDAN", "cab_type": "NOT_APPLICABLE",
            "registration_type": "", "market_scope": "CORE", "aliases": [],
            "retail_status": retail_status,
            "retail_source": "https://example.test/echo-lineup",
            "retail_checked_at": "2026-09-27",
            "generations": [{
                "code": "E1", "segment": "C", "seats": 5,
                "launched": "2024-01-01", "ended": None,
                "variants": [{
                    "id": "bev", "name": "Echo BEV", "powertrain": "BEV",
                    "drivetrain": "FWD", "price_thb": None, "import_type": "CBU",
                    "origin_country": "US", "aliases": [], "battery_kwh": 60.0,
                }],
                "trims": trims,
            }],
        }],
    })
    return data


def _trim(local_id: str, name: str, *, aliases: list[str] | None = None) -> dict:
    return {
        "id": local_id, "name": name, "powertrain": "BEV", "seats": 5,
        "aliases": aliases or [],
        "source_refs": {"oem": [f"https://example.test/{local_id}"]},
    }


def _catalog(data_dir: Path) -> Catalog:
    return Catalog.load(data_dir, YEAR)


def _write_current_retail(data_dir: Path, *, model_id: str = MODEL_ID,
                          trim_ids: list[str], reviewer: str = "Owner",
                          reviewed_at: str = "2026-09-27",
                          source_ref: str = "https://example.test/approved-lineup") -> None:
    result = replace_current_retail_set(
        data_dir=data_dir, year=YEAR, model_id=model_id, trim_ids=trim_ids,
        reviewer=reviewer, reviewed_at=reviewed_at, source_ref=source_ref, write=True,
    )
    assert result["written"] is True


def _release(*, trim_ids: list[str], ended: str | None = None,
             model_status: str = "CURRENT", extra_trims: list[str] = ()) -> dict:
    """A release-shaped dict, matching tdr_bridge's SEMANTIC_KEYS shape, for
    every trim id in ``trim_ids`` (real Catalog identities) plus any
    ``extra_trims`` (overlay/fragment-only ids that were never materialized
    into Catalog -- exactly what apply_canonical_trim_overlay would add)."""
    return {
        "as_of": "2026-09-27",
        "models": [{
            "canonical_id": MODEL_ID, "status": "current",
            "payload": {"retail_status": model_status},
        }],
        "generations": [{"canonical_id": GEN_ID, "model_id": MODEL_ID, "ended": ended}],
        "market_trims": [
            {"canonical_id": tid, "model_id": MODEL_ID, "generation_id": GEN_ID,
             "status": "current", "current_list_price": None}
            for tid in (*trim_ids, *extra_trims)
        ],
    }


# --- 1: base Catalog has 3 trims, approved set has 1 -> exactly 1 CURRENT ---

def test_approved_set_of_one_wins_over_two_other_base_trims(tmp_path):
    data = _seed_brand(tmp_path, trims=[
        _trim("ultra_single_bev", "Ultra Single Motor"),
        _trim("ultra_twin_bev", "Ultra Twin Motor"),
        _trim("black_edition_bev", "Black Edition"),
    ])
    approved = f"{GEN_ID}.trim.ultra_single_bev"
    _write_current_retail(data, trim_ids=[approved])

    release = _release(trim_ids=[
        f"{GEN_ID}.trim.ultra_single_bev",
        f"{GEN_ID}.trim.ultra_twin_bev",
        f"{GEN_ID}.trim.black_edition_bev",
    ])
    projected = apply_retail_lifecycle(release, data_dir=data, year=YEAR)
    by_id = {t["canonical_id"]: t["status"] for t in projected["market_trims"]}
    assert by_id[approved] == "CURRENT"
    assert by_id[f"{GEN_ID}.trim.ultra_twin_bev"] == "UNVERIFIED"
    assert by_id[f"{GEN_ID}.trim.black_edition_bev"] == "UNVERIFIED"
    assert sum(1 for status in by_id.values() if status == "CURRENT") == 1


# --- 2: overlay adds 3 more identities; they never become CURRENT ---

def test_overlay_only_identities_never_become_current(tmp_path):
    data = _seed_brand(tmp_path, trims=[_trim("ultra_single_bev", "Ultra Single Motor")])
    approved = f"{GEN_ID}.trim.ultra_single_bev"
    _write_current_retail(data, trim_ids=[approved])

    overlay_ids = [
        f"{GEN_ID}.trim.twin_performance_bev",
        f"{GEN_ID}.trim.black_edition_bev",
        f"{GEN_ID}.trim.extended_range_bev",
    ]
    release = _release(trim_ids=[approved], extra_trims=overlay_ids)
    projected = apply_retail_lifecycle(release, data_dir=data, year=YEAR)
    by_id = {t["canonical_id"]: t["status"] for t in projected["market_trims"]}
    assert by_id[approved] == "CURRENT"
    for overlay_id in overlay_ids:
        assert by_id[overlay_id] == "UNVERIFIED"


# --- 3: building the release twice never resurrects a retired trim ---

def test_repeated_release_builds_are_deterministic_no_resurrection(tmp_path):
    data = _seed_brand(tmp_path, trims=[
        _trim("ultra_single_bev", "Ultra Single Motor"),
        _trim("ultra_twin_bev", "Ultra Twin Motor"),
    ])
    approved = f"{GEN_ID}.trim.ultra_single_bev"
    _write_current_retail(data, trim_ids=[approved])
    overlay_ids = [f"{GEN_ID}.trim.black_edition_bev"]

    def build_once():
        release = _release(
            trim_ids=[approved, f"{GEN_ID}.trim.ultra_twin_bev"],
            extra_trims=overlay_ids,
        )
        projected = apply_retail_lifecycle(release, data_dir=data, year=YEAR)
        return {t["canonical_id"] for t in projected["market_trims"] if t["status"] == "CURRENT"}

    first = build_once()
    second = build_once()
    assert first == second == {approved}


# --- 4: an approved id must already exist in base Catalog ---

def test_replace_current_retail_set_rejects_an_overlay_only_id(tmp_path):
    data = _seed_brand(tmp_path, trims=[_trim("ultra_single_bev", "Ultra Single Motor")])
    with pytest.raises(CurrentRetailError, match="unknown MarketTrim"):
        replace_current_retail_set(
            data_dir=data, year=YEAR, model_id=MODEL_ID,
            trim_ids=[f"{GEN_ID}.trim.black_edition_bev"],
            reviewer="Owner", reviewed_at="2026-09-27",
            source_ref="https://example.test/approved-lineup", write=True,
        )
    # Nothing was written on the rejected attempt.
    assert load_current_retail_index(data_dir=data, year=YEAR) == {}


# --- 5: materialize a brand-new trim, then approve it, in ONE batch ---

def _batch(commands: list[dict], *, batch_id: str) -> dict:
    return {
        "schema_version": 1, "batch_id": batch_id, "year": YEAR,
        "submitted_at": "2026-09-27T03:00:00+00:00", "actor": "Owner",
        "source": {"kind": "ADMIN"}, "reason": "test repair lot",
        "commands": commands,
    }


def test_same_batch_materialize_then_replace_current_retail_set(tmp_path):
    data = _seed_brand(tmp_path, trims=[_trim("old_bev", "Old Grade")])
    new_trim_id = f"{GEN_ID}.trim.new_ultra_bev"

    result = CanonicalInputPipeline(data).apply(_batch([
        {
            "operation": "UPSERT_MODEL_BUNDLE",
            "canonical_id": MODEL_ID,
            "payload": {
                "brand": {"id": "acme", "name_en": "Acme"},
                "model": {},
                "generation": {"code": "E1"},
                "variants": [],
                "trims": [{"id": "new_ultra_bev", "name": "New Ultra",
                           "powertrain": "BEV", "seats": 5, "aliases": []}],
            },
        },
        {
            "operation": "REPLACE_CURRENT_RETAIL_SET",
            "payload": {
                "model_id": MODEL_ID,
                "trim_ids": [new_trim_id],
                "source_ref": "https://example.test/approved-lineup",
                "notes": "repair",
            },
        },
    ], batch_id="repair-echo-1"))

    assert result.status == "APPLIED"
    assert new_trim_id in Catalog.load(data, YEAR).trims
    assert resolve_approved_current_trim_ids(MODEL_ID, data_dir=data, year=YEAR) == frozenset({new_trim_id})


def test_replace_current_retail_set_before_materializing_fails_closed(tmp_path):
    """Wrong order in the same batch must fail, not silently reorder itself."""
    data = _seed_brand(tmp_path, trims=[_trim("old_bev", "Old Grade")])
    new_trim_id = f"{GEN_ID}.trim.new_ultra_bev"

    with pytest.raises(CanonicalInputError, match="unknown MarketTrim"):
        CanonicalInputPipeline(data).apply(_batch([
            {
                "operation": "REPLACE_CURRENT_RETAIL_SET",
                "payload": {
                    "model_id": MODEL_ID,
                    "trim_ids": [new_trim_id],
                    "source_ref": "https://example.test/approved-lineup",
                },
            },
            {
                "operation": "UPSERT_MODEL_BUNDLE",
                "canonical_id": MODEL_ID,
                "payload": {
                    "brand": {"id": "acme", "name_en": "Acme"},
                    "model": {}, "generation": {"code": "E1"}, "variants": [],
                    "trims": [{"id": "new_ultra_bev", "name": "New Ultra",
                               "powertrain": "BEV", "seats": 5, "aliases": []}],
                },
            },
        ], batch_id="repair-echo-wrong-order"))
    assert resolve_approved_current_trim_ids(MODEL_ID, data_dir=data, year=YEAR) is None


# --- 6: an old trim's history/identity survives removal from the set ---

def test_removed_trim_keeps_its_catalog_identity_but_loses_price_eligibility(tmp_path):
    data = _seed_brand(tmp_path, trims=[
        _trim("ultra_single_bev", "Ultra Single Motor"),
        _trim("ultra_twin_bev", "Ultra Twin Motor"),
    ])
    approved = f"{GEN_ID}.trim.ultra_single_bev"
    retired = f"{GEN_ID}.trim.ultra_twin_bev"
    _write_current_retail(data, trim_ids=[approved])

    catalog = _catalog(data)
    # History/identity: the retired trim is still a real, loadable identity.
    assert retired in catalog.trims

    siblings = scoped_siblings_by_model(catalog, data_dir=data, year=YEAR)
    eligible_ids = {trim.id for trim in siblings.get(MODEL_ID, [])}
    assert eligible_ids == {approved}
    assert retired not in eligible_ids


# --- 7/8: pricefeed matches only the approved trim ---

def _sources():
    return {"oem": pf.Source(id="oem", name="oem", tier=pf.Tier.A)}


def _pricefeed_setup(tmp_path):
    data = _seed_brand(tmp_path, trims=[
        _trim("ultra_single_bev", "Ultra Single Motor", aliases=["Ultra Single"]),
        _trim("ultra_twin_bev", "Ultra Twin Motor", aliases=["Ultra Twin"]),
    ])
    approved = f"{GEN_ID}.trim.ultra_single_bev"
    _write_current_retail(data, trim_ids=[approved])
    catalog = _catalog(data)
    siblings = scoped_siblings_by_model(catalog, data_dir=data, year=YEAR)
    return data, catalog, siblings, approved


def _claim(trim_raw: str) -> tuple[list[pf.SourceDocument], list[pf.PriceClaim]]:
    doc = pf.SourceDocument(document_id="sha256:d1", source_id="oem",
                            url="https://example.test/a", content_hash="d1")
    claim = pf.PriceClaim(
        claim_id="c1", document_id="sha256:d1", source_id="oem",
        brand_raw="Acme", model_raw="Echo", trim_raw=trim_raw,
        amount_thb=1_890_000, price_type=pf.PriceType.LIST_PRICE,
    )
    return [doc], [claim]


def test_pricefeed_matches_the_approved_trims_alias(tmp_path):
    data, catalog, siblings, approved = _pricefeed_setup(tmp_path)
    documents, claims = _claim("Ultra Single")
    result = pf.run(documents, claims, _sources(), catalog, siblings_by_model=siblings)
    assert result.review == []
    matched_trim_ids = {row["trim_id"] for row in (result.offers + result.provisional)}
    assert matched_trim_ids == {approved}


def test_pricefeed_refuses_to_match_or_reopen_a_retired_trim(tmp_path):
    data, catalog, siblings, approved = _pricefeed_setup(tmp_path)
    documents, claims = _claim("Ultra Twin")
    result = pf.run(documents, claims, _sources(), catalog, siblings_by_model=siblings)
    assert result.offers == []
    assert result.provisional == []
    assert len(result.review) == 1
    assert pf.ReviewReason.NO_TRIM_MATCH.value in result.review[0]["reasons"]
    # The retired trim was not reopened by this attempt.
    assert resolve_approved_current_trim_ids(MODEL_ID, data_dir=data, year=YEAR) == frozenset({approved})


# --- 9: an unmanaged model keeps legacy behavior untouched ---

def test_model_without_current_retail_entry_keeps_legacy_current_by_default(tmp_path):
    data = _seed_brand(tmp_path, trims=[_trim("ultra_single_bev", "Ultra Single Motor")])
    assert resolve_approved_current_trim_ids(MODEL_ID, data_dir=data, year=YEAR) is None

    release = _release(trim_ids=[f"{GEN_ID}.trim.ultra_single_bev"])
    projected = apply_retail_lifecycle(release, data_dir=data, year=YEAR)
    assert projected["market_trims"][0]["status"] == "CURRENT"


# --- 10: an old HUMAN "CURRENT" decision cannot override a managed model ---

def test_old_human_current_decision_cannot_beat_the_approved_set(tmp_path):
    data = _seed_brand(tmp_path, trims=[
        _trim("ultra_single_bev", "Ultra Single Motor"),
        _trim("ultra_twin_bev", "Ultra Twin Motor"),
    ])
    approved = f"{GEN_ID}.trim.ultra_single_bev"
    non_member = f"{GEN_ID}.trim.ultra_twin_bev"
    _write_current_retail(data, trim_ids=[approved])

    stale_decision = [{
        "trim_id": non_member, "status": "CURRENT", "reviewer": "old-reviewer",
        "reviewed_at": "2025-01-01", "source_ref": "https://example.test/old",
        "notes": "stale human review from before the approved set existed",
    }]
    release = _release(trim_ids=[approved, non_member])
    with patch("tdr_bridge.lifecycle.load_trim_lifecycle_decisions", return_value=stale_decision):
        projected = apply_retail_lifecycle(release, data_dir=data, year=YEAR)
    by_id = {t["canonical_id"]: t["status"] for t in projected["market_trims"]}
    assert by_id[approved] == "CURRENT"
    assert by_id[non_member] == "UNVERIFIED"


def test_old_human_historical_decision_on_a_non_member_is_still_honored(tmp_path):
    """A stricter (HISTORICAL) claim on a non-member is preserved, never a
    route back to CURRENT -- it just confirms what the approved set already
    implies via a distinguishable status."""
    data = _seed_brand(tmp_path, trims=[
        _trim("ultra_single_bev", "Ultra Single Motor"),
        _trim("ultra_twin_bev", "Ultra Twin Motor"),
    ])
    approved = f"{GEN_ID}.trim.ultra_single_bev"
    non_member = f"{GEN_ID}.trim.ultra_twin_bev"
    _write_current_retail(data, trim_ids=[approved])

    decision = [{
        "trim_id": non_member, "status": "HISTORICAL", "reviewer": "reviewer",
        "reviewed_at": "2026-09-01", "source_ref": "https://example.test/retired",
        "notes": "retired",
    }]
    release = _release(trim_ids=[approved, non_member])
    with patch("tdr_bridge.lifecycle.load_trim_lifecycle_decisions", return_value=decision):
        projected = apply_retail_lifecycle(release, data_dir=data, year=YEAR)
    by_id = {t["canonical_id"]: t["status"] for t in projected["market_trims"]}
    assert by_id[non_member] == "HISTORICAL"


# --- 11/12: historical parent model / ended generation beat the approved set ---

def test_historical_model_beats_the_approved_set(tmp_path):
    data = _seed_brand(tmp_path, trims=[_trim("ultra_single_bev", "Ultra Single Motor")],
                       retail_status="HISTORICAL")
    approved = f"{GEN_ID}.trim.ultra_single_bev"
    _write_current_retail(data, trim_ids=[approved])
    release = _release(trim_ids=[approved], model_status="HISTORICAL")
    projected = apply_retail_lifecycle(release, data_dir=data, year=YEAR)
    assert projected["market_trims"][0]["status"] == "HISTORICAL"


def test_ended_generation_beats_the_approved_set(tmp_path):
    data = _seed_brand(tmp_path, trims=[_trim("ultra_single_bev", "Ultra Single Motor")])
    approved = f"{GEN_ID}.trim.ultra_single_bev"
    _write_current_retail(data, trim_ids=[approved])
    release = _release(trim_ids=[approved], ended="2026-01-01")
    projected = apply_retail_lifecycle(release, data_dir=data, year=YEAR)
    assert projected["market_trims"][0]["status"] == "HISTORICAL"


# --- 13: READY owner-directory evidence missing from the approved set
#          is research debt, never a release blocker ---

def _write_reconciliation_state(data_dir: Path, rows: list[dict]) -> None:
    _write_json(data_dir / str(YEAR) / "market" / "trims" / "reconciliation.json",
               {"schema_version": 1, "models": rows})


def _write_overlay(data_dir: Path, rows: list[dict]) -> None:
    _write_json(data_dir / str(YEAR) / "market" / "trims" / "canonical.json",
               {"schema_version": 1, "trims": rows})


def test_ready_evidence_outside_the_approved_set_does_not_block_release(tmp_path):
    data = _seed_brand(tmp_path, trims=[_trim("ultra_single_bev", "Ultra Single Motor")])
    approved = f"{GEN_ID}.trim.ultra_single_bev"
    _write_current_retail(data, trim_ids=[approved])
    _write_reconciliation_state(data, [{
        "model_id": MODEL_ID, "status": "READY", "source_trim_count": 3,
        "source_refs": ["owner_directory:test:001"],
        "reason": "three owner-directory grades, none approved as current",
    }])
    _write_overlay(data, [])  # the owner-directory rows were never promoted

    base_release = _release(trim_ids=[approved])
    out = apply_canonical_trim_overlay(base_release, data_dir=data, year=YEAR)
    report = release_reconciliation_report(out, data_dir=data, year=YEAR)
    assert report["blocker_count"] == 0
    assert report["models"][0]["unresolved_source_trim_count"] == 3

    # And the release itself still builds -- CURRENT membership is unaffected.
    projected = apply_retail_lifecycle(out, data_dir=data, year=YEAR)
    assert projected["market_trims"][0]["status"] == "CURRENT"


# --- 14: a bulk repair lot covers multiple models in one batch ---

def test_bulk_batch_replaces_current_retail_sets_for_multiple_models_independently(tmp_path):
    data = tmp_path / "data"
    _write_json(data / str(YEAR) / "models" / "acme.json", {
        "brand": {"id": "acme", "name_en": "Acme", "brand_segment": "MASS",
                  "brand_origin": "US", "aliases": []},
        "models": [
            {
                "id": "echo", "name_en": "Echo", "body_type": "SEDAN",
                "cab_type": "NOT_APPLICABLE", "registration_type": "",
                "market_scope": "CORE", "aliases": [], "retail_status": "CURRENT",
                "retail_source": "https://example.test/echo-lineup",
                "retail_checked_at": "2026-09-27",
                "generations": [{
                    "code": "E1", "segment": "C", "seats": 5, "launched": "2024-01-01",
                    "ended": None, "variants": [], "trims": [
                        _trim("ultra_single_bev", "Ultra Single Motor"),
                        _trim("ultra_twin_bev", "Ultra Twin Motor"),
                    ],
                }],
            },
            {
                "id": "delta", "name_en": "Delta", "body_type": "SEDAN",
                "cab_type": "NOT_APPLICABLE", "registration_type": "",
                "market_scope": "CORE", "aliases": [], "retail_status": "CURRENT",
                "retail_source": "https://example.test/delta-lineup",
                "retail_checked_at": "2026-09-27",
                "generations": [{
                    "code": "D1", "segment": "C", "seats": 5, "launched": "2024-01-01",
                    "ended": None, "variants": [], "trims": [
                        _trim("base_bev", "Base"),
                        _trim("premium_bev", "Premium"),
                    ],
                }],
            },
        ],
    })
    echo_approved = f"{GEN_ID}.trim.ultra_single_bev"
    delta_gen = "acme.delta.d1"
    delta_approved = f"{delta_gen}.trim.premium_bev"

    result = CanonicalInputPipeline(data).apply(_batch([
        {
            "operation": "REPLACE_CURRENT_RETAIL_SET",
            "payload": {
                "model_id": MODEL_ID, "trim_ids": [echo_approved],
                "source_ref": "https://example.test/echo-lineup",
            },
        },
        {
            "operation": "REPLACE_CURRENT_RETAIL_SET",
            "payload": {
                "model_id": "acme.delta", "trim_ids": [delta_approved],
                "source_ref": "https://example.test/delta-lineup",
            },
        },
    ], batch_id="bulk-repair-lot-1"))

    assert result.status == "APPLIED"
    index = load_current_retail_index(data_dir=data, year=YEAR)
    assert index[MODEL_ID] == frozenset({echo_approved})
    assert index["acme.delta"] == frozenset({delta_approved})
