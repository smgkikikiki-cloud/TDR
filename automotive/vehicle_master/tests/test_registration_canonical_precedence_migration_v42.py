"""v42 against a real Postgres: the exact acceptance scenario from the
audit -- a row with no legacy model_id at all, resolved purely through
registrations.canonical_model_id.

Before v42, registration_reporting_source derived canonical_model_id only
through the reverse crosswalk (current_vehicle_models.tdr_model_id =
registrations.model_id). A row created by assignRegistrationIdentity for
a car with no legacy row yet -- model_id NULL, canonical_model_id set
directly -- came out of every view built on registration_reporting_source
as unmapped, even though it had just been mapped. This proves the fix at
the one place the precedence has to hold: what Postgres actually returns.
"""

from __future__ import annotations

import pytest

from tests.pg_cluster import apply_production_schema, pg  # noqa: F401

BRAND = "66666666-6666-6666-6666-666666666666"
NEW_MODEL_CANONICAL = "newbrand.newmodel"
RELEASE = "vehicle-2026-v42"


@pytest.fixture
def db(pg):
    apply_production_schema(pg)
    pg.sql(f"""
    insert into public.canonical_vehicle_releases
      (release_id, schema_version, canonical_revision, source_hash, as_of,
       counts, payload, status, activated_at)
      values ('{RELEASE}', 1, 'rev', 'hash', '2026-09-01',
              '{{}}'::jsonb, '{{}}'::jsonb, 'ACTIVE', now());
    insert into public.canonical_vehicle_state (scope, active_release_id)
      values ('vehicle_catalog', '{RELEASE}');
    insert into public.canonical_brand_projection
      (release_id, canonical_id, slug, name_en, payload)
      values ('{RELEASE}', 'newbrand', 'newbrand', 'New Brand', '{{}}'::jsonb);
    -- The car exists in the active canonical release, but has NO
    -- tdr_model_id -- exactly a car created in the admin today, before
    -- any release has rebuilt the legacy crosswalk for it.
    insert into public.canonical_model_projection
      (release_id, canonical_id, tdr_model_id, brand_id, slug, name_en, status, payload)
      values ('{RELEASE}', '{NEW_MODEL_CANONICAL}', null, 'newbrand', 'newbrand-newmodel',
              'New Model', 'CURRENT', '{{}}'::jsonb);
    """)
    return pg


def _insert_registration(db, *, canonical_model_id, model_id="null", registrations=87,
                         model_name_raw="NEW MODEL", period="2026-06-01"):
    db.sql(f"""
      insert into public.registrations
        (period, registration_type, brand_name_raw, model_name_raw, registrations,
         model_id, canonical_model_id, mapping_method)
        values ('{period}', 'PC', 'NEWBRAND', '{model_name_raw}', {registrations},
                {model_id}, {"null" if canonical_model_id is None else f"'{canonical_model_id}'"},
                'admin-assigned-alias')""")


def test_the_acceptance_scenario_resolves_through_canonical_model_id_alone(db):
    """model_id = NULL, canonical_model_id = 'newbrand.newmodel', registrations = 87."""
    _insert_registration(db, canonical_model_id=NEW_MODEL_CANONICAL)

    # registration_reporting_source: the one compatibility boundary every
    # other registration_* view reads through.
    rows = db.rows("select model_id, canonical_model_id, registrations, fact_source"
                   " from public.registration_reporting_source"
                   " where model_name_raw = 'NEW MODEL'")
    assert rows == [["", NEW_MODEL_CANONICAL, "87", "legacy"]]


def test_mapped_coverage_counts_it_and_total_market_is_unchanged(db):
    _insert_registration(db, canonical_model_id=NEW_MODEL_CANONICAL)
    # A genuinely unmapped row in the same month, for contrast.
    _insert_registration(db, canonical_model_id=None, model_name_raw="UNKNOWN THING",
                         registrations=13)

    row = db.rows("select raw_rows, total_registrations, mapped_rows, mapped_registrations"
                  " from public.registration_analytics_coverage where period = '2026-06-01'")
    assert row == [["2", "100", "1", "87"]]
    # The total market did not move: both rows are still counted in
    # total_registrations, mapped or not.
    assert db.scalar("select sum(registrations) from public.registrations"
                     " where period = '2026-06-01'") == "100"


