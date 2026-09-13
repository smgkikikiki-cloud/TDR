"""The 2026 models first added from DLT-only evidence, and their alias guards.

Some of these rows begin life as declared-incomplete stubs, then become normal
canonical models once research fills their specification.  The DLT label must
keep resolving in either state; finishing a stub must not require weakening the
alias regression tests or pretending the row is still incomplete forever.
"""

from __future__ import annotations

import pytest

from vehreg.catalog import DATA_DIR, Catalog
from vehreg.ingest import Resolver
from vehreg.db import connect, rebuild_dimension

#: raw DLT label -> the model id it must reach. Every one of these was sitting
#: in review before the stub/alias was added.
LABELS = {
    ("BYD", "BYD ATTO 2 PREMIUM"): "atto2",
    # Atto 1 is Dolphin Mini renamed, confirmed by the owner: an alias on
    # the existing model rather than a model of its own.
    ("BYD", "BYD ATTO 1 PREMIUM"): "seagull",
    ("BYD", "BYD SEALION5 DM-i PREMIUM"): "sealion5",
    ("MG", "MG URBAN"): "mg_urban",
    ("MG", "MG IM5"): "mg_im5",
    ("CHANGAN", "CHANGAN NEVO Q05"): "nevo_q05",
    ("WULING", "WULING DARION EV"): "wuling_darion",
    ("WULING", "WULING PORTA EV"): "wuling_porta",
    ("GWM", "WEY G9 PLUG-IN HYBRID"): "wey_g9",
    ("AVATR", "AVATR 07 MAX"): "avatr_07",
    ("KIA", "PV5 CARGO"): "kia_pv5",
    ("MERCEDES BENZ", "CLA 250+ electric"): "cla",
    ("MINI", "JCW E"): "jcw_e",
    ("CHERY", "TIGGO8 PHEV 4WD ELITE"): "tiggo8",
    ("HONDA", "e:N2"): "en2",
}

#: These ids were introduced through the stub/alias workflow.  The name is
#: intentionally historical: individual rows may now be fully researched.
SOURCE_MODEL_IDS = sorted(set(LABELS.values()) - {"seagull"})


@pytest.fixture(scope="module")
def catalog():
    cat = Catalog.load(DATA_DIR, 2026)
    cat.build_indexes()
    return cat


def _source_models(catalog):
    wanted = set(SOURCE_MODEL_IDS)
    return [(key, model) for key, model in catalog.models.items()
            if key.split(".", 1)[1] in wanted]


class TestTheSourceRowsExist:
    @pytest.mark.parametrize("model_id", SOURCE_MODEL_IDS)
    def test_the_model_is_in_the_2026_catalog(self, catalog, model_id):
        # Catalog keys are "<brand>.<model>".
        assert any(key.split(".", 1)[1] == model_id for key in catalog.models)


@pytest.fixture(scope="module")
def resolver(tmp_path_factory):
    cat = Catalog.load(DATA_DIR, 2026)
    cat.build_indexes()
    conn = connect(tmp_path_factory.mktemp("db") / "db.sqlite3")
    rebuild_dimension(conn, cat)
    return Resolver(cat, conn)


class TestTheLabelsStillReach:

    @pytest.mark.parametrize("label,model_id", sorted(LABELS.items()))
    def test_a_real_dlt_label_resolves_to_its_model(self, resolver, label, model_id):
        brand, model = label
        unit_id, grain, _how, _score, problem = resolver.resolve(brand, model)
        assert problem == "", f"{brand} {model} -> {problem}"
        assert grain.value in {"MODEL", "VARIANT"}, f"{brand} {model} -> {grain}"
        assert model_id in unit_id, f"{brand} {model} -> {unit_id}"


class TestHistoricallyStubbedRowsStayHonest:
    """A still-incomplete row says what DLT said and nothing else.

    Once research completes a row, the same test file keeps guarding its alias
    without requiring the obsolete ``incomplete`` marker to remain forever.
    """

    def test_no_price_is_claimed_on_a_declared_hole_without_evidence(self, catalog):
        for key, model in _source_models(catalog):
            if not model.incomplete:
                continue
            model_id = key.split(".", 1)[1]
            for variant in catalog.variants.values():
                if variant.id.split(".")[1] != model_id:
                    continue
                if variant.price_thb is not None:
                    assert variant.price_note != "not-researched", (
                        f"{model_id} has a price but is still marked not-researched")

    @pytest.mark.parametrize("model_id", SOURCE_MODEL_IDS)
    def test_a_source_row_keeps_at_least_one_alias(self, catalog, model_id):
        # The alias is the whole mechanism: without it the DLT label finds
        # nothing and the volume goes straight back to review.
        model = next(m for key, m in catalog.models.items()
                     if key.split(".", 1)[1] == model_id)
        assert model.aliases, f"{model_id} has no alias to match a DLT label on"


