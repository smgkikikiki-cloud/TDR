"""migration_v66 (Vehicle DB v3 Phase 1, slice 1): the governed price writer, against a real Postgres.

Built on the same production-order fixture as the v59/v60 tests, then v66 on top. Covers the Phase 1 acceptance
pack of docs/vehicle-db/VEHICLE_DB_V3.md §13 and issue #219 that applies to prices: authority ordering, stale
revision, the 15 % jump guard, revert and double revert, immutable observations, inbox de-duplication, and
per-item atomicity.
"""

from __future__ import annotations

import json

import pytest

from tests.pg_cluster import SUPABASE, pg  # noqa: F401
from tests.test_vehicle_close_old_write_path_migration_v60 import V60
from tests.test_vehicle_engine_rules_migration_v59 import V59, seeded, tree  # noqa: F401
from tools.engine_rule_corpus import T_BASE, T_TOP

V66 = SUPABASE / "migration_v66_vehicle_master_governed_writer.sql"
MODEL = "acme.a"
TODAY = "2026-10-12"


@pytest.fixture
def db(seeded):
    for migration in (V59, V60, V66):
        ok, err = seeded.try_sql(migration.read_text(encoding="utf-8"))
        assert ok, f"{migration.name}: {err}"
    return seeded


def _lit(value) -> str:
    return "'" + json.dumps(value).replace("'", "''") + "'::jsonb"


def _revision(db, trim_id: str) -> int:
    return int(db.scalar(f"select revision from public.vehicle_trims where canonical_id = '{trim_id}'"))


def _served(amount: int) -> dict:
    return {"current_list_price": {"amount_thb": amount, "price_type": "LIST_PRICE"}, "price_history": [],
            "campaign_quote": {}}


def _item(db, trim_id: str, amount: int, actor: str = "OFFICIAL", **extra) -> dict:
    item = {
        "trim_id": trim_id, "expected_trim_revision": _revision(db, trim_id), "actor_kind": actor,
        "new_row": {"amount_thb": amount, "price_type": "LIST_PRICE", "effective_from": TODAY, "observed_at": TODAY,
                    "source": "oem", "source_ref": "https://example.test/new", "vat_included": True},
        "served": _served(amount), "reason": "test",
    }
    item.update(extra)
    return item


def _apply(db, *items: dict, batch: str = "b1") -> list[dict]:
    raw = db.scalar(f"select public.vm_apply_price_changes('{batch}', {_lit(list(items))})::text")
    return json.loads(raw)["results"]


def _count(db, sql: str) -> int:
    return int(db.scalar(sql))


def _prior_record(db, trim_id: str) -> str:
    return db.scalar(
        f"select record_id from public.vehicle_price_ledger where trim_id = '{trim_id}' and price_type = 'LIST_PRICE' "
        "and retracted_at is null order by coalesce(effective_from, observed_at) desc limit 1")


def test_v66_replays_and_is_idempotent(db):
    ok, err = db.try_sql(V66.read_text(encoding="utf-8"))
    assert ok, err


def test_observations_cannot_be_updated_or_deleted(db):
    db.sql("insert into public.vm_observations (run_id, source_kind, field_key, source_url) "
           "values ('r1', 'SCRAPE', 'LIST_PRICE', 'https://example.test/p')")
    for statement in ("update public.vm_observations set run_id = 'x'", "delete from public.vm_observations"):
        ok, err = db.try_sql(statement)
        assert not ok and "immutable" in err


def test_anon_and_authenticated_cannot_call_the_writer(db):
    for role in ("anon", "authenticated"):
        assert db.scalar(
            f"select has_function_privilege('{role}', 'public.vm_apply_price_changes(text,jsonb)', 'EXECUTE')") == "f"
    assert db.scalar(
        "select has_function_privilege('service_role', 'public.vm_apply_price_changes(text,jsonb)', 'EXECUTE')") == "t"


def test_official_change_within_15_percent_applies_and_is_logged(db):
    before = _revision(db, T_BASE)
    prior = _prior_record(db, T_BASE)
    [result] = _apply(db, _item(db, T_BASE, 919000, close_record_ids=[prior], close_effective_to="2026-10-11"))
    assert result["status"] == "APPLIED", result
    assert _revision(db, T_BASE) == before + 1
    assert db.scalar(f"select (current_list_price ->> 'amount_thb')::int from public.vehicle_trims "
                     f"where canonical_id = '{T_BASE}'") == "919000"
    assert db.rows(f"select authority, vat_included from public.vehicle_price_ledger where record_id = '{result['record_id']}'") \
        == [["OFFICIAL", "t"]]
    assert db.scalar(f"select effective_to from public.vehicle_price_ledger where record_id = '{prior}'") == "2026-10-11"
    assert db.rows(
        "select topic, entity_id, field, actor_kind, before_revision, after_revision, batch_id "
        f"from public.canonical_write_revisions where id = '{result['log_id']}'"
    ) == [["price", T_BASE, "LIST_PRICE", "OFFICIAL", str(before), str(before + 1), "b1"]]


