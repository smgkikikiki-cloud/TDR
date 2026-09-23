"""migration_v49's replay-safe idempotency for import_run_exceptions,
against a real Postgres: the exact upsert semantics
tools/pricefeed_write.py relies on (``on_conflict=storage_path`` for
import_runs, ``on_conflict=run_id,exception_hash`` for
import_run_exceptions) actually behave the way PostgREST's
``Prefer: resolution=merge-duplicates`` / ``resolution=ignore-duplicates``
promise, at the SQL level -- not just that the client code constructs the
right request (see test_pricefeed_write_replay_idempotency.py for that
half).

The bug this fixes: two different exception-only Price Feed harvests on
the same calendar day named the identical import_runs.storage_path
(derived from the date alone), so the second one's insert hit
import_runs_storage_path_key and 409'd -- a real production failure. Once
storage_path stops colliding, import_run_exceptions itself has no
natural-key uniqueness at all (a bare gen_random_uuid() primary key), so
a genuine replay of the same harvest would still insert a fresh duplicate
exception row every time, or worse, revive one a human had already
resolved by touching it again.
"""

from __future__ import annotations

import pytest

from tests.pg_cluster import apply_production_schema, pg  # noqa: F401


@pytest.fixture
def db(pg):
    apply_production_schema(pg)
    return pg


def _upsert_run(db, storage_path: str, *, exceptions: int = 1) -> str:
    """The exact statement shape PostgREST generates for
    ``POST import_runs?on_conflict=storage_path`` with
    ``Prefer: resolution=merge-duplicates,return=representation``."""
    rows = db.rows(f"""
        insert into public.import_runs
          (storage_path, original_name, source_kind, status, actor, exceptions,
           started_at, finished_at)
        values
          ('{storage_path}', '{storage_path}.json', 'PRICE', 'COMPLETED',
           'price-feed', {exceptions}, now(), now())
        on conflict (storage_path) do update set
          exceptions = excluded.exceptions, finished_at = excluded.finished_at
        returning id
    """)
    return rows[0][0]


def _upsert_exception(db, run_id: str, exception_hash: str, *, reason: str = "r") -> None:
    """The exact statement shape PostgREST generates for
    ``POST import_run_exceptions?on_conflict=run_id,exception_hash`` with
    ``Prefer: resolution=ignore-duplicates``."""
    db.sql(f"""
        insert into public.import_run_exceptions
          (run_id, source_kind, kind, reason, source_identity, status, exception_hash)
        values
          ('{run_id}', 'PRICE', 'PRICE_IDENTITY', '{reason}', '{{}}'::jsonb, 'OPEN',
           '{exception_hash}')
        on conflict (run_id, exception_hash) do nothing
    """)


def test_two_different_exception_only_batches_the_same_day_do_not_collide(db):
    # This is the literal production bug: two distinct storage_paths for
    # two genuinely different harvests, both must succeed.
    id_a = _upsert_run(db, "pricefeed/pricefeed-2026-09-23-aaaaaaaaaaaaaaaa")
    id_b = _upsert_run(db, "pricefeed/pricefeed-2026-09-23-bbbbbbbbbbbbbbbb")
    assert id_a != id_b
    assert db.scalar("select count(*) from public.import_runs") == "2"


def test_replaying_the_same_storage_path_upserts_not_duplicates(db):
    first = _upsert_run(db, "pricefeed/pricefeed-2026-09-23-cccccccccccccccc")
    second = _upsert_run(db, "pricefeed/pricefeed-2026-09-23-cccccccccccccccc")
    assert first == second
    assert db.scalar(
        "select count(*) from public.import_runs "
        "where storage_path = 'pricefeed/pricefeed-2026-09-23-cccccccccccccccc'"
    ) == "1"


def test_replaying_the_same_exception_hash_is_a_true_no_op(db):
    run_id = _upsert_run(db, "pricefeed/pricefeed-2026-09-23-dddddddddddddddd")
    _upsert_exception(db, run_id, "hash-1")
    _upsert_exception(db, run_id, "hash-1")  # the replay
    assert db.scalar(
        f"select count(*) from public.import_run_exceptions where run_id = '{run_id}'"
    ) == "1"


def test_a_replay_does_not_resurrect_an_already_resolved_exception(db):
    run_id = _upsert_run(db, "pricefeed/pricefeed-2026-09-23-eeeeeeeeeeeeeeee")
    _upsert_exception(db, run_id, "hash-2")
    db.sql(f"""
        update public.import_run_exceptions
           set status = 'RESOLVED', resolved_by = 'owner', resolved_at = now()
         where run_id = '{run_id}' and exception_hash = 'hash-2'
    """)
    _upsert_exception(db, run_id, "hash-2")  # a replay of the same harvest
    assert db.rows(
        f"select status from public.import_run_exceptions "
        f"where run_id = '{run_id}' and exception_hash = 'hash-2'"
    ) == [["RESOLVED"]]


def test_different_exception_content_under_the_same_run_is_never_deduped(db):
    run_id = _upsert_run(db, "pricefeed/pricefeed-2026-09-23-ffffffffffffffff",
                         exceptions=2)
    _upsert_exception(db, run_id, "hash-3", reason="conflict A")
    _upsert_exception(db, run_id, "hash-4", reason="conflict B")
    assert db.scalar(
        f"select count(*) from public.import_run_exceptions where run_id = '{run_id}'"
    ) == "2"


def test_a_legacy_writer_that_never_sets_exception_hash_keeps_todays_behavior(db):
    # DLT/ECO/registration exception writers (migration_v41) do not know
    # about exception_hash and never will; each of their inserts must
    # remain its own distinct row, exactly as before this migration.
    run_id = _upsert_run(db, "eco/legacy-writer-batch", exceptions=2)
    db.sql(f"""
        insert into public.import_run_exceptions
          (run_id, source_kind, kind, reason, source_identity, status)
        values
          ('{run_id}', 'ECO', 'VEHICLE_IDENTITY', 'no match', '{{}}'::jsonb, 'OPEN'),
          ('{run_id}', 'ECO', 'VEHICLE_IDENTITY', 'no match', '{{}}'::jsonb, 'OPEN')
    """)
    assert db.scalar(
        f"select count(*) from public.import_run_exceptions where run_id = '{run_id}'"
    ) == "2"
    assert db.scalar(
        f"select count(distinct exception_hash) from public.import_run_exceptions "
        f"where run_id = '{run_id}'"
    ) == "2"
