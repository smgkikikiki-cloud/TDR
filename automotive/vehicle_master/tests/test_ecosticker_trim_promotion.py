import gzip
import hashlib
import json
from pathlib import Path

import pytest

from vehreg.catalog import Catalog
from vehreg.ecosticker_promote import ECOTrimPromotionError, build_market_trim_input_batch
from vehreg.input_pipeline import CanonicalInputPipeline


SOURCE_ID = "11111111-2222-4333-8444-555555555555"
SNAPSHOT_DATE = "2026-09-08"


def _catalog_payload():
    return {
        "brand": {"id": "acme", "name_en": "Acme", "name_th": ""},
        "models": [{
            "id": "one",
            "name_en": "One",
            "body_type": "CROSSOVER",
            "generations": [{
                "code": "G1",
                "segment": "C",
                "variants": [{
                    "name": "BEV",
                    "powertrain": "BEV",
                    "drivetrain": "FWD",
                    "battery_kwh": 60,
                    "import_type": "CBU",
                    "origin_country": "CN",
                }],
                "trims": [],
            }],
        }],
    }


def _normalized_row(**changes):
    row = {
        "source_id": SOURCE_ID,
        "source_url": f"https://car.ecosticker.go.th/landing-page/detail/{SOURCE_ID}",
        "brand_raw": "ACME",
        "model_raw": "ONE PREMIUM",
        "price_thb": 999000,
        "price_classification": "ECO_STICKER_PRICE",
        "matched_model_id": "acme.one",
        "matched_generation_id": "acme.one.g1",
        "powertrain_candidate": "BEV",
        "review_status": "ready_for_review",
        "review_reasons": [],
        # These are deliberately present in source evidence; identity promotion
        # must not copy them into the MarketTrim command.
        "wheel_size": "235/55R18",
        "length_mm": 4500,
        "battery_chemistry": "LFP",
    }
    row.update(changes)
    return row


