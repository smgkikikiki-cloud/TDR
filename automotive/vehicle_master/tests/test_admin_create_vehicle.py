"""Blocker 1 (Tests A & B): the admin "+ สร้างรถใหม่" create-vehicle form,
proven end to end through the real canonical write pipeline.

scripts/check-vehicle-create.ts executes lib/canonical-vehicle-create.ts's
buildNewVehicleBatch for real and writes its exact output to
tests/fixtures/admin_create_*.json. This test never reimplements that
builder -- it reads those literal fixtures and feeds them to
vehreg.input_pipeline.CanonicalInputPipeline.apply(), the same entry point
tools/canonical_input_worker.py's pull() uses for every admin batch, then
reads the result back with Catalog.load() the same way the release build
would. That is the whole path except the Supabase queue row and the actual
GitHub Actions commit/publish, which need live infrastructure this
sandbox does not have (see the final report's "REQUIRES LIVE SMOKE" note).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vehreg.catalog import Catalog
from vehreg.input_pipeline import CanonicalInputPipeline

YEAR = 2026
FIXTURES = Path(__file__).parent / "fixtures"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def data(tmp_path: Path) -> Path:
    """A catalogue with exactly one existing brand: toyota, no models yet --
    the state Test A's "existing brand, new model" fixture was built to run
    against (lib/canonical-vehicle-create.ts's buildNewVehicleBatch sends
    only {id: "toyota"} for an existing brand, deliberately relying on the
    brand's own name_en already being on disk rather than resending it --
    see that module's docstring)."""
    root = tmp_path / "data"
    _write_json(root / f"{YEAR}/models/toyota.json", {
        "brand": {"id": "toyota", "name_en": "Toyota", "name_th": "โตโยต้า",
                  "brand_segment": "MASS", "brand_origin": "JP", "aliases": []},
        "models": [],
    })
    return root


def test_a_existing_brand_new_model_and_trim(data: Path):
    payload = _fixture("admin_create_existing_brand.json")

    result = CanonicalInputPipeline(data).apply(payload)
    assert result.status == "APPLIED"

    catalog = Catalog.load(data, YEAR)
    assert "toyota.test_model_x" in catalog.models
    model = catalog.models["toyota.test_model_x"]
    assert model.name_en == "Test Model X"
    assert model.incomplete is True

    trims = catalog.trims_of("toyota.test_model_x")
    assert len(trims) == 1
    assert trims[0].name == "Premium"
    assert trims[0].powertrain.value == "HEV"
    # Deterministic id: the same generation_id.trim.<slug> rule every other
    # canonical write uses (vehreg/normalize.py's trim_identity). No raw id
    # was given, so it folds name+powertrain ("Premium HEV" -> "premium_hev")
    # exactly like the catalog loader would for any other trim -- not a
    # value this test invented.
    assert trims[0].id == "toyota.test_model_x.x1.trim.premium_hev"

    # Catalog.validate() is what CanonicalInputPipeline.apply() itself runs
    # before it will write anything (vehreg/canonical_write.py's
    # _validate_payloads) -- re-running it here proves the write really did
    # leave a catalogue that passes it, not just that apply() didn't raise.
    assert catalog.validate() == []


def test_a_resubmitting_the_same_batch_does_not_duplicate(data: Path):
    payload = _fixture("admin_create_existing_brand.json")
    CanonicalInputPipeline(data).apply(payload)

    # Same batch_id + same content -- the exact "double click the Save
    # button" case. CanonicalInputPipeline.apply() recognises the marker
    # and replays instead of re-applying (vehreg/input_pipeline.py).
    result = CanonicalInputPipeline(data).apply(payload)
    assert result.idempotent_replay is True

    catalog = Catalog.load(data, YEAR)
    assert len(catalog.trims_of("toyota.test_model_x")) == 1


def test_b_new_brand_and_new_model_no_legacy_row_needed(tmp_path: Path):
    # A genuinely empty catalogue: nothing pre-seeded, proving the whole
    # brand is minted by this one write and nothing about it depends on a
    # legacy public.brands/models row existing anywhere.
    data = tmp_path / "data"
    (data / str(YEAR) / "models").mkdir(parents=True)

    payload = _fixture("admin_create_new_brand.json")
    result = CanonicalInputPipeline(data).apply(payload)
    assert result.status == "APPLIED"

    catalog = Catalog.load(data, YEAR)
    assert "test_new_brand" in catalog.brands
    assert catalog.brands["test_new_brand"].name_en == "Test New Brand"
    assert "test_new_brand.model_one" in catalog.models
    assert catalog.models["test_new_brand.model_one"].incomplete is True
    assert catalog.validate() == []


def test_1a_model_grain_existing_brand_creates_no_trim(data: Path):
    """MODEL-grain: DLT named a car, never a grade or a powertrain
    (lib/canonical-vehicle-create.ts's buildNewVehicleBatch with trim
    omitted). Literal proof of "no trim/no powertrain" -- the fixture's own
    commands[0].payload.trims is [], asserted here and again on the
    catalogue the pipeline actually wrote."""
    payload = _fixture("admin_create_model_only_existing_brand.json")
    assert payload["commands"][0]["payload"]["trims"] == []
    assert "trim_powertrain" not in json.dumps(payload)

    result = CanonicalInputPipeline(data).apply(payload)
    assert result.status == "APPLIED"

    catalog = Catalog.load(data, YEAR)
    assert "toyota.test_model_y" in catalog.models
    model = catalog.models["toyota.test_model_y"]
    assert model.name_en == "Test Model Y"
    assert model.incomplete is True
    assert catalog.generations_of("toyota.test_model_y")[0].code == "Y1"
    assert catalog.trims_of("toyota.test_model_y") == []

    # Catalog.validate() passes precisely because incomplete=True skips the
    # "no variants"/"body_type not set" checks -- not because this test
    # relaxed anything.
    assert catalog.validate() == []


def test_1b_model_grain_new_brand_creates_no_trim_no_legacy_row(tmp_path: Path):
    data = tmp_path / "data"
    (data / str(YEAR) / "models").mkdir(parents=True)

    payload = _fixture("admin_create_model_only_new_brand.json")
    assert payload["commands"][0]["payload"]["trims"] == []

    result = CanonicalInputPipeline(data).apply(payload)
    assert result.status == "APPLIED"

    catalog = Catalog.load(data, YEAR)
    assert "test_model_only_brand" in catalog.brands
    assert "test_model_only_brand.model_two" in catalog.models
    assert catalog.models["test_model_only_brand.model_two"].incomplete is True
    assert catalog.trims_of("test_model_only_brand.model_two") == []
    assert catalog.validate() == []
