"""Two releases in the database at once, and what a reader gets.

Every canonical projection is keyed by release, and a release is not
deleted when the next one supersedes it -- that history is the point. So
the same trim has a row per release, and a reader that forgets to say
which release it means gets all of them stacked on top of each other and
the newest wins by luck of the sort order. The admin price panel did
exactly that.

This is the data-level half of that claim, asked of Postgres: what an
unfiltered read returns, what a release-scoped read returns, and what the
serving views return while one release is active. The call sites are
guarded separately (scripts/check-import-flows.ts).
"""

from __future__ import annotations

import pytest

from tests.pg_cluster import apply_production_schema, pg  # noqa: F401

OLD = "vehicle-2026-old"
NEW = "vehicle-2026-new"
MODEL = "toyota.camry"
TRIM = "toyota.camry.axvh70.trim.premium"


def _release(db, release_id: str, *, as_of: str, list_price: int, status: str):
    db.sql(f"""
    insert into public.canonical_vehicle_releases
      (release_id, schema_version, canonical_revision, source_hash, as_of,
       counts, payload, status, activated_at)
      values ('{release_id}', 1, '{release_id}', 'hash-{release_id}', '{as_of}',
              '{{}}'::jsonb, '{{}}'::jsonb, '{status}',
              {'now()' if status == 'ACTIVE' else 'null'});
    insert into public.canonical_brand_projection
      (release_id, canonical_id, slug, name_en, payload)
      values ('{release_id}', 'toyota', 'toyota', 'Toyota', '{{}}'::jsonb);
    insert into public.canonical_model_projection
      (release_id, canonical_id, brand_id, slug, name_en, status, payload)
      values ('{release_id}', '{MODEL}', 'toyota', 'toyota-camry', 'Camry',
              'CURRENT', '{{}}'::jsonb);
    insert into public.canonical_generation_projection
      (release_id, canonical_id, model_id, code, payload)
      values ('{release_id}', 'toyota.camry.axvh70', '{MODEL}', 'AXVH70', '{{}}'::jsonb);
    insert into public.canonical_market_trim_projection
      (release_id, canonical_id, model_id, generation_id, name, powertrain, status, payload)
      values ('{release_id}', '{TRIM}', '{MODEL}', 'toyota.camry.axvh70',
              'Premium', 'HEV', 'CURRENT', '{{}}'::jsonb);
    insert into public.canonical_price_projection
      (release_id, record_id, trim_id, amount_thb, price_type, effective_from,
       observed_at, source, payload)
      values ('{release_id}', '{release_id}-p1', '{TRIM}', {list_price}, 'LIST_PRICE',
              '{as_of}', '{as_of}', 'admin', '{{}}'::jsonb);
    """)


@pytest.fixture
def db(pg):
    apply_production_schema(pg)
    # Last year's release is still there, as it always is, and this year's
    # is the one being served.
    _release(pg, OLD, as_of="2025-06-01", list_price=1_799_000, status="SUPERSEDED")
    _release(pg, NEW, as_of="2026-06-01", list_price=1_899_000, status="ACTIVE")
    pg.sql(f"""insert into public.canonical_vehicle_state (scope, active_release_id)
               values ('vehicle_catalog', '{NEW}')""")
    return pg


def test_an_unscoped_price_read_really_does_return_both_releases(db):
    """The failure the scoping exists to prevent, demonstrated."""
    assert db.rows(
        f"select release_id, amount_thb from public.canonical_price_projection"
        f" where trim_id = '{TRIM}' order by release_id"
    ) == [[NEW, "1899000"], [OLD, "1799000"]]


def test_a_release_scoped_read_returns_that_release_and_nothing_else(db):
    assert db.rows(
        f"select amount_thb from public.canonical_price_projection"
        f" where trim_id = '{TRIM}' and release_id = '{NEW}'") == [["1899000"]]
    assert db.rows(
        f"select amount_thb from public.canonical_price_projection"
        f" where trim_id = '{TRIM}' and release_id = '{OLD}'") == [["1799000"]]


def test_the_serving_views_show_one_release_at_a_time(db):
    assert db.rows("select canonical_id from public.current_vehicle_models") == [[MODEL]]
    assert db.rows("select canonical_id from public.current_market_trims") == [[TRIM]]
    assert db.rows("select amount_thb from public.current_price_ledger") == [["1899000"]]


def test_activating_the_older_release_moves_every_reader_back_together(db):
    """A rollback is one row, and nothing is left reading the other one."""
    db.sql(f"""update public.canonical_vehicle_state
                  set active_release_id = '{OLD}', activated_at = now()
                where scope = 'vehicle_catalog'""")

    assert db.rows("select amount_thb from public.current_price_ledger") == [["1799000"]]
    assert db.rows("select canonical_id from public.current_market_trims") == [[TRIM]]
    # And the newer release is still there to go back to.
    assert db.scalar("select count(*) from public.canonical_price_projection") == "2"


def test_a_trim_that_only_the_older_release_had_is_not_served(db):
    db.sql(f"""
      insert into public.canonical_market_trim_projection
        (release_id, canonical_id, model_id, generation_id, name, powertrain, status, payload)
      values ('{OLD}', '{MODEL}.axvh70.trim.discontinued', '{MODEL}',
              'toyota.camry.axvh70', 'Discontinued', 'HEV', 'CURRENT', '{{}}'::jsonb)""")

    assert db.rows("select canonical_id from public.current_market_trims") == [[TRIM]]
