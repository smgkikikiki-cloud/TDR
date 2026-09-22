"""The v35 -> v36 migration, run against a real Postgres with real rows.

v35 is applied in production. Its schema is
``kind in ('MODEL_GENERATION','MARKET_TRIM','SPEC_DRAFT')`` with a mutable
``DRAFT`` status backed by ``draft_entries``/``default_evidence``; the unified
trim editor writes ``kind = 'TRIM'`` and never drafts. Something has to carry
the live table from one to the other without losing a row.

A source-text assertion cannot show that. Whether a constraint can be dropped
and re-added while rows that violate the new form are still sitting in the
table, whether the statement order is right, whether the thing is re-runnable
-- those are answered by Postgres or not at all. So this test starts a real
cluster, applies the production v35 verbatim, fills it with the rows
production would actually have, applies v36, and then checks both the data and
the constraints.
"""
from __future__ import annotations

import json
from pathlib import Path

from tests.pg_cluster import Cluster, pg  # noqa: F401

REPO_ROOT = Path(__file__).resolve().parents[3]
V35 = REPO_ROOT / "supabase" / "migration_v35_admin_edit_sessions.sql"
V36 = REPO_ROOT / "supabase" / "migration_v36_admin_edit_sessions_trim_kind.sql"
VERIFY = REPO_ROOT / "supabase" / "migration_v36_verify.sql"


def verify_section(number: int) -> str:
    """One numbered section of the operator runbook, as the operator pastes it."""
    text = VERIFY.read_text(encoding="utf-8")
    start = text.index(f"-- SECTION {number} ")
    end = text.find(f"-- SECTION {number + 1} ")
    return text[start:end if end != -1 else len(text)]

#: Exactly what production has: every kind, every status, including a draft
#: mid-edit and a proposal an admin is in the middle of confirming.
SEED = [
    # A finished MODEL_GENERATION proposal awaiting confirmation.
    dict(id="s1", kind="MODEL_GENERATION", status="PENDING_REVIEW", model_id="toyota.yaris",
         trim_id=None, compiled=True),
    # The two trim-scoped kinds, both of which described a trim edit.
    dict(id="s2", kind="MARKET_TRIM", status="PENDING_REVIEW", model_id="aion.aion_es",
         trim_id="aion.aion_es.aes.trim.comfort_private_use_bev", compiled=True),
    dict(id="s3", kind="SPEC_DRAFT", status="PENDING_REVIEW", model_id="aion.aion_es",
         trim_id="aion.aion_es.aes.trim.standard_fleet_taxi_ev_bev", compiled=True),
    # A spec draft an admin never finished: no batch_payload at all.
    dict(id="s4", kind="SPEC_DRAFT", status="DRAFT", model_id="honda.civic",
         trim_id="honda.civic.fe.trim.rs", compiled=False),
    # Already-consumed history, which must stay exactly as it is.
    dict(id="s5", kind="MARKET_TRIM", status="CONSUMED", model_id="mazda.cx30",
         trim_id="mazda.cx30.dm.trim.sp", compiled=True, consumed=True),
]


def _insert(pg: Cluster, row: dict) -> None:
    payload = ("'{\"schema_version\": 1, \"commands\": []}'::jsonb" if row["compiled"] else "null")
    diff = ("'[{\"field\": \"seats\", \"changed\": true}]'::jsonb" if row["compiled"] else "null")
    reason = ("'seed reason'" if row["compiled"] else "null")
    evidence = ("'{\"sourceKind\": \"ADMIN\"}'::jsonb" if row["compiled"] else "null")
    draft = ("'[{\"field_key\": \"powertrain.max_power_kw\", \"value\": 150}]'::jsonb"
             if row["status"] == "DRAFT" else "'[]'::jsonb")
    pg.sql(f"""
        insert into public.admin_edit_sessions
          (id, kind, status, model_id, trim_id, actor, page_release_id,
           draft_entries, default_evidence, batch_payload, diff, reason, evidence,
           expires_at, consumed_at)
        values (
          '{row["id"]}', '{row["kind"]}', '{row["status"]}', '{row["model_id"]}',
          {"null" if row["trim_id"] is None else "'" + row["trim_id"] + "'"},
          'someadmin', 'vehicle-2026-abc',
          {draft}, '{{"sourceKind": "OEM"}}'::jsonb,
          {payload}, {diff}, {reason}, {evidence},
          now() + interval '1 hour',
          {"now()" if row.get("consumed") else "null"}
        );
    """)


def _seed_applied_v35(pg: Cluster) -> None:
    """The starting point this migration must actually work from: the
    production v35 file, applied verbatim, with production-shaped rows in it."""
    pg.file(V35)
    for row in SEED:
        _insert(pg, row)
    assert pg.scalar("select count(*) from public.admin_edit_sessions;") == "5"


