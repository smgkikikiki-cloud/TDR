"""Fix 2 (FINAL 3-FIX PASS): a canonical_input_batches row stuck STAGED
behind a failed publish must be retried by the next scheduled tick, even
when that tick's own pull() finds nothing new to apply -- literally no new
QUEUED/stale-PROCESSING row, no new git diff of its own.

Same convention as tests/test_import_worker_publish_retry.py: an in-memory
fake of the exact PostgREST calls tools.canonical_input_worker makes, and
every assertion reads back state a real call produced. staged_batches() and
mark_published() are exercised together, exactly as
.github/workflows/canonical-input.yml's recovery steps call them; neither
this test nor that workflow ever calls CanonicalInputPipeline.apply() again
for a STAGED batch -- the write was already committed the first time, and
recovery only retries the publish step, so "the same command not applied
twice" and "canonical entity exists once" hold by construction, not by
observation.
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import pytest

from tools import canonical_input_worker


class FakeCanonicalBatches:
    """Enough of canonical_input_batches + PostgREST's filter query strings
    to exercise staged_batches()/mark_published() for real."""

    def __init__(self):
        self.rows: dict[str, dict] = {}
        self._next = 1

    def insert(self, **fields) -> str:
        row_id = f"batch-{self._next}"
        self._next += 1
        self.rows[row_id] = {
            "id": row_id, "release_id": None, "error": None, "updated_at": None,
            **fields,
        }
        return row_id

    def _matches(self, row: dict, filters: dict[str, list[str]]) -> bool:
        for key, values in filters.items():
            if key in ("select", "limit", "order"):
                continue
            value = values[0]
            if value.startswith("eq."):
                if str(row.get(key)) != value[len("eq."):]:
                    return False
            elif value.startswith("in."):
                allowed = value[len("in."):].strip("()").split(",")
                if str(row.get(key)) not in allowed:
                    return False
            else:  # pragma: no cover - every filter used here is one of the above
                raise AssertionError(f"unhandled filter {key}={value}")
        return True

    def rest(self, method: str, path: str, payload=None, *, prefer=None):
        parsed = urlparse(path)
        table = parsed.path.split("?")[0]
        filters = parse_qs(parsed.query)
        assert table == "canonical_input_batches"

        if method == "GET":
            matched = [row for row in self.rows.values() if self._matches(row, filters)]
            order = filters.get("order", [""])[0]
            if order.startswith("created_at"):
                matched.sort(key=lambda row: row["created_at"], reverse="desc" in order)
            select = filters.get("select", ["*"])[0].split(",")
            return [{k: row.get(k) for k in select} for row in matched]

        if method == "PATCH":
            matched = [row for row in self.rows.values() if self._matches(row, filters)]
            for row in matched:
                row.update(payload)
            return [dict(row) for row in matched] if matched else []

        raise AssertionError(f"unhandled method {method}")  # pragma: no cover


@pytest.fixture
def db(monkeypatch):
    fake = FakeCanonicalBatches()
    monkeypatch.setattr(canonical_input_worker, "_request", fake.rest)
    return fake


def _staged(db, *, key: str, sha: str, created_at: str) -> str:
    return db.insert(
        batch_key=key, status="STAGED", created_at=created_at,
        pull_request_url=f"https://github.com/org/repo/commit/{sha}",
    )


def test_a_staged_batch_is_found_with_no_new_git_diff(db, tmp_path):
    """The literal acceptance case: nothing QUEUED, nothing PROCESSING --
    pull() would report count=0 -- and the STAGED row is still found."""
    _staged(db, key="batch-1", sha="deadbeef01", created_at="2026-09-01T00:00:00Z")
    result_file = tmp_path / "staged.json"

    canonical_input_worker.staged_batches(result_file, limit=50)

    payload = json.loads(result_file.read_text())
    assert payload["revision"] == "deadbeef01"
    assert payload["applied"] == [{"id": "batch-1", "batch_key": "batch-1"}]


def test_b_recovery_publishes_and_marks_published_with_no_reapply(db, tmp_path):
    run_id = _staged(db, key="batch-1", sha="deadbeef01", created_at="2026-09-01T00:00:00Z")
    result_file = tmp_path / "staged.json"
    canonical_input_worker.staged_batches(result_file, limit=50)

    # The workflow's "Retry publishing" step is a separate process
    # (tools.publish_canonical) this test does not invoke -- exactly the
    # boundary test_import_worker_publish_retry.py draws around
    # mark_committed()/finalize() too. What this asserts is the worker's own
    # half: once that retry succeeds, mark_published() (unchanged, the same
    # function the normal path already uses) completes the row.
    canonical_input_worker.mark_published(result_file, "vehicle-2026-recovered")

    assert db.rows[run_id]["status"] == "PUBLISHED"
    assert db.rows[run_id]["release_id"] == "vehicle-2026-recovered"


def test_c_a_second_failed_retry_leaves_it_staged_not_published(db, tmp_path):
    run_id = _staged(db, key="batch-1", sha="deadbeef01", created_at="2026-09-01T00:00:00Z")
    result_file = tmp_path / "staged.json"
    canonical_input_worker.staged_batches(result_file, limit=50)

    # The retry publish itself failed -- mark_published() is simply never
    # called, exactly as the workflow's own "if publish succeeded" gate
    # would skip it. The row must not have moved.
    assert db.rows[run_id]["status"] == "STAGED"
    assert db.rows[run_id]["release_id"] is None

    # The NEXT tick still finds the exact same commit to retry.
    result_file_2 = tmp_path / "staged2.json"
    canonical_input_worker.staged_batches(result_file_2, limit=50)
    assert json.loads(result_file_2.read_text())["revision"] == "deadbeef01"


def test_d_only_the_oldest_stuck_commit_is_recovered_per_call(db, tmp_path):
    """Two different commits are both stuck STAGED (two separate failed
    publish attempts across two different runs). Recovery must not mix
    batches from different commits into one publish/mark-published call --
    that would mark a batch PUBLISHED under a release built from the
    WRONG commit's tree."""
    old = _staged(db, key="old-batch", sha="oldsha01", created_at="2026-09-01T00:00:00Z")
    newer = _staged(db, key="new-batch", sha="newsha02", created_at="2026-09-05T00:00:00Z")
    result_file = tmp_path / "staged.json"

    canonical_input_worker.staged_batches(result_file, limit=50)

    payload = json.loads(result_file.read_text())
    assert payload["revision"] == "oldsha01"
    assert payload["applied"] == [{"id": old, "batch_key": "old-batch"}]

    canonical_input_worker.mark_published(result_file, "vehicle-2026-old")
    assert db.rows[old]["status"] == "PUBLISHED"
    assert db.rows[newer]["status"] == "STAGED"  # the newer commit untouched