def _write_snapshot(data_dir: Path, row: dict):
    root = data_dir / "2026/ingest/ecosticker/snapshots" / SNAPSHOT_DATE
    root.mkdir(parents=True, exist_ok=True)
    normalized = (json.dumps(row, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")) + "\n").encode()
    (root / "normalized.jsonl.gz").write_bytes(gzip.compress(normalized, mtime=0))
    (root / "manifest.json").write_text(json.dumps({
        "schema_version": 1,
        "snapshot_date": SNAPSHOT_DATE,
        "normalized_sha256": hashlib.sha256(normalized).hexdigest(),
    }), encoding="utf-8")


def _write_review(path: Path, *, origin="HUMAN", reviewer="owner",
                  action="create_market_trim", trim_name="Premium"):
    path.write_text(json.dumps({
        "schema_version": 1,
        "snapshot_date": SNAPSHOT_DATE,
        "reviewer": reviewer,
        "origin": origin,
        "reviewed_at": "2026-09-11T09:00:00+07:00",
        "decisions": [{
            "source_id": SOURCE_ID,
            "action": action,
            "trim_name": trim_name,
            "notes": "Owner verified the ECO record as the Premium market trim",
        }],
    }), encoding="utf-8")


@pytest.fixture
def local_data(tmp_path):
    models = tmp_path / "2026/models"
    models.mkdir(parents=True)
    (models / "acme.json").write_text(
        json.dumps(_catalog_payload(), ensure_ascii=False), encoding="utf-8")
    # Prove the fixture is valid before promotion.
    catalog = Catalog.load(tmp_path, 2026)
    assert "acme.one" in catalog.models
    assert not catalog.trims
    _write_snapshot(tmp_path, _normalized_row())
    return tmp_path


def test_human_review_exports_existing_canonical_input_contract(local_data, tmp_path):
    review = tmp_path / "review.json"
    _write_review(review)
    batch = build_market_trim_input_batch(
        review, data_dir=local_data, year=2026, snapshot_date=SNAPSHOT_DATE)

    assert batch["source"]["kind"] == "ECO"
    assert batch["actor"] == "owner"
    assert len(batch["commands"]) == 1
    command = batch["commands"][0]
    assert command["operation"] == "UPSERT_MODEL_BUNDLE"
    assert command["canonical_id"] == "acme.one"
    trim = command["payload"]["trims"][0]
    assert trim == {
        "canonical_id": "acme.one.g1.trim.premium_bev",
        "name": "Premium",
        "powertrain": "BEV",
        "source_refs": {"ecosticker": [SOURCE_ID]},
    }
    encoded = json.dumps(command, ensure_ascii=False)
    assert "999000" not in encoded
    assert "ECO_STICKER_PRICE" not in encoded
    assert "235/55R18" not in encoded
    assert "wheel" not in encoded.lower()
    assert "battery" not in encoded.lower()
    assert "length_mm" not in encoded


def test_exported_batch_applies_through_normal_canonical_pipeline(local_data, tmp_path):
    review = tmp_path / "review.json"
    _write_review(review)
    batch = build_market_trim_input_batch(
        review, data_dir=local_data, year=2026, snapshot_date=SNAPSHOT_DATE)
    result = CanonicalInputPipeline(local_data).apply(batch)
    assert result.status == "APPLIED"

    catalog = Catalog.load(local_data, 2026)
    trim = catalog.trims["acme.one.g1.trim.premium_bev"]
    assert trim.name == "Premium"
    assert trim.powertrain.value == "BEV"
    assert trim.source_refs["ecosticker"] == (SOURCE_ID,)

    # Identity promotion did not manufacture any PriceLedger observation.
    price_dir = local_data / "2026/market/prices"
    assert not price_dir.exists() or not list(price_dir.glob("*.json"))


def test_agent_or_nonhuman_origin_cannot_create_market_trim(local_data, tmp_path):
    review = tmp_path / "review.json"
    _write_review(review, origin="AGENT", reviewer="agent-proposed")
    with pytest.raises(ECOTrimPromotionError, match="HUMAN"):
        build_market_trim_input_batch(
            review, data_dir=local_data, year=2026, snapshot_date=SNAPSHOT_DATE)


def test_ambiguous_eco_candidate_must_be_resolved_before_creation(local_data, tmp_path):
    _write_snapshot(local_data, _normalized_row(
        matched_generation_id=None,
        review_status="needs_model_review",
        review_reasons=["generation_ambiguous"],
    ))
    review = tmp_path / "review.json"
    _write_review(review)
    with pytest.raises(ECOTrimPromotionError, match="resolve model/generation/powertrain ambiguity"):
        build_market_trim_input_batch(
            review, data_dir=local_data, year=2026, snapshot_date=SNAPSHOT_DATE)


def test_human_must_name_the_trim_instead_of_promoting_raw_label(local_data, tmp_path):
    review = tmp_path / "review.json"
    _write_review(review, trim_name="")
    with pytest.raises(ECOTrimPromotionError, match="must provide trim_name"):
        build_market_trim_input_batch(
            review, data_dir=local_data, year=2026, snapshot_date=SNAPSHOT_DATE)


def test_snapshot_hash_is_part_of_the_security_boundary(local_data, tmp_path):
    normalized = local_data / f"2026/ingest/ecosticker/snapshots/{SNAPSHOT_DATE}/normalized.jsonl.gz"
    rows = gzip.decompress(normalized.read_bytes()).decode("utf-8")
    normalized.write_bytes(gzip.compress((rows + "\n").encode(), mtime=0))
    review = tmp_path / "review.json"
    _write_review(review)
    with pytest.raises(ECOTrimPromotionError, match="hash does not match"):
        build_market_trim_input_batch(
            review, data_dir=local_data, year=2026, snapshot_date=SNAPSHOT_DATE)