def test_v35_applies_and_really_is_the_old_schema(pg: Cluster):
    """Guards the premise. If v35 ever stopped being the applied schema, every
    assertion below would be testing a migration from somewhere imaginary."""
    _seed_applied_v35(pg)
    columns = {row[0] for row in pg.rows(
        "select column_name from information_schema.columns "
        "where table_name = 'admin_edit_sessions';")}
    assert {"draft_entries", "default_evidence"} <= columns
    ok, _ = pg.try_sql("update public.admin_edit_sessions set kind = 'TRIM' where id = 's1';")
    assert not ok, "v35 must not already accept the new kind, or there is nothing to migrate"


def test_v36_migrates_every_row_and_loses_nothing(pg: Cluster):
    _seed_applied_v35(pg)
    pg.file(V36)

    # -- no row is deleted --
    assert pg.scalar("select count(*) from public.admin_edit_sessions;") == "5"
    assert sorted(row[0] for row in pg.rows(
        "select id from public.admin_edit_sessions;")) == ["s1", "s2", "s3", "s4", "s5"]

    kinds = dict(pg.rows("select id, kind from public.admin_edit_sessions order by id;"))
    assert kinds == {"s1": "MODEL_GENERATION", "s2": "TRIM", "s3": "TRIM",
                     "s4": "TRIM", "s5": "TRIM"}, \
        "both trim-scoped kinds become TRIM; MODEL_GENERATION is untouched"

    statuses = dict(pg.rows("select id, status from public.admin_edit_sessions order by id;"))
    assert statuses == {"s1": "PENDING_REVIEW", "s2": "PENDING_REVIEW",
                        "s3": "PENDING_REVIEW", "s4": "CONSUMED", "s5": "CONSUMED"}, \
        "an unfinishable DRAFT is retired as CONSUMED, never deleted"

    # -- a retired draft stays auditable and stays inert --
    retired = pg.rows("select consumed_at is not null, batch_payload is null "
                      "from public.admin_edit_sessions where id = 's4';")[0]
    assert retired == ["t", "t"]

    # -- a proposal an admin was mid-confirm on keeps everything it needs --
    inflight = pg.rows(
        "select batch_payload::text, diff::text, reason, evidence::text, "
        "       expires_at is not null, page_release_id, actor, trim_id "
        "from public.admin_edit_sessions where id = 's2';")[0]
    assert json.loads(inflight[0]) == {"schema_version": 1, "commands": []}
    assert json.loads(inflight[1]) == [{"field": "seats", "changed": True}]
    assert inflight[2] == "seed reason"
    assert json.loads(inflight[3]) == {"sourceKind": "ADMIN"}
    assert inflight[4] == "t"
    assert inflight[5] == "vehicle-2026-abc"
    assert inflight[6] == "someadmin"
    assert inflight[7] == "aion.aion_es.aes.trim.comfort_private_use_bev"

    # -- consumed history is not rewritten --
    assert pg.rows("select consumed_at is not null from public.admin_edit_sessions "
                   "where id = 's5';")[0][0] == "t"


def test_v36_leaves_the_schema_the_new_code_expects(pg: Cluster):
    _seed_applied_v35(pg)
    pg.file(V36)

    columns = {row[0] for row in pg.rows(
        "select column_name from information_schema.columns "
        "where table_name = 'admin_edit_sessions';")}
    assert "draft_entries" not in columns
    assert "default_evidence" not in columns
    # Everything the app reads is still there.
    assert {"id", "kind", "status", "model_id", "trim_id", "actor", "page_release_id",
            "batch_payload", "diff", "reason", "evidence", "created_at", "updated_at",
            "expires_at", "consumed_at"} <= columns

    # -- the new kind is accepted; the retired ones are not --
    ok, _ = pg.try_sql("update public.admin_edit_sessions set kind = 'TRIM' where id = 's1';")
    assert ok
    for gone in ("MARKET_TRIM", "SPEC_DRAFT"):
        ok, error = pg.try_sql(
            f"update public.admin_edit_sessions set kind = '{gone}' where id = 's1';")
        assert not ok and "admin_edit_sessions_kind_check" in error

    # -- DRAFT is no longer a status anything can enter --
    ok, error = pg.try_sql("update public.admin_edit_sessions set status = 'DRAFT' where id = 's1';")
    assert not ok and "admin_edit_sessions_status_check" in error

    # -- the invariants that were protecting the review step still protect it --
    ok, error = pg.try_sql("""
        insert into public.admin_edit_sessions
          (id, kind, status, model_id, actor, page_release_id, expires_at)
        values ('bad', 'TRIM', 'PENDING_REVIEW', 'm', 'a', 'r', now() + interval '1 hour');
    """)
    assert not ok and "pending_review_is_compiled" in error
    ok, error = pg.try_sql("""
        insert into public.admin_edit_sessions
          (id, kind, status, model_id, actor, page_release_id, expires_at,
           batch_payload, diff, reason, evidence)
        values ('bad2', 'TRIM', 'CONSUMED', 'm', 'a', 'r', now() + interval '1 hour',
                '{}'::jsonb, '[]'::jsonb, 'r', '{}'::jsonb);
    """)
    assert not ok and "consumed_has_timestamp" in error

    # -- and the access posture is unchanged: still service-role only --
    assert pg.scalar("select relrowsecurity::text from pg_class "
                     "where relname = 'admin_edit_sessions';") == "true"
    grantees = {row[0] for row in pg.rows(
        "select distinct grantee from information_schema.role_table_grants "
        "where table_name = 'admin_edit_sessions';")}
    assert "anon" not in grantees and "authenticated" not in grantees
    assert "service_role" in grantees