def test_e_multiple_batches_sharing_one_commit_are_recovered_together(db, tmp_path):
    """A single "Apply N canonical input batch(es)" commit can carry
    several queued batches at once -- mark_staged() stamps them all with
    the same commit URL, and recovery has to publish and complete them
    together, not just the first one found."""
    first = _staged(db, key="batch-a", sha="sharedsha", created_at="2026-09-01T00:00:00Z")
    second = _staged(db, key="batch-b", sha="sharedsha", created_at="2026-09-01T00:00:01Z")
    result_file = tmp_path / "staged.json"

    canonical_input_worker.staged_batches(result_file, limit=50)
    payload = json.loads(result_file.read_text())
    assert payload["revision"] == "sharedsha"
    assert {row["id"] for row in payload["applied"]} == {first, second}

    canonical_input_worker.mark_published(result_file, "vehicle-2026-shared")
    assert db.rows[first]["status"] == "PUBLISHED"
    assert db.rows[second]["status"] == "PUBLISHED"
    assert db.rows[first]["release_id"] == db.rows[second]["release_id"] == "vehicle-2026-shared"


def test_f_no_staged_rows_is_a_clean_no_op(db, tmp_path):
    result_file = tmp_path / "staged.json"
    canonical_input_worker.staged_batches(result_file, limit=50)
    payload = json.loads(result_file.read_text())
    assert payload == {"applied": [], "revision": None}