def test_a_row_with_both_ids_null_is_still_the_only_thing_that_counts_as_unmapped(db):
    _insert_registration(db, canonical_model_id=NEW_MODEL_CANONICAL)
    _insert_registration(db, canonical_model_id=None, model_name_raw="UNKNOWN THING",
                         registrations=13)

    unmapped = db.rows("select model_name_raw from public.registrations"
                       " where model_id is null and canonical_model_id is null")
    assert unmapped == [["UNKNOWN THING"]]


def test_the_legacy_reverse_crosswalk_still_works_when_canonical_model_id_is_not_set(db):
    """No regression: a row resolved only through the old bridge still resolves."""
    legacy_model_id = "77777777-7777-7777-7777-777777777777"
    db.sql(f"""
      insert into public.models (id, slug, brand_id, name_th, name_en)
        values ('{legacy_model_id}', 'newbrand-legacy', (
          select id from public.brands limit 1
        ), 'ทดสอบ', 'Legacy Bridge Test');
    """)
    # Give the brand a row if none exists.
    if db.scalar("select count(*) from public.brands") == "0":
        db.sql(f"""insert into public.brands (id, slug, name_th, name_en)
                    values (gen_random_uuid(), 'newbrand-legacy-brand', 'ทดสอบ', 'Legacy Brand')""")
        db.sql(f"""update public.models set brand_id = (select id from public.brands limit 1)
                     where id = '{legacy_model_id}'""")
    db.sql(f"""
      update public.canonical_model_projection
         set tdr_model_id = '{legacy_model_id}'
       where release_id = '{RELEASE}' and canonical_id = '{NEW_MODEL_CANONICAL}';
    """)
    _insert_registration(db, canonical_model_id=None, model_id=f"'{legacy_model_id}'",
                        model_name_raw="LEGACY BRIDGE ROW", registrations=50)

    rows = db.rows("select canonical_model_id from public.registration_reporting_source"
                   " where model_name_raw = 'LEGACY BRIDGE ROW'")
    assert rows == [[NEW_MODEL_CANONICAL]]


def test_canonical_model_id_on_the_row_outranks_a_conflicting_legacy_crosswalk(db):
    """Precedence is precedence: the row's own canonical_model_id always wins."""
    other_release_model = "otherbrand.othermodel"
    legacy_model_id = "88888888-8888-8888-8888-888888888888"
    db.sql(f"""insert into public.brands (id, slug, name_th, name_en)
                values (gen_random_uuid(), 'otherbrand', 'ทดสอบ', 'Other Brand')""")
    db.sql(f"""insert into public.models (id, slug, brand_id, name_th, name_en)
                values ('{legacy_model_id}', 'otherbrand-othermodel',
                        (select id from public.brands where slug = 'otherbrand'),
                        'ทดสอบ', 'Other Model')""")
    db.sql(f"""insert into public.canonical_model_projection
                  (release_id, canonical_id, tdr_model_id, brand_id, slug, name_en, status, payload)
                values ('{RELEASE}', '{other_release_model}', '{legacy_model_id}', 'newbrand',
                        'otherbrand-othermodel', 'Other Model', 'CURRENT', '{{}}'::jsonb)""")
    # A row that names BOTH: canonical_model_id says one car, model_id's
    # reverse crosswalk says a different one.
    _insert_registration(db, canonical_model_id=NEW_MODEL_CANONICAL,
                        model_id=f"'{legacy_model_id}'",
                        model_name_raw="AMBIGUOUS ROW", registrations=5)

    rows = db.rows("select canonical_model_id from public.registration_reporting_source"
                   " where model_name_raw = 'AMBIGUOUS ROW'")
    assert rows == [[NEW_MODEL_CANONICAL]]
