"""One trim-identity rule, shared, and proof it moved nothing that exists.

The admin editor has to know a new trim's canonical_id *before* its batch
runs, so it can attach comparable-spec facts to that same trim in the same
batch. It cannot compute that id itself: ``slug`` folds Thai combining marks
and strips corporate words, so a trim honestly named "Dual Motor" loses
"Motor" and one named "Auto" collapses to "unnamed". Reimplementing that in
TypeScript would be two algorithms that silently drift.

So the rule lives in exactly one place, ``normalize.trim_identity``, the
catalog loader and the canonical writer both call it, and a command that
cannot know the id names the trim by reference and lets the writer resolve
it. Identity is the one thing in this system that must never move; these
tests are the proof that extracting the rule didn't move it.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from vehreg.catalog import Catalog, available_years, year_dir
from vehreg.normalize import slug, trim_identity, trim_local_id

DATA_DIR = Path(__file__).resolve().parents[1] / "vehreg" / "data"


def test_the_rule_is_exactly_the_expression_the_catalog_always_used():
    # Explicit id wins; otherwise name + powertrain, both through slug.
    assert trim_local_id("max_plus_bev", "Max Plus", "BEV") == slug("max_plus_bev")
    assert trim_local_id(None, "Max Plus", "BEV") == slug("Max Plus BEV")
    assert trim_local_id("", "Max Plus", "BEV") == slug("Max Plus BEV")
    assert trim_identity("acme.m.gen1", None, "Max Plus", "BEV") == \
        "acme.m.gen1.trim." + slug("Max Plus BEV")


def test_the_rule_is_lossy_in_ways_no_caller_could_predict():
    """Why callers must ask for the id instead of deriving it themselves."""
    # "motor" and "auto" are corporate noise to the folder, so they vanish.
    assert trim_local_id("royal_edition_awd_dual_motor_bev") == \
        "royal_edition_awd_dual_bev"
    assert trim_local_id(None, "Auto", "ICE") == "ice"


def test_every_trim_id_in_real_catalog_data_is_unchanged():
    """The regression that matters: read every trim in every brand file of
    every published year and assert the extracted rule produces exactly what
    the original inline expression produced."""
    checked = 0
    for year in available_years(DATA_DIR):
        for path in sorted(year_dir(DATA_DIR, year).glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            for model in payload.get("models", []):
                for generation in model.get("generations", []):
                    for raw in generation.get("trims") or []:
                        legacy = slug(raw.get("id")
                                      or f"{raw.get('name')} {raw.get('powertrain')}")
                        assert trim_local_id(raw.get("id"), raw.get("name"),
                                             raw.get("powertrain")) == legacy, (
                            f"{path}: trim {raw.get('name')!r} identity moved")
                        checked += 1
    assert checked > 100, f"only {checked} trims exercised; the fixture is too thin"


@pytest.mark.parametrize("year", available_years(DATA_DIR))
def test_the_loader_and_the_writer_agree_on_every_real_trim(year: int):
    """catalog.py derives ids on read; canonical_write.py matches trims on
    write. If those two ever disagreed, an edit would silently fork a trim."""
    catalog = Catalog.load(DATA_DIR, year)
    for trim in catalog.trims.values():
        generation_id, _, local = trim.id.rpartition(".trim.")
        row = {"id": local, "name": trim.name, "powertrain": trim.powertrain.value}
        # This is the key the writer's _upsert_by_identity computes for a row.
        assert trim_local_id(row["id"], row["name"], row["powertrain"]) == local, (
            f"{trim.id}: the writer would not recognise this trim as itself")
        assert trim_identity(generation_id, local, trim.name,
                             trim.powertrain.value) == trim.id
