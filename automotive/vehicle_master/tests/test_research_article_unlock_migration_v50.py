"""migration_v50's atomic research-article unlock, against a real Postgres.

The bug this fixes: app/api/research/read/route.ts used to (1) check for an
existing research_article_reads row, (2) spend a research_full quota unit,
(3) insert the read row -- three separate round trips. A quota unit spent
in step 2 with step 3 then failing for any non-duplicate-key reason left a
member charged with no entitlement to show for it; and two unlock attempts
for the SAME article landing in different 5-second fingerprint buckets
(lib/request-fingerprint.ts) could both pass step 1 seeing "not yet read"
and both spend a unit in step 2 before one lost step 3's primary-key race.

tdr_unlock_research_article closes both by doing all three steps inside one
transaction, serialized per (user, article) by its own advisory lock --
not by tdr_consume_usage's fingerprint bucket, which is exactly what let
the race through in the first place.
"""
from __future__ import annotations

import pytest

from tests.pg_cluster import apply_production_schema, pg  # noqa: F401


@pytest.fixture
def db(pg):
    apply_production_schema(pg)
    return pg


def _user(db) -> str:
    return db.scalar("insert into auth.users default values returning id")


def _article(db, *, slug: str = "test-article") -> str:
    return db.scalar(f"""
        insert into public.research_articles (slug, title_th, summary_th, body_th, status, published_at)
        values ('{slug}', 'Title', 'Summary', 'Full body text', 'published', now())
        returning id
    """)


def _unlock(db, user_id: str, article_id: str, *, period_key: str = "2026-09", limit: int | None = None) -> list[str]:
    limit_sql = "null" if limit is None else str(limit)
    rows = db.rows(f"""
        select already_unlocked, allowed, used, quota_limit
        from public.tdr_unlock_research_article('{user_id}'::uuid, '{article_id}'::uuid, '{period_key}', {limit_sql})
    """)
    return rows[0]


def test_first_unlock_spends_one_quota_unit_and_records_the_read(db):
    user_id = _user(db)
    article_id = _article(db)
    already_unlocked, allowed, used, quota_limit = _unlock(db, user_id, article_id, limit=2)
    assert already_unlocked == "f"
    assert allowed == "t"
    assert used == "1"
    read_count = db.scalar(
        f"select count(*) from public.research_article_reads "
        f"where user_id = '{user_id}' and article_id = '{article_id}'"
    )
    assert read_count == "1"


def test_rereading_the_same_article_is_free_and_never_touches_the_quota_counter(db):
    user_id = _user(db)
    article_id = _article(db)
    _unlock(db, user_id, article_id, limit=2)
    already_unlocked, allowed, used, quota_limit = _unlock(db, user_id, article_id, limit=2)
    assert already_unlocked == "t"
    assert allowed == "t"
    counter = db.scalar(
        f"select count from public.tdr_usage_counters "
        f"where user_id = '{user_id}' and metric = 'research_full'"
    )
    # Still 1 from the first unlock -- the second call's whole point is that
    # it never reaches tdr_consume_usage at all.
    assert counter == "1"


def test_a_third_different_article_beyond_the_limit_is_refused_and_records_no_read(db):
    user_id = _user(db)
    article_a = _article(db, slug="a")
    article_b = _article(db, slug="b")
    first = _unlock(db, user_id, article_a, limit=1)
    assert first[1] == "t"  # allowed
    already_unlocked, allowed, used, quota_limit = _unlock(db, user_id, article_b, limit=1)
    assert already_unlocked == "f"
    assert allowed == "f"
    read_count = db.scalar(
        f"select count(*) from public.research_article_reads "
        f"where user_id = '{user_id}' and article_id = '{article_b}'"
    )
    assert read_count == "0", "a refused unlock must never record a read entitlement"
    counter = db.scalar(
        f"select count from public.tdr_usage_counters "
        f"where user_id = '{user_id}' and metric = 'research_full'"
    )
    assert counter == "1", "a refused attempt still counts against the counter, same as tdr_consume_usage alone"


def test_a_null_limit_never_refuses_and_still_counts(db):
    user_id = _user(db)
    article_id = _article(db)
    already_unlocked, allowed, used, quota_limit = _unlock(db, user_id, article_id, limit=None)
    assert allowed == "t"
    assert quota_limit == ""  # NULL comes back as empty string through psql -t -A


def test_unlocking_different_articles_for_different_users_never_collide(db):
    user_a, user_b = _user(db), _user(db)
    article_id = _article(db)
    a_result = _unlock(db, user_a, article_id, limit=1)
    b_result = _unlock(db, user_b, article_id, limit=1)
    assert a_result[1] == "t" and b_result[1] == "t"  # both allowed -- independent quotas
    read_count = db.scalar(
        f"select count(*) from public.research_article_reads where article_id = '{article_id}'"
    )
    assert read_count == "2"


def _function_body() -> str:
    from pathlib import Path
    path = (
        Path(__file__).resolve().parents[3] / "supabase"
        / "migration_v50_research_article_unlock_atomic.sql"
    )
    text = path.read_text(encoding="utf-8").lower()
    start = text.index("create or replace function public.tdr_unlock_research_article")
    end = text.index("revoke all on function public.tdr_unlock_research_article", start)
    return text[start:end]


def test_unlock_rpc_serializes_on_an_advisory_lock_keyed_by_user_and_article_not_the_fingerprint_bucket():
    body = _function_body()
    assert "perform pg_advisory_xact_lock(hashtextextended(" in body
    assert "p_user_id::text" in body and "p_article_id::text" in body
    # The lock must be taken before the existence check, not after --
    # otherwise two callers could both pass the check before either locks.
    assert body.index("pg_advisory_xact_lock") < body.index("exists (")


def test_unlock_rpc_passes_a_null_action_id_relying_on_its_own_lock_not_the_fingerprint_dedup():
    body = _function_body()
    assert "tdr_consume_usage(p_user_id, 'research_full', p_period_key, p_limit, null)" in body


def test_unlock_rpc_is_locked_to_service_role_only():
    from pathlib import Path
    path = (
        Path(__file__).resolve().parents[3] / "supabase"
        / "migration_v50_research_article_unlock_atomic.sql"
    )
    text = path.read_text(encoding="utf-8").lower()
    assert (
        "revoke all on function public.tdr_unlock_research_article(uuid, uuid, text, integer) "
        "from public, anon, authenticated"
    ) in text
    assert (
        "grant execute on function public.tdr_unlock_research_article(uuid, uuid, text, integer) "
        "to service_role"
    ) in text
