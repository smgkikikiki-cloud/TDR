"""Behavioral proof for the Admin MarketTrim delete path.

The delete command is intentionally expressed as an UPSERT_MODEL_BUNDLE with
an explicit ``delete_trim`` marker, so it goes through the same
CanonicalInputPipeline staging/revision path as every other Vehicle editor
change.  These tests exercise that real pipeline, not a duplicate helper.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vehreg.catalog import Catalog
from vehreg.input_pipeline import CanonicalInputError, CanonicalInputPipeline

YEAR = 2026
FIXTURES = Path(__file__).parent / "fixtures"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@pytest.fixture
def data(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    _write_json(root / f"{YEAR}/models/toyota.json", {
        "brand": {"id": "toyota", "name_en": "Toyota", "name_th": "โตโยต้า",
                  "brand_segment": "MASS", "brand_origin": "JP", "aliases": []},
        "models": [],
    })
    create = json.loads((FIXTURES / "admin_create_existing_brand.json").read_text(encoding="utf-8"))
    CanonicalInputPipeline(root).apply(create)
    return root


def _delete_payload(*, model_id: str = "toyota.test_model_x") -> dict:
    return {
        "schema_version": 1,
        "batch_id": "admin-delete-trim-test-1",
        "year": YEAR,
        "submitted_at": "2026-09-22T03:00:00+00:00",
        "source": {"kind": "ADMIN"},
        "reason": "delete erroneous trim in test",
        "commands": [{
            "operation": "UPSERT_MODEL_BUNDLE",
            "canonical_id": model_id,
            "payload": {
                "brand": {"id": "toyota", "name_en": "Toyota"},
                "model": {},
                "generation": {"code": "X1"},
                "variants": [],
                "trims": [],
                "delete_trim": {
                    "canonical_id": "toyota.test_model_x.x1.trim.premium_hev",
                },
            },
        }],
    }


def test_delete_trim_removes_it_from_canonical_catalog(data: Path):
    before = Catalog.load(data, YEAR)
    assert "toyota.test_model_x.x1.trim.premium_hev" in before.trims

    result = CanonicalInputPipeline(data).apply(_delete_payload())
    assert result.status == "APPLIED"

    after = Catalog.load(data, YEAR)
    assert "toyota.test_model_x.x1.trim.premium_hev" not in after.trims
    assert after.trims_of("toyota.test_model_x") == []
    assert after.validate() == []


def test_delete_trim_same_batch_is_idempotent(data: Path):
    payload = _delete_payload()
    CanonicalInputPipeline(data).apply(payload)
    replay = CanonicalInputPipeline(data).apply(payload)
    assert replay.idempotent_replay is True
    assert Catalog.load(data, YEAR).trims_of("toyota.test_model_x") == []


def test_delete_trim_refuses_wrong_parent_model(data: Path):
    payload = _delete_payload(model_id="toyota.some_other_model")
    with pytest.raises((CanonicalInputError, ValueError), match="submitted model|unknown model"):
        CanonicalInputPipeline(data).apply(payload)

    # Failed deletion leaves the real catalogue untouched.
    assert "toyota.test_model_x.x1.trim.premium_hev" in Catalog.load(data, YEAR).trims
