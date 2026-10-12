"""Regression rules for conservative vehicle nameplate resolution."""
from vehreg.ice_identity_guard import check_pair, latin_letter_distance


def decision(a, b, brand="BMW", alias_group=""):
    return check_pair(ice_name=a, ice_brand=brand,
                      canonical_name=b, canonical_brand=brand, alias_group=alias_group)


def test_isolated_l_splits_every_brand():
    assert decision("Audi A4 L", "Audi A4", "Audi").disposition == "BLOCK"
    assert decision("Toyota Corolla L", "Toyota Corolla", "Toyota").disposition == "BLOCK"
    assert decision("Audi A4 L", "Audi A4 l", "Audi").disposition == "ALLOW"
    assert decision("Volvo", "Volvo", "Volvo").disposition == "ALLOW"


def test_nameplate_latin_edits_split_over_three():
    assert decision("Nissan March", "Nissan Navara Cab", "Nissan").disposition == "BLOCK"
    assert decision("Honda City", "Honda City Hatchback", "Honda").disposition == "BLOCK"
    assert latin_letter_distance("X4", "X5") == 0


def test_sensitive_codes_require_review_for_small_differences():
    assert decision("BMW X4", "BMW X5").disposition == "REVIEW"
    assert decision("Mazda 6", "Mazda 6e", "Mazda").disposition == "REVIEW"
    assert decision("Volvo XC40", "Volvo XC4O", "Volvo").disposition == "REVIEW"
    assert decision("MG ZS", "MG ZS EV", "MG").disposition == "REVIEW"
    assert decision("Toyota Corolla 1", "Toyota Corolla 2", "Toyota").disposition == "ALLOW"


def test_existing_maxus_mifa_alias_is_preserved():
    result = check_pair(ice_name="7", ice_brand="MG Maxus",
                        canonical_name="MAXUS Mifa 7", canonical_brand="MAXUS",
                        alias_group="maxus_mifa")
    assert result.disposition == "ALLOW"


def test_bare_name_code_is_not_magically_accepted():
    assert decision("BMW 530e", "BMW 530i").disposition == "REVIEW"
