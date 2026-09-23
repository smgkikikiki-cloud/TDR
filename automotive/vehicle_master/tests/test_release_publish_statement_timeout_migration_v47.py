"""v47's function-level statement_timeout on publish_vehicle_release(jsonb),
against a real Postgres: the RPC gets its own 45s budget regardless of
the calling role's session default, and everything v44 already proved
about it (SECURITY DEFINER, search_path, staleness guard, atomic
activation) still holds once this migration has run.

The September 2026 ECO Sticker bulk import's release (tens of thousands
of spec facts and price records) was cancelled mid-transaction with
Postgres error 57014 on every publish attempt: the authenticator role's
own 8s session default was what the RPC's execution was constrained by,
since it had no timeout of its own. This is the fix, scoped to exactly
this one function.
"""

from __future__ import annotations

import json

import pytest

from tests.pg_cluster import apply_production_schema, pg  # noqa: F401


def _release(release_id: str, *, ordinal: int | None = None,
            as_of: str = "2026-09-01") -> dict:
    payload = {
        "schema_version": 1,
        "release_id": release_id,
        "canonical_revision": f"sha-for-{release_id}",
        "source_hash": release_id.rsplit("-", 1)[-1],
        "as_of": as_of,
        "counts": {"brands": 0, "models": 0, "generations": 0,
                   "market_trims": 0, "price_ledger": 0, "spec_facts": 0},
        "brands": [], "models": [], "generations": [],
        "market_trims": [], "price_ledger": [], "spec_facts": [],
    }
    if ordinal is not None:
        payload["revision_ordinal"] = ordinal
    return payload


def _publish(db, release: dict) -> tuple[bool, str]:
    body = json.dumps(release).replace("'", "''")
    return db.try_sql(f"select public.publish_vehicle_release('{body}'::jsonb)")


@pytest.fixture
def db(pg):
    apply_production_schema(pg)
    return pg


def test_the_function_carries_its_own_statement_timeout(db):
    configs = [row[0] for row in db.rows(
        "select unnest(proconfig) from pg_proc where proname = 'publish_vehicle_release'")]
    assert "statement_timeout=45s" in configs
    # Untouched by this migration -- v44/v16's own hardening, still there.
    assert any(c.startswith("search_path=") for c in configs)


def test_no_role_session_default_changed(db):
    """The fix is scoped to the one function. Nothing else moved."""
    authenticator = db.rows(
        "select setting from pg_db_role_setting drs "
        "join pg_roles r on r.oid = drs.setrole "
        "join pg_settings s on s.name = 'statement_timeout' "
        "where r.rolname = 'authenticator'")
    # No role-level statement_timeout override exists for authenticator in
    # this schema (the 8s constraint production sees is a platform-level
    # Supabase default, not something these migrations set) -- and this
    # migration must not be the one that introduces one.
    assert authenticator == []


def test_publish_still_activates_a_release_normally(db):
    ok, err = _publish(db, _release("vehicle-2026-aaaaaaaaaaaaaaaa"))
    assert ok, err
    active = db.rows(
        "select active_release_id from public.canonical_vehicle_state "
        "where scope = 'vehicle_catalog'")
    assert active == [["vehicle-2026-aaaaaaaaaaaaaaaa"]]


def test_the_staleness_guard_from_v44_still_refuses_an_older_ordinal(db):
    ok, _ = _publish(db, _release("vehicle-2026-bbbbbbbbbbbbbbbb", ordinal=10))
    assert ok
    ok, _ = _publish(db, _release("vehicle-2026-cccccccccccccccc", ordinal=20))
    assert ok
    ok, err = _publish(db, _release("vehicle-2026-dddddddddddddddd", ordinal=5))
    assert not ok
    assert "stale revision" in err
    active = db.rows(
        "select active_release_id from public.canonical_vehicle_state "
        "where scope = 'vehicle_catalog'")
    assert active == [["vehicle-2026-cccccccccccccccc"]]


def test_the_function_is_still_security_definer_and_service_role_only(db):
    row = db.rows(
        "select prosecdef from pg_proc where proname = 'publish_vehicle_release'")
    assert row == [["t"]]
    # The owner (postgres, in this throwaway cluster) always appears here
    # implicitly -- that is Postgres's own behaviour, not a grant this
    # migration made. What matters is that no other role was granted
    # access and that service_role explicitly was.
    grantees = {g[0] for g in db.rows(
        "select grantee from information_schema.role_routine_grants "
        "where routine_name = 'publish_vehicle_release'")}
    assert grantees == {"postgres", "service_role"}
    assert "anon" not in grantees and "authenticated" not in grantees
