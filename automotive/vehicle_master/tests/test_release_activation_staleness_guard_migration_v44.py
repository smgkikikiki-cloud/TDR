"""v44's staleness guard, against a real Postgres: the exact acceptance
scenario -- release A, then a newer release B, then an attempt to
activate A again must be refused and the active pointer must stay B.

Four independent workflows can call publish_vehicle_release(): source-
import, canonical-input, pricefeed and vehicle-release (the last on its
own concurrency group before this pass). Nothing stopped an older
commit's publish call from reaching Postgres after a newer commit's
already activated, silently rolling the active release backward. git
commit ancestry cannot be evaluated inside Postgres, so revision_ordinal
(a monotonic proxy -- typically `git rev-list --count`) is what the RPC
compares instead.
"""

from __future__ import annotations

import json

import pytest

from tests.pg_cluster import apply_production_schema, pg  # noqa: F401


def _release(release_id: str, *, ordinal: int | None, as_of: str = "2026-09-01") -> dict:
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
    # The RPC's single positional argument IS the release object. The
    # `{"release": ...}` wrapper is a PostgREST-over-HTTP convention
    # (tdr_bridge/publish.py's POST body, where a JSON key maps to a
    # function's parameter name) that does not apply calling the function
    # directly in SQL.
    body = json.dumps(release).replace("'", "''")
    return db.try_sql(f"select public.publish_vehicle_release('{body}'::jsonb)")


@pytest.fixture
def db(pg):
    apply_production_schema(pg)
    return pg


def _active(db) -> tuple[str, str]:
    row = db.rows("""select active_release_id, r.revision_ordinal
                     from public.canonical_vehicle_state s
                     join public.canonical_vehicle_releases r on r.release_id = s.active_release_id
                    where s.scope = 'vehicle_catalog'""")
    return (row[0][0], row[0][1]) if row else (None, None)


RELEASE_A = "vehicle-2026-1111111111111111"
RELEASE_B = "vehicle-2026-2222222222222222"


def test_the_acceptance_scenario_a_then_newer_b_then_a_again_is_refused(db):
    ok, error = _publish(db, _release(RELEASE_A, ordinal=100))
    assert ok, error
    assert _active(db) == (RELEASE_A, "100")

    ok, error = _publish(db, _release(RELEASE_B, ordinal=105))
    assert ok, error
    assert _active(db) == (RELEASE_B, "105")

    # The race: an older commit's publish call reaches Postgres AFTER a
    # newer commit's already activated.
    ok, error = _publish(db, _release(RELEASE_A, ordinal=100))
    assert not ok
    assert "stale revision" in error
    assert "vehicle-2026-1111111111111111" in error
    # The active pointer must remain B -- untouched by the refused call.
    assert _active(db) == (RELEASE_B, "105")
    assert db.scalar(f"select status from public.canonical_vehicle_releases"
                     f" where release_id = '{RELEASE_A}'") == "SUPERSEDED"
    assert db.scalar(f"select status from public.canonical_vehicle_releases"
                     f" where release_id = '{RELEASE_B}'") == "ACTIVE"


def test_forward_progress_still_activates_normally(db):
    _publish(db, _release(RELEASE_A, ordinal=100))
    ok, error = _publish(db, _release(RELEASE_B, ordinal=200))
    assert ok, error
    assert _active(db) == (RELEASE_B, "200")


def test_republishing_the_same_release_id_is_not_treated_as_stale(db):
    """An idempotent retry of the currently-active release must not be
    refused just because its own ordinal is not strictly greater."""
    _publish(db, _release(RELEASE_A, ordinal=100))
    ok, error = _publish(db, _release(RELEASE_A, ordinal=100))
    assert ok, error
    assert _active(db) == (RELEASE_A, "100")


def test_a_release_built_without_an_ordinal_is_never_blocked(db):
    """Degrade to the pre-v44 behaviour when the ordinal is unknown --
    never invent a reason to refuse a publish that has no ordinal to
    compare with."""
    _publish(db, _release(RELEASE_A, ordinal=100))
    ok, error = _publish(db, _release(RELEASE_B, ordinal=None))
    assert ok, error
    assert _active(db)[0] == RELEASE_B


def test_an_older_release_can_still_activate_when_nothing_is_active_yet(db):
    """The guard only compares against a currently-active release; the
    very first publish for a scope has nothing to be stale relative to."""
    ok, error = _publish(db, _release(RELEASE_A, ordinal=1))
    assert ok, error
    assert _active(db) == (RELEASE_A, "1")


def test_equal_ordinal_different_release_id_is_treated_as_the_active_one_not_stale(db):
    """Two builds from the exact same commit (re-run, no new history)
    produce equal ordinals; that is a tie, not staleness, and must not be
    refused just because it is not strictly newer."""
    _publish(db, _release(RELEASE_A, ordinal=100))
    rebuilt_same_commit = "vehicle-2026-3333333333333333"
    ok, error = _publish(db, _release(rebuilt_same_commit, ordinal=100))
    assert ok, error
    assert _active(db) == (rebuilt_same_commit, "100")
