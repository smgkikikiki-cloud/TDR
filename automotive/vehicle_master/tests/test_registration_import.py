"""A DLT file is registration data, and is read as registration data."""

from pathlib import Path

import pytest

from vehreg.registration_import import (
    MATCHED, UNKNOWN, RegistrationRow, UnsupportedRegistrationSchema,
    exception_rows, parse_registration_rows, resolve_registrations, snapshot_rows,
)

BRAND_ALIASES = {"toyota": "brand-uuid-toyota"}
MODEL_ALIASES = [
    {"brand_id": "brand-uuid-toyota", "registration_type": "*",
     "alias_norm": "camry", "model_id": "legacy-camry", "match_mode": "prefix"},
]


def csv_rows(**overrides):
    base = {"period": "2026-08", "registration_type": "RY1",
            "brand": "TOYOTA", "model": "CAMRY", "units": "120"}
    base.update(overrides)
    return [base]


# ---------------------------------------------------------------------------
# Reading the file
# ---------------------------------------------------------------------------

def test_a_registration_export_is_read_as_registration_rows():
    rows, rejected = parse_registration_rows(csv_rows())
    assert not rejected
    assert rows[0].period == "2026-08" and rows[0].units == 120


def test_a_file_that_is_not_a_registration_export_is_refused_not_guessed():
    """An ECO workbook handed to this importer must fail, not be parsed as
    though its columns meant something here."""
    with pytest.raises(UnsupportedRegistrationSchema):
        parse_registration_rows([{"brand": "TOYOTA", "model": "CAMRY", "capacity_cylinder": "2487"}])


def test_an_empty_file_is_refused():
    with pytest.raises(UnsupportedRegistrationSchema):
        parse_registration_rows([])


def test_a_malformed_row_is_reported_and_the_rest_still_read():
    rows, rejected = parse_registration_rows(csv_rows() + [
        {"period": "2026-08", "registration_type": "RY1", "brand": "MG",
         "model": "MG4", "units": "not a number"}])
    assert len(rows) == 1 and len(rejected) == 1


def test_the_grade_detail_a_source_prints_is_kept_verbatim():
    """Some marques print the grade inside the model field. Folding it away
    would turn a trim-level row into a model-level one."""
    rows, _ = parse_registration_rows(csv_rows(brand="BYD", model="SEALION 6 DM-i PREMIUM"))
    assert rows[0].model_raw == "SEALION 6 DM-i PREMIUM"


# ---------------------------------------------------------------------------
# Resolving against what was taught
# ---------------------------------------------------------------------------

def test_a_label_the_crosswalk_knows_matches_without_asking():
    rows, _ = parse_registration_rows(csv_rows())
    resolved = resolve_registrations(rows, BRAND_ALIASES, MODEL_ALIASES)
    assert resolved[0].status == MATCHED and resolved[0].model_id == "legacy-camry"


def test_an_unknown_brand_is_an_exception_not_a_guess():
    rows, _ = parse_registration_rows(csv_rows(brand="NOTABRAND"))
    resolved = resolve_registrations(rows, BRAND_ALIASES, MODEL_ALIASES)
    assert resolved[0].status == UNKNOWN and "crosswalk" in resolved[0].reason


def test_an_unknown_model_under_a_known_brand_is_an_exception():
    rows, _ = parse_registration_rows(csv_rows(model="MYSTERY"))
    resolved = resolve_registrations(rows, BRAND_ALIASES, MODEL_ALIASES)
    assert resolved[0].status == UNKNOWN


def test_two_equally_good_mappings_are_left_for_a_person():
    aliases = MODEL_ALIASES + [
        {"brand_id": "brand-uuid-toyota", "registration_type": "*",
         "alias_norm": "camry", "model_id": "legacy-camry-2", "match_mode": "prefix"},
    ]
    rows, _ = parse_registration_rows(csv_rows())
    resolved = resolve_registrations(rows, BRAND_ALIASES, aliases)
    assert resolved[0].status == UNKNOWN and "equally well" in resolved[0].reason


