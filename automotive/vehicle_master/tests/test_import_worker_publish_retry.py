"""A publish that fails after a successful push must not strand the run.

Before this pass: commit_sha and release_id were both written by
finalize(), which only ever runs after publish succeeds. A push that
landed cleanly followed by a publish that failed (or a cancelled job)
left the run WRITTEN_PENDING_PUBLISH with NO record of what it had
pushed. The next scheduled tick saw a clean working tree -- nothing NEW
of its own to commit -- and skipped publishing entirely, so the run
stayed stuck until some unrelated future import happened to produce a
fresh diff on its own.

This exercises the real sequence -- mark_committed() right after push,
a publish that fails, stuck_runs() finding it on the next tick with NO
new diff, and finalize() completing it -- against an in-memory fake of
the exact PostgREST calls tools.import_worker makes. Nothing here is a
string search over the workflow YAML; every assertion reads back state a
real call produced.
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import pytest

from tools import import_worker


class FakeImportRuns:
    """Just enough of import_runs + PostgREST's filter query strings to
    exercise pending_runs/mark_committed/stuck_runs/finalize for real."""

    def __init__(self):
        self.rows: dict[str, dict] = {}
        self._next = 1

    def insert(self, **fields) -> str:
        run_id = f"run-{self._next}"
        self._next += 1
        self.rows[run_id] = {"id": run_id, "commit_sha": None, "release_id": None, **fields}
        return run_id

    def _matches(self, row: dict, filters: dict[str, list[str]]) -> bool:
        for key, values in filters.items():
            if key in ("select", "limit", "order"):
                continue
            value = values[0]
            if value.startswith("eq."):
                if str(row.get(key)) != value[len("eq."):]:
                    return False
            elif value == "not.is.null":
                if row.get(key) is None:
                    return False
            elif value == "is.null":
                if row.get(key) is not None:
                    return False
            else:  # pragma: no cover - every filter used here is one of the above
                raise AssertionError(f"unhandled filter {key}={value}")
        return True

    def rest(self, method: str, path: str, payload=None, *, prefer=None):
        parsed = urlparse(path)
        table, _, query = parsed.path.partition("?") if "?" not in path else (parsed.path, "", parsed.query)
        query = parsed.query
        filters = parse_qs(query)
        assert table.split("?")[0] == "import_runs" or parsed.path == "import_runs"

        if method == "GET":
            matched = [row for row in self.rows.values() if self._matches(row, filters)]
            select = filters.get("select", ["*"])[0].split(",")
            return [{k: row[k] for k in select if k in row} for row in matched]

        if method == "PATCH":
            id_filter = filters.get("id", [None])[0]
            assert id_filter and id_filter.startswith("eq.")
            target_id = id_filter[len("eq."):]
            row = self.rows.get(target_id)
            if row is None:
                return []
            if not self._matches(row, filters):
                return []
            row.update(payload)
            return [dict(row)]

        raise AssertionError(f"unhandled method {method}")  # pragma: no cover


@pytest.fixture
def db(monkeypatch):
    fake = FakeImportRuns()
    monkeypatch.setattr(import_worker, "_rest", fake.rest)
    return fake


def test_a_run_whose_publish_failed_is_recorded_with_its_commit(db):
    run_id = db.insert(status="WRITTEN_PENDING_PUBLISH", source_kind="ECO")

    import_worker.mark_committed([run_id], "deadbeef01")

    assert db.rows[run_id]["commit_sha"] == "deadbeef01"
    assert db.rows[run_id]["status"] == "WRITTEN_PENDING_PUBLISH"
    assert db.rows[run_id]["release_id"] is None


def test_the_run_is_findable_as_stuck_once_committed_but_not_yet_published(db):
    run_id = db.insert(status="WRITTEN_PENDING_PUBLISH", source_kind="ECO")
    import_worker.mark_committed([run_id], "deadbeef01")

    assert stuck_ids(db) == [run_id]


def test_a_run_with_no_commit_sha_yet_is_not_stuck_it_is_just_pending(db):
    """The normal, in-flight state -- publish has not been attempted at
    all yet -- must not be confused with a publish that already failed."""
    run_id = db.insert(status="WRITTEN_PENDING_PUBLISH", source_kind="ECO")

    assert stuck_ids(db) == []


def test_a_completed_run_is_not_stuck(db):
    run_id = db.insert(status="COMPLETED", source_kind="ECO",
                       commit_sha="deadbeef01", release_id="vehicle-2026-x")
    assert stuck_ids(db) == []


def test_the_full_recovery_sequence_completes_the_run_with_no_new_diff(db):
    """The exact acceptance case: commit succeeded, publish failed, the
    next tick has nothing new to commit -- and still finishes the run."""
    run_id = db.insert(status="WRITTEN_PENDING_PUBLISH", source_kind="ECO")

    # Tick 1: the push succeeded, the publish step (simulated, not called
    # here) then failed. The commit is on record regardless.
    import_worker.mark_committed([run_id], "deadbeef01")
    assert db.rows[run_id]["status"] == "WRITTEN_PENDING_PUBLISH"

    # Tick 2: NO new upload, NO new diff -- this is exactly what the old
    # `if git status --porcelain; then changed=false; publish skipped`
    # path produced, and it is why the run stayed stuck forever. Recovery
    # does not depend on there being anything new to commit.
    found = stuck_ids(db)
    assert found == [run_id]

    import_worker.finalize(found, "deadbeef01", "vehicle-2026-recovered")

    assert db.rows[run_id]["status"] == "COMPLETED"
    assert db.rows[run_id]["release_id"] == "vehicle-2026-recovered"
    assert stuck_ids(db) == []


def test_finalising_one_run_never_completes_a_different_ones_work(db):
    """Named runs only -- sweeping every WRITTEN_PENDING_PUBLISH row would
    let one run's recovery finish a run whose write is not even in that
    commit yet."""
    stuck_run = db.insert(status="WRITTEN_PENDING_PUBLISH", source_kind="ECO")
    other_run = db.insert(status="WRITTEN_PENDING_PUBLISH", source_kind="ECO")
    import_worker.mark_committed([stuck_run], "deadbeef01")
    # other_run has no commit_sha at all -- it has not even pushed yet.

    assert stuck_ids(db) == [stuck_run]
    import_worker.finalize([stuck_run], "deadbeef01", "vehicle-2026-recovered")

    assert db.rows[stuck_run]["status"] == "COMPLETED"
    assert db.rows[other_run]["status"] == "WRITTEN_PENDING_PUBLISH"
    assert db.rows[other_run]["release_id"] is None


def stuck_ids(db: FakeImportRuns) -> list[str]:
    import io
    import sys

    captured = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured
    try:
        import_worker.stuck_runs()
    finally:
        sys.stdout = old_stdout
    printed = captured.getvalue().strip()
    return printed.split() if printed else []
