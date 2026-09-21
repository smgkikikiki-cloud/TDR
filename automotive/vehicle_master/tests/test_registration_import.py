"""A DLT file is registration data, and is read as registration data."""

import pytest

from vehreg.registration_import import (
    MATCHED, UNKNOWN, UnsupportedRegistrationSchema, parse_registration_rows,
    registration_payload, resolve_registrations,
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
# Writing it twice
# ---------------------------------------------------------------------------

def test_the_upsert_key_is_what_makes_a_re_import_replace_rather_than_duplicate():
    """The table is unique on (period, registration_type, brand, model), so
    the same month re-uploaded lands on the same row."""
    rows, _ = parse_registration_rows(csv_rows())
    first = registration_payload(
        resolve_registrations(rows, BRAND_ALIASES, MODEL_ALIASES)[0], mapping_method="import-alias")
    again = registration_payload(
        resolve_registrations(rows, BRAND_ALIASES, MODEL_ALIASES)[0], mapping_method="import-alias")
    key = ("period", "registration_type", "brand_name_raw", "model_name_raw")
    assert tuple(first[k] for k in key) == tuple(again[k] for k in key)


def test_a_corrected_file_carries_the_new_number_on_the_same_key():
    original, _ = parse_registration_rows(csv_rows(units="120"))
    corrected, _ = parse_registration_rows(csv_rows(units="131"))
    a = registration_payload(resolve_registrations(original, BRAND_ALIASES, MODEL_ALIASES)[0],
                             mapping_method="import-alias")
    b = registration_payload(resolve_registrations(corrected, BRAND_ALIASES, MODEL_ALIASES)[0],
                             mapping_method="import-alias")
    assert a["period"] == b["period"] and a["model_name_raw"] == b["model_name_raw"]
    assert a["registrations"] == 120 and b["registrations"] == 131


def test_a_new_month_is_a_different_row():
    august, _ = parse_registration_rows(csv_rows(period="2026-08"))
    september, _ = parse_registration_rows(csv_rows(period="2026-09"))
    a = registration_payload(resolve_registrations(august, BRAND_ALIASES, MODEL_ALIASES)[0],
                             mapping_method="import-alias")
    b = registration_payload(resolve_registrations(september, BRAND_ALIASES, MODEL_ALIASES)[0],
                             mapping_method="import-alias")
    assert a["period"] != b["period"]


def test_registration_rows_never_carry_vehicle_specs():
    """Registration says how many, never what the car is made of."""
    rows, _ = parse_registration_rows(csv_rows())
    payload = registration_payload(
        resolve_registrations(rows, BRAND_ALIASES, MODEL_ALIASES)[0], mapping_method="import-alias")
    assert set(payload) == {
        "period", "registration_type", "brand_name_raw", "model_name_raw",
        "registrations", "model_id", "mapping_method",
    }