def test_a_class_specific_alias_beats_a_wildcard_one():
    aliases = MODEL_ALIASES + [
        {"brand_id": "brand-uuid-toyota", "registration_type": "RY1",
         "alias_norm": "camry", "model_id": "legacy-camry-ry1", "match_mode": "prefix"},
    ]
    rows, _ = parse_registration_rows(csv_rows())
    resolved = resolve_registrations(rows, BRAND_ALIASES, aliases)
    assert resolved[0].model_id == "legacy-camry-ry1"


# ---------------------------------------------------------------------------
# A month is a snapshot, and nothing in it is allowed to vanish
# ---------------------------------------------------------------------------

def test_an_unmatched_row_is_still_a_registration_fact():
    """Nobody has taught the crosswalk this label yet. That is a mapping
    problem, not a reason for the month to lose 40 cars."""
    rows, _ = parse_registration_rows(csv_rows(brand="NOTABRAND", model="MYSTERY", units="40"))
    written = snapshot_rows(resolve_registrations(rows, BRAND_ALIASES, MODEL_ALIASES))
    assert len(written) == 1
    assert written[0]["registrations"] == 40
    assert written[0]["canonical_model_id"] is None and written[0]["model_id"] is None
    assert written[0]["brand_name_raw"] == "NOTABRAND"
    assert written[0]["mapping_method"] == "unmapped"


def test_the_month_total_is_the_same_before_and_after_mapping():
    known, _ = parse_registration_rows(csv_rows(units="100"))
    unknown, _ = parse_registration_rows(csv_rows(brand="NOTABRAND", model="MYSTERY", units="40"))
    written = snapshot_rows(resolve_registrations(known + unknown, BRAND_ALIASES, MODEL_ALIASES))
    assert sum(row["registrations"] for row in written) == 140
    assert sum(1 for row in written if row["canonical_model_id"] or row["model_id"]) == 1


def test_every_unknown_label_leaves_one_piece_of_mapping_work():
    rows, _ = parse_registration_rows(csv_rows(brand="NOTABRAND", model="MYSTERY"))
    work = exception_rows(resolve_registrations(rows, BRAND_ALIASES, MODEL_ALIASES))
    assert len(work) == 1
    assert work[0]["kind"] == "REGISTRATION_IDENTITY"
    assert work[0]["source_identity"]["model"] == "MYSTERY"
    # The source published no trim detail, so this is model-level work.
    assert work[0]["source_identity"]["grain"] == "MODEL"


def test_a_matched_row_leaves_no_mapping_work():
    rows, _ = parse_registration_rows(csv_rows())
    assert exception_rows(resolve_registrations(rows, BRAND_ALIASES, MODEL_ALIASES)) == []


# ---------------------------------------------------------------------------
# Canonical identity, without waiting for a legacy row
# ---------------------------------------------------------------------------

def test_an_alias_carrying_a_canonical_id_attributes_the_row_directly():
    """A car created today has no legacy models row yet, and does not need
    one to receive a label."""
    aliases = [{"brand_id": "brand-uuid-toyota", "registration_type": "*",
                "alias_norm": "camry", "model_id": None,
                "canonical_model_id": "toyota.camry", "match_mode": "prefix"}]
    rows, _ = parse_registration_rows(csv_rows())
    written = snapshot_rows(resolve_registrations(rows, BRAND_ALIASES, aliases))
    assert written[0]["canonical_model_id"] == "toyota.camry"
    assert written[0]["model_id"] is None


def test_a_legacy_alias_still_resolves_so_old_data_keeps_working():
    rows, _ = parse_registration_rows(csv_rows())
    written = snapshot_rows(resolve_registrations(rows, BRAND_ALIASES, MODEL_ALIASES))
    assert written[0]["model_id"] == "legacy-camry"


