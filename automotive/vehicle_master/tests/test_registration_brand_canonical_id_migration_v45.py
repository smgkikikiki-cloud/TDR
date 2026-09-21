"""v45 against a real Postgres: acceptance case B -- a brand-new marque
AND a brand-new model, neither with a legacy row, resolved and bound
through canonical ids alone.

registration_model_aliases.brand_id was part of the table's own primary
key, so making it nullable meant replacing that key (Postgres refuses
NULL in a primary-key column outright) -- caught by the migration-chain
replay test before this file existed: the naive `alter column ... drop
not null` failed with `column "brand_id" is in a primary key`.
"""

from __future__ import annotations

import pytest

from tests.pg_cluster import apply_production_schema, pg  # noqa: F401


@pytest.fixture
def db(pg):
    apply_production_schema(pg)
    return pg


def test_a_canonical_only_brand_alias_can_be_inserted_with_no_legacy_brand(db):
    ok, error = db.try_sql("""
        insert into public.registration_brand_aliases (raw_brand_norm, canonical_brand_id)
        values ('newmarque', 'newbrand')""")
    assert ok, error
    assert db.scalar("select canonical_brand_id from public.registration_brand_aliases"
                     " where raw_brand_norm = 'newmarque'") == "newbrand"


def test_a_brand_alias_still_has_to_name_something(db):
    ok, error = db.try_sql("""
        insert into public.registration_brand_aliases (raw_brand_norm)
        values ('nothing')""")
    assert not ok and "registration_brand_aliases_identity_check" in error


def test_a_canonical_only_model_alias_can_be_inserted_with_no_legacy_brand_or_model(db):
    """The exact acceptance case: new brand + new model, no tdr_brand_id,
    no tdr_model_id anywhere."""
    ok, error = db.try_sql("""
        insert into public.registration_model_aliases
          (canonical_brand_id, registration_type, alias_norm, canonical_model_id, match_mode)
        values ('newbrand', 'PC', 'firstmodel', 'newbrand.firstmodel', 'exact')""")
    assert ok, error
    assert db.scalar("select canonical_model_id from public.registration_model_aliases"
                     " where alias_norm = 'firstmodel'") == "newbrand.firstmodel"


def test_a_model_alias_still_has_to_name_a_brand(db):
    ok, error = db.try_sql("""
        insert into public.registration_model_aliases
          (registration_type, alias_norm, canonical_model_id, match_mode)
        values ('PC', 'orphan', 'nobrand.orphan', 'exact')""")
    assert not ok and "registration_model_aliases_identity_check" in error


def test_the_replacement_uniqueness_rule_still_catches_a_duplicate_canonical_alias(db):
    db.sql("""insert into public.registration_model_aliases
                 (canonical_brand_id, registration_type, alias_norm, canonical_model_id, match_mode)
               values ('newbrand', 'PC', 'firstmodel', 'newbrand.firstmodel', 'exact')""")
    ok, error = db.try_sql("""
        insert into public.registration_model_aliases
          (canonical_brand_id, registration_type, alias_norm, canonical_model_id, match_mode)
        values ('newbrand', 'PC', 'firstmodel', 'newbrand.firstmodel_v2', 'exact')""")
    assert not ok and "registration_model_aliases_identity_idx" in error


def test_the_replacement_uniqueness_rule_still_catches_a_duplicate_legacy_alias(db):
    """No regression: the legacy (brand_id, registration_type, alias_norm)
    uniqueness the old primary key enforced still holds."""
    brand = db.scalar("""insert into public.brands (id, slug, name_th, name_en)
                          values (gen_random_uuid(), 'toyota', 'โตโยต้า', 'Toyota')
                          returning id""")
    db.sql(f"""insert into public.registration_model_aliases
                  (brand_id, registration_type, alias_norm, model_id, match_mode)
                values ('{brand}', 'PC', 'camry',
                        (select id from public.models limit 1), 'prefix')""") \
        if db.scalar("select count(*) from public.models") != "0" else None
    # A model row to reference.
    model = db.scalar(f"""insert into public.models (id, slug, brand_id, name_th, name_en)
                          values (gen_random_uuid(), 'toyota-camry', '{brand}', 'แคมรี่', 'Camry')
                          returning id""")
    db.sql(f"""insert into public.registration_model_aliases
                  (brand_id, registration_type, alias_norm, model_id, match_mode)
                values ('{brand}', 'PC', 'camry', '{model}', 'prefix')""")
    ok, error = db.try_sql(f"""
        insert into public.registration_model_aliases
          (brand_id, registration_type, alias_norm, model_id, match_mode)
        values ('{brand}', 'PC', 'camry', '{model}', 'prefix')""")
    assert not ok and "registration_model_aliases_identity_idx" in error


def test_a_legacy_alias_and_a_canonical_only_alias_never_collide_on_null_coalescing(db):
    """Two different rows that both happen to have brand_id NULL but
    different canonical_brand_id values are NOT the same identity."""
    ok1, e1 = db.try_sql("""insert into public.registration_model_aliases
        (canonical_brand_id, registration_type, alias_norm, canonical_model_id, match_mode)
        values ('brand-a', 'PC', 'samelabel', 'brand-a.model', 'exact')""")
    ok2, e2 = db.try_sql("""insert into public.registration_model_aliases
        (canonical_brand_id, registration_type, alias_norm, canonical_model_id, match_mode)
        values ('brand-b', 'PC', 'samelabel', 'brand-b.model', 'exact')""")
    assert ok1, e1
    assert ok2, e2
    assert db.scalar("select count(*) from public.registration_model_aliases"
                     " where alias_norm = 'samelabel'") == "2"