def test_stale_revision_changes_nothing(db):
    item = _item(db, T_BASE, 919000)
    item["expected_trim_revision"] -= 1
    ledger_before = _count(db, "select count(*) from public.vehicle_price_ledger")
    [result] = _apply(db, item)
    assert result["status"] == "STALE_REVISION"
    assert _count(db, "select count(*) from public.vehicle_price_ledger") == ledger_before
    assert _count(db, "select count(*) from public.canonical_write_revisions") == 0


def test_legacy_null_authority_counts_as_official_not_admin(db):
    assert db.scalar(f"select authority is null from public.vehicle_price_ledger where trim_id = '{T_BASE}' "
                     "and price_type = 'LIST_PRICE' limit 1") == "t"
    [result] = _apply(db, _item(db, T_BASE, 919000, actor="OFFICIAL"))
    assert result["status"] == "APPLIED", result


def test_official_and_ai_cannot_overwrite_admin_but_admin_can(db):
    [admin] = _apply(db, _item(db, T_BASE, 905000, actor="ADMIN"))
    assert admin["status"] == "APPLIED", admin
    for actor in ("OFFICIAL", "AI"):
        [blocked] = _apply(db, _item(db, T_BASE, 910000, actor=actor), batch=f"b-{actor}")
        assert blocked["status"] == "AUTHORITY_BLOCKED", blocked
        assert blocked["prior_authority"] == "ADMIN"
    assert db.scalar(f"select amount_thb from public.vehicle_price_ledger where trim_id = '{T_BASE}' "
                     "and retracted_at is null order by created_at desc limit 1") == "905000"
    later = _item(db, T_BASE, 915000, actor="ADMIN")
    later["new_row"].update(effective_from="2026-10-13", observed_at="2026-10-13")
    [again] = _apply(db, later, batch="b-admin2")
    assert again["status"] == "APPLIED", again


def test_excel_carries_admin_authority(db):
    [result] = _apply(db, _item(db, T_BASE, 905000, actor="EXCEL"))
    assert result["status"] == "APPLIED", result
    assert db.scalar(f"select authority from public.vehicle_price_ledger where record_id = '{result['record_id']}'") == "ADMIN"
    [blocked] = _apply(db, _item(db, T_BASE, 910000, actor="OFFICIAL"), batch="b2")
    assert blocked["status"] == "AUTHORITY_BLOCKED"


def test_jump_over_15_percent_needs_an_approved_card(db):
    big = 899000 * 120 // 100            # +20 %
    [blocked] = _apply(db, _item(db, T_BASE, big))
    assert blocked["status"] == "JUMP_BLOCKED", blocked
    assert (blocked["prior_amount_thb"], blocked["new_amount_thb"]) == (899000, big)

    card = json.loads(db.scalar(
        f"select public.vm_inbox_propose('PRICE_JUMP', 'jump:{T_BASE}', '{MODEL}', '{T_BASE}', 'h1', '{{}}'::jsonb)::text"))
    pending = _item(db, T_BASE, big, approved_inbox_id=card["id"])
    [still] = _apply(db, pending, batch="b2")
    assert still["status"] == "JUMP_BLOCKED", "an OPEN card is not an approval"

    db.sql(f"update public.vm_inbox set status = 'APPROVED', decided_by = 'owner', decided_at = now() where id = '{card['id']}'")
    [approved] = _apply(db, _item(db, T_BASE, big, approved_inbox_id=card["id"]), batch="b3")
    assert approved["status"] == "APPLIED", approved


def test_admin_is_not_subject_to_the_jump_guard(db):
    [result] = _apply(db, _item(db, T_BASE, 899000 * 2, actor="ADMIN"))
    assert result["status"] == "APPLIED", result


def test_conflicting_price_is_rejected_atomically(db):
    # Same start date as the seeded row, different amount, prior row not closed: the engine rule refuses it,
    # and nothing of the item (ledger row, served values, change log) may survive.
    conflict = _item(db, T_BASE, 910000)
    conflict["new_row"].update(effective_from="2026-01-01", observed_at="2026-01-01")
    ledger_before = _count(db, "select count(*) from public.vehicle_price_ledger")
    revision_before = _revision(db, T_BASE)
    [result] = _apply(db, conflict)
    assert result["status"] == "REJECTED", result
    assert "same-start conflict" in result["error"]
    assert _count(db, "select count(*) from public.vehicle_price_ledger") == ledger_before
    assert _revision(db, T_BASE) == revision_before
    assert _count(db, "select count(*) from public.canonical_write_revisions") == 0


def test_one_bad_item_does_not_block_the_rest_of_the_batch(db):
    good = _item(db, T_BASE, 919000)
    bad = _item(db, T_TOP, 1)
    bad["trim_id"] = "acme.a.g1.trim.does_not_exist"
    results = _apply(db, bad, good)
    assert [r["status"] for r in results] == ["REJECTED", "APPLIED"]