def test_a_model_level_row_never_receives_a_trim():
    rows, _ = parse_registration_rows(csv_rows())
    written = snapshot_rows(resolve_registrations(rows, BRAND_ALIASES, MODEL_ALIASES))
    assert written[0]["canonical_trim_id"] is None


def test_a_trim_grained_mapping_is_honoured_where_the_source_has_the_detail():
    """Some marques print the grade in the model field. Where a mapping for
    that exact label exists, the trim is kept -- it is not invented."""
    aliases = [{"brand_id": "brand-uuid-toyota", "registration_type": "*",
                "alias_norm": "camryhevpremium", "model_id": "legacy-camry",
                "canonical_model_id": "toyota.camry",
                "canonical_trim_id": "toyota.camry.axvh70.trim.hev_premium",
                "match_mode": "exact"}]
    rows, _ = parse_registration_rows(csv_rows(model="CAMRY HEV PREMIUM"))
    written = snapshot_rows(resolve_registrations(rows, BRAND_ALIASES, aliases))
    assert written[0]["canonical_trim_id"] == "toyota.camry.axvh70.trim.hev_premium"
    assert written[0]["model_name_raw"] == "CAMRY HEV PREMIUM"


# ---------------------------------------------------------------------------
# The files TDR actually uploads
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("fixture", [
    "data/raw/dlt_2025-06.csv",          # the DLT export, Thai headers
    "data/raw_pivot/long_2021-06.csv",   # the normalized long form
])
def test_a_real_monthly_export_parses(fixture):
    """Not a synthetic dict: the two shapes a real month arrives in."""
    import pandas

    path = REPO_ROOT / fixture
    rows, rejected = parse_registration_rows(pandas.read_csv(path).to_dict(orient="records"))
    assert rows and not rejected
    assert all(row.period and row.brand_raw and row.model_raw for row in rows)
    assert sum(row.units for row in rows) > 0


def test_a_real_month_is_written_whole_even_with_an_empty_crosswalk():
    """With nothing taught yet every row is unknown -- and every row is
    still written, so the month's total survives."""
    import pandas

    path = REPO_ROOT / "data/raw/dlt_2025-06.csv"
    rows, _ = parse_registration_rows(pandas.read_csv(path).to_dict(orient="records"))
    resolved = resolve_registrations(rows, {}, [])
    written = snapshot_rows(resolved)
    assert len(written) == len(rows)
    assert sum(r["registrations"] for r in written) == sum(r.units for r in rows)
    assert len(exception_rows(resolved)) == len(rows)


def test_an_unknown_label_from_a_marque_that_files_grades_is_trim_grained():
    """AION files 'AION V 602 LUXURY'; Toyota files 'YARIS'. Not the same row."""
    rows = [
        RegistrationRow(period="2026-06", registration_type="RY1",
                        brand_raw="AION", model_raw="AION V 602 LUXURY", units=419),
        RegistrationRow(period="2026-06", registration_type="RY1",
                        brand_raw="TOYOTA", model_raw="YARIS", units=1200),
    ]
    resolved = resolve_registrations(rows, {}, [])
    exceptions = exception_rows(resolved, trim_detail_brands={"aion"})

    grains = {row["source_identity"]["model"]: row["source_identity"]["grain"]
              for row in exceptions}
    assert grains == {"AION V 602 LUXURY": "TRIM", "YARIS": "MODEL"}


def test_nothing_is_trim_grained_when_no_marque_is_known_to_file_grades():
    rows = [RegistrationRow(period="2026-06", registration_type="RY1",
                            brand_raw="AION", model_raw="AION V 602 LUXURY", units=419)]
    exceptions = exception_rows(resolve_registrations(rows, {}, []))
    assert exceptions[0]["source_identity"]["grain"] == "MODEL"


def test_the_catalogue_is_what_says_which_marques_file_grades():
    """The flag is data, not a list kept in the importer."""
    from tools.import_worker import _trim_detail_brands

    brands = _trim_detail_brands()
    assert "aion" in brands and "byd" in brands
    assert "toyota" not in brands and "honda" not in brands