def test_the_new_code_can_actually_write_its_proposal_after_v36(pg: Cluster):
    """The shape lib/edit-session-store.ts's createProposal inserts."""
    _seed_applied_v35(pg)
    pg.file(V36)
    ok, error = pg.try_sql("""
        insert into public.admin_edit_sessions
          (id, kind, status, model_id, trim_id, actor, page_release_id,
           batch_payload, diff, reason, evidence, expires_at)
        values ('new1', 'TRIM', 'PENDING_REVIEW', 'aion.aion_es',
                'aion.aion_es.aes.trim.comfort_private_use_bev', 'someadmin',
                'vehicle-2026-abc',
                '{"schema_version": 1, "commands": []}'::jsonb,
                '[{"field": "rated_range_km", "proposed": "442 km (NEDC)"}]'::jsonb,
                'Manual edit via Canonical Vehicle Editor',
                '{"sourceKind": "ADMIN", "reviewedAt": "2026-01-01"}'::jsonb,
                now() + interval '1 hour');
    """)
    assert ok, error
    # And the atomic one-time consume the store relies on.
    pg.sql("update public.admin_edit_sessions set status = 'CONSUMED', consumed_at = now() "
           "where id = 'new1' and status = 'PENDING_REVIEW' and actor = 'someadmin';")
    assert pg.scalar("select status from public.admin_edit_sessions where id = 'new1';") == "CONSUMED"


def test_v36_is_safe_to_apply_twice(pg: Cluster):
    """A migration runner that retries, or a human who is not sure whether it
    already ran, must not be able to break the table."""
    _seed_applied_v35(pg)
    pg.file(V36)
    before = pg.rows("select id, kind, status from public.admin_edit_sessions order by id;")
    pg.file(V36)
    assert pg.rows("select id, kind, status from public.admin_edit_sessions order by id;") == before


def test_v36_applies_to_an_empty_table_too(pg: Cluster):
    """A staging database that has v35 but no rows yet."""
    pg.file(V35)
    pg.file(V36)
    assert pg.scalar("select count(*) from public.admin_edit_sessions;") == "0"
    ok, _ = pg.try_sql("""
        insert into public.admin_edit_sessions
          (id, kind, status, model_id, actor, page_release_id, batch_payload, diff,
           reason, evidence, expires_at)
        values ('x', 'TRIM', 'PENDING_REVIEW', 'm', 'a', 'r', '{}'::jsonb, '[]'::jsonb,
                'r', '{}'::jsonb, now() + interval '1 hour');
    """)
    assert ok


def test_the_operator_runbook_passes_against_a_migrated_database(pg: Cluster):
    """The SQL a person is told to paste into production has to work there.

    This is the same trap the migration itself fell into: SQL that reads
    correctly and does not run. Sections 1, 3 and 4 of the runbook are
    executed against a database that really has been through v35 -> v36, and
    section 3's assertions all have to come back PASS -- if the migration were
    wrong, or the runbook's own queries were, this fails rather than a person
    discovering it against the live table.
    """
    _seed_applied_v35(pg)
    before = pg.rows(verify_section(1))
    total_before = [row for row in before if row[:2] == ["rows", "TOTAL"]]
    assert total_before == [["rows", "TOTAL", "5"]], before

    pg.file(V36)

    checks = pg.rows(verify_section(3))
    assert checks, "the runbook's after-state query returned nothing"
    failed = [row for row in checks if row[-1] != "PASS"]
    assert not failed, failed

    after = pg.rows(verify_section(1))
    assert [row for row in after if row[:2] == ["rows", "TOTAL"]] == total_before

    # The smoke test writes a row and rolls it back; its last statement must
    # report that nothing was left behind.
    smoke = pg.rows(verify_section(4))
    assert ["loadProposal finds it", "1"] in smoke, smoke
    assert ["consumeProposal left it CONSUMED", "CONSUMED"] in smoke, smoke
    assert ["rows left behind (must be 0)", "0"] in smoke, smoke
    assert pg.scalar("select count(*) from public.admin_edit_sessions;") == "5"