def test_revert_restores_the_prior_price_and_a_second_revert_is_refused(db):
    prior = _prior_record(db, T_BASE)
    [applied] = _apply(db, _item(db, T_BASE, 919000, close_record_ids=[prior], close_effective_to="2026-10-11"))
    assert applied["status"] == "APPLIED", applied
    revert = {
        "trim_id": T_BASE, "expected_trim_revision": applied["revision"], "actor_kind": "ADMIN",
        "new_row": None, "retract_record_ids": [applied["record_id"]], "retraction_reason": "revert of change",
        "reopen_record_ids": [prior], "served": _served(899000), "reverts_id": applied["log_id"], "reason": "revert",
    }
    [reverted] = _apply(db, revert, batch="rv1")
    assert reverted["status"] == "APPLIED", reverted
    assert db.rows(f"select retracted_at is not null, in_release from public.vehicle_price_ledger "
                   f"where record_id = '{applied['record_id']}'") == [["t", "f"]]
    assert db.scalar(f"select effective_to is null from public.vehicle_price_ledger where record_id = '{prior}'") == "t"

    again = dict(revert, expected_trim_revision=reverted["revision"])
    [second] = _apply(db, again, batch="rv2")
    assert second["status"] == "REJECTED", "reverting the same change twice must not write a second compensating entry"
    assert _count(db, f"select count(*) from public.canonical_write_revisions where reverts_id = '{applied['log_id']}'") == 1


def test_revert_after_a_later_change_is_stale(db):
    prior = _prior_record(db, T_BASE)
    [first] = _apply(db, _item(db, T_BASE, 919000, close_record_ids=[prior], close_effective_to="2026-10-11"))
    later = _item(db, T_BASE, 925000, actor="ADMIN", close_record_ids=[first["record_id"]],
                  close_effective_to="2026-10-19")
    later["new_row"].update(effective_from="2026-10-20", observed_at="2026-10-20")
    [second] = _apply(db, later, batch="b2")
    assert second["status"] == "APPLIED", second
    revert_first = {
        "trim_id": T_BASE, "expected_trim_revision": first["revision"], "actor_kind": "ADMIN", "new_row": None,
        "retract_record_ids": [first["record_id"]], "reopen_record_ids": [prior], "served": _served(899000),
        "reverts_id": first["log_id"], "reason": "revert",
    }
    [result] = _apply(db, revert_first, batch="rv")
    assert result["status"] == "STALE_REVISION", "changed since: the entry is skipped, not forced"


def test_a_retraction_is_never_undone(db):
    [applied] = _apply(db, _item(db, T_BASE, 919000))
    retract = {"trim_id": T_BASE, "expected_trim_revision": applied["revision"], "actor_kind": "ADMIN",
               "new_row": None, "retract_record_ids": [applied["record_id"]], "served": _served(899000), "reason": "x"}
    assert _apply(db, retract, batch="r1")[0]["status"] == "APPLIED"
    ok, err = db.try_sql(f"update public.vehicle_price_ledger set retracted_at = null where record_id = '{applied['record_id']}'")
    assert not ok and "never undone" in err


def test_inbox_dedupes_suppresses_rejected_and_reopens_on_new_data(db):
    def propose(source_hash: str, payload: dict | None = None) -> dict:
        return json.loads(db.scalar(
            f"select public.vm_inbox_propose('STRUCTURE', 'struct:{MODEL}', '{MODEL}', null, '{source_hash}', "
            f"{_lit(payload or {})})::text"))

    created = propose("h1")
    assert created["status"] == "CREATED"
    updated = propose("h1", {"seen": 2})
    assert updated["status"] == "UPDATED" and updated["id"] == created["id"]
    assert _count(db, "select count(*) from public.vm_inbox") == 1
    assert db.scalar(f"select seen_count from public.vm_inbox where id = '{created['id']}'") == "2"

    db.sql(f"update public.vm_inbox set status = 'REJECTED', decided_at = now() where id = '{created['id']}'")
    assert propose("h1")["status"] == "SUPPRESSED"          # same data, already decided: never re-proposed
    assert propose("h2")["status"] == "CREATED"             # the source really changed: may propose again
    assert _count(db, "select count(*) from public.vm_inbox") == 2


def test_inbox_allows_only_the_three_kinds(db):
    ok, err = db.try_sql(f"select public.vm_inbox_propose('NEWS', 'k', '{MODEL}', null, 'h', '{{}}'::jsonb)")
    assert not ok and "vm_inbox_kind_check" in err


def test_same_day_correction_retracts_the_superseded_row_in_the_same_item(db):
    [first] = _apply(db, _item(db, T_BASE, 919000))
    assert first["status"] == "APPLIED", first
    fix = _item(db, T_BASE, 921000, retract_record_ids=[first["record_id"]], retraction_reason="superseded same day")
    [second] = _apply(db, fix, batch="b2")
    assert second["status"] == "APPLIED", second
    assert _count(db, f"select count(*) from public.vehicle_price_ledger where trim_id = '{T_BASE}' "
                      "and price_type = 'LIST_PRICE' and retracted_at is null and observed_at = '2026-10-12'") == 1