class TestDeclaredIncompleteness:
    """"The catalog is complete" has to keep meaning something."""

    def test_every_year_validates_clean(self):
        from vehreg.catalog import available_years

        for year in available_years(DATA_DIR):
            cat = Catalog.load(DATA_DIR, year)
            cat.build_indexes()
            assert cat.validate() == [], f"{year} has unexplained problems"

    def test_only_rows_still_marked_incomplete_are_reported_as_holes(self, catalog):
        reported = catalog.incomplete_models()
        for key, model in _source_models(catalog):
            model_id = key.split(".", 1)[1]
            present = any(model_id in line for line in reported)
            assert present is model.incomplete, (
                f"{model_id}: incomplete={model.incomplete}, report={present}")

    def test_dolphin_mini_is_finished_and_not_reported(self, catalog):
        # It has a price and a body type, so it is not a hole even though the
        # DLT label that reaches it arrived with the 2026 stubs.
        assert not any("seagull" in line for line in catalog.incomplete_models())

    def test_each_hole_names_what_is_missing(self, catalog):
        # A stub with nothing missing is a stub someone finished and forgot to
        # unmark; the report says so rather than staying silent.
        for line in catalog.incomplete_models():
            assert "incomplete (" in line, line

    def test_a_finished_model_is_not_marked_incomplete(self, catalog):
        finished = next(m for k, m in catalog.models.items()
                        if k.split(".", 1)[1] == "atto3")
        assert finished.incomplete is False

    def test_an_incomplete_marker_survives_a_save_round_trip(self, catalog):
        # Pick a source-row that is *currently* incomplete instead of freezing
        # this test to ATTO 2 forever. Research is expected to finish stubs.
        key, model = next((key, model) for key, model in _source_models(catalog)
                          if model.incomplete)
        brand_id, model_id = key.split(".", 1)
        payload = catalog.brand_payload(brand_id)
        stub = next(m for m in payload["models"] if m["id"] == model_id)
        assert stub.get("incomplete") is True

        rebuilt = Catalog(catalog.year)
        rebuilt.add_brand_payload(payload)
        rebuilt.build_indexes()
        assert rebuilt.models[key].incomplete is True
        assert rebuilt.validate() == []


@pytest.fixture(scope="module")
def resolver_2021(tmp_path_factory):
    cat = Catalog.load(DATA_DIR, 2021)
    cat.build_indexes()
    conn = connect(tmp_path_factory.mktemp("db21") / "db.sqlite3")
    rebuild_dimension(conn, cat)
    return Resolver(cat, conn)


class TestLegacyModelsAndAliases:
    """Cars that stopped being sold but are still being registered from stock.

    Every one of these labels appears in DLT through 2026, not only in the year
    the model was current, so the fix belongs in every catalog year rather than
    in 2021 alone.
    """

    LEGACY = {
        ("HONDA", "MOBILIO"): "mobilio",
        ("TOYOTA", "Avanza"): "avanza",
        ("HYUNDAI", "GRAND STAREX"): "grand_starex",
        ("CHEVROLET", "COLORADO C-CAB"): "colorado_c_cab",
        ("CHEVROLET", "COLORADO X-CAB"): "colorado_x_cab",
        ("CHEVROLET", "CAPTIVA"): "captiva",
        ("MERCEDES BENZ", "S 560 e"): "s_class",
        ("MINI", "Cooper S Countryman RHD"): "countryman",
    }

    @pytest.mark.parametrize("label,model_id", sorted(LEGACY.items()))
    def test_the_label_resolves(self, resolver_2021, label, model_id):
        brand, model = label
        unit_id, grain, _how, _score, problem = resolver_2021.resolve(brand, model)
        assert problem == "", f"{brand} {model} -> {problem}"
        assert model_id in unit_id, f"{brand} {model} -> {unit_id}"

    def test_the_pickup_cab_split_follows_the_registration_class(self):
        # DLT filed C-Cab as รย.1 (passenger) and X-Cab as รย.3 (cargo), which
        # is what decides the cab rather than anyone's reading of the name.
        from vehreg.taxonomy import CabType, RegistrationType

        cat = Catalog.load(DATA_DIR, 2021)
        cat.build_indexes()
        c_cab = cat.models["chevrolet.colorado_c_cab"]
        x_cab = cat.models["chevrolet.colorado_x_cab"]
        assert c_cab.cab_type is CabType.DOUBLE_CAB
        assert c_cab.registration_type is RegistrationType.RY1
        assert x_cab.cab_type is CabType.SMART_CAB
        assert x_cab.registration_type is RegistrationType.RY3


class TestUnmatchableLabels:
    def test_dlts_own_placeholder_never_enters_the_open_queue(self):
        from vehreg.ingest import is_unmatchable

        assert is_unmatchable("ไม่ระบุ")
        assert is_unmatchable("  ไม่ระบุ  ")
        assert not is_unmatchable("D-MAX")
        assert not is_unmatchable("")
