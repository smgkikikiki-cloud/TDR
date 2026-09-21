"""An ECO row, through the pipeline, into the catalogue a release reads.

The resolver's own tests say which rows should be written; this says the
writing works: the commands it compiles are accepted by the canonical
input pipeline, they change the trim's own columns on disk, a blank
column in the source leaves the stored value alone, and re-importing the
same file writes nothing at all.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vehreg.catalog import Catalog
from vehreg.input_pipeline import CanonicalInputPipeline
from vehreg.source_import import (
    CREATED, PATCHED, UNCHANGED, ExistingTrim, SourceRow, batches_from_commands,
    commands_from_outcomes, resolve_rows, summarize,
)

YEAR = 2026
MODEL = "toyota.camry"
GEN = f"{MODEL}.axvh70"
TRIM = f"{GEN}.trim.premium"


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


@pytest.fixture
def data(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    _write(root / f"{YEAR}/models/toyota.json", {
        "brand": {"id": "toyota", "name_en": "Toyota", "name_th": "โตโยต้า",
                  "brand_segment": "MASS", "brand_origin": "JP", "aliases": []},
        "models": [{
            "id": "camry", "name_en": "Camry", "nameplate": "Camry",
            "body_type": "SEDAN", "cab_type": "NOT_APPLICABLE",
            "registration_type": "", "market_scope": "CORE", "aliases": [],
            "generations": [{
                "code": "AXVH70", "segment": "D", "seats": 5,
                "variants": [{"name": "2.5 HEV", "powertrain": "HEV",
                              "drivetrain": "FWD", "import_type": "CKD",
                              "origin_country": "TH", "aliases": []}],
                "trims": [{
                    "id": "premium", "name": "Premium", "variant": "2.5 HEV",
                    "powertrain": "HEV", "drivetrain": "FWD", "seats": 5,
                    "aliases": [],
                }],
            }],
        }],
    })
    return root


def _catalog(data: Path) -> Catalog:
    return Catalog.load(data, YEAR)


def _trim(data: Path):
    return _catalog(data).trims[TRIM]


def _existing(data: Path) -> list[ExistingTrim]:
    from tools.import_source import FIELD_TO_COLUMN

    out = []
    for trim in _catalog(data).trims.values():
        out.append(ExistingTrim(
            canonical_id=trim.id, model_id=MODEL, generation_id=GEN,
            name=trim.name, powertrain=str(getattr(trim.powertrain, "value", trim.powertrain)),
            columns={column: getattr(trim, column, None)
                     for column in FIELD_TO_COLUMN.values()},
            source_ids=tuple(trim.source_refs.get("eco", ()) if trim.source_refs else ()),
        ))
    return out


def _apply(data: Path, rows: list[SourceRow], *, prefix: str):
    outcomes = resolve_rows(rows, _existing(data), known_generations=[GEN])
    commands, stranded = commands_from_outcomes(
        outcomes, generation_codes={GEN: "AXVH70"},
        existing_by_trim={item.canonical_id: item for item in _existing(data)})
    assert not stranded, stranded
    for batch in batches_from_commands(
            commands, year=YEAR, source_kind="ECO", source_ref="eco-book.xlsx",
            batch_prefix=prefix, submitted_at="2026-09-21T00:00:00+00:00"):
        CanonicalInputPipeline(data).apply(batch)
    return outcomes, commands


def _row(source_id="eco-1", name="Premium", **values) -> SourceRow:
    return SourceRow(source_id=source_id, source_kind="ECO", model_id=MODEL,
                     generation_id=GEN, powertrain="HEV", trim_name=name, values=values)


def test_a_measurement_from_the_sticker_lands_on_the_trim(data: Path):
    assert _trim(data).length_mm is None

    outcomes, _ = _apply(data, [_row(**{
        "vehicle.length_mm": 4885, "vehicle.width_mm": 1840,
        "engine.displacement_cc": 2487,
    })], prefix="eco-a")

    assert summarize(outcomes)[PATCHED] == 1
    after = _trim(data)
    assert (after.length_mm, after.width_mm, after.engine_cc) == (4885, 1840, 2487)
    # The identity did not move.
    assert after.id == TRIM and after.name == "Premium"


def test_a_column_the_file_leaves_blank_keeps_what_was_there(data: Path):
    _apply(data, [_row(**{"vehicle.length_mm": 4885})], prefix="eco-b1")
    assert _trim(data).seats == 5

    _apply(data, [_row(source_id="eco-2", **{"vehicle.width_mm": 1840})], prefix="eco-b2")

    after = _trim(data)
    assert (after.seats, after.length_mm, after.width_mm) == (5, 4885, 1840)


def test_the_same_file_imported_twice_writes_nothing_the_second_time(data: Path):
    _apply(data, [_row(**{"vehicle.length_mm": 4885})], prefix="eco-c1")
    before = json.loads((data / f"{YEAR}/models/toyota.json").read_text(encoding="utf-8"))

    outcomes, commands = _apply(data, [_row(**{"vehicle.length_mm": 4885})],
                                prefix="eco-c2")

    assert summarize(outcomes)[UNCHANGED] == 1 and commands == []
    assert json.loads((data / f"{YEAR}/models/toyota.json").read_text(encoding="utf-8")) == before


def test_a_grade_the_catalogue_does_not_have_is_created_once(data: Path):
    outcomes, _ = _apply(data, [
        _row(**{"vehicle.length_mm": 4885}),
        _row(source_id="eco-9", name="Sport", **{"vehicle.length_mm": 4885}),
    ], prefix="eco-d")

    assert summarize(outcomes)[CREATED] == 1
    names = sorted(trim.name for trim in _catalog(data).trims.values())
    assert names == ["Premium", "Sport"]

    # And importing the same book again does not make a second Sport.
    _apply(data, [
        _row(**{"vehicle.length_mm": 4885}),
        _row(source_id="eco-9", name="Sport", **{"vehicle.length_mm": 4885}),
    ], prefix="eco-d2")
    assert len(_catalog(data).trims) == 2


def test_the_file_that_wrote_a_column_is_recorded_on_the_trim(data: Path):
    _apply(data, [_row(**{"vehicle.length_mm": 4885})], prefix="eco-e")
    assert "eco-1" in (_trim(data).source_refs or {}).get("eco", [])
