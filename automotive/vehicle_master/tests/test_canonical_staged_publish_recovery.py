"""Fix 2 (FINAL 3-FIX PASS) and its own follow-up fix (FINAL STATUS-RECOVERY
FIX): a canonical_input_batches row stuck STAGED behind a failed publish
must be retried by the next scheduled tick, even when that tick's own
pull() finds nothing new to apply -- literally no new QUEUED/stale-PROCESSING
row, no new git diff of its own -- AND, when a LATER batch's own publish
already carried the stuck commit's changes into the release that is
serving right now, must be marked PUBLISHED directly with NO republish at
all, proven by real `git merge-base --is-ancestor`, never by ordinal or
revision-count comparison.

Same convention as tests/test_import_worker_publish_retry.py: an in-memory
fake of the exact PostgREST calls tools.canonical_input_worker makes, and
every assertion reads back state a real call produced. staged_batches() and
mark_published() are exercised together, exactly as
.github/workflows/canonical-input.yml's recovery steps call them; neither
this test nor that workflow ever calls CanonicalInputPipeline.apply() again
for a STAGED batch -- the write was already committed the first time, and
recovery only ever retries the publish step or skips it, so "the same
command not applied twice" and "canonical entity exists once" hold by
construction, not by observation.

The ancestry tests below run real `git` against real throwaway repositories
built in tmp_path -- not a fake of git's answer. tools.canonical_input_worker's
_git_is_ancestor is exercised directly by them, and
_resolve_staged_recovery (the pure decision function staged_batches() calls)
is driven with those real commit shas plus the real ancestry function, so
"proves git ancestry" is a fact about what ran, not a claim about what the
code merely calls.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from tools import canonical_input_worker


class FakeCanonicalBatches:
    """Enough of canonical_input_batches, canonical_vehicle_state and
    canonical_vehicle_releases + PostgREST's filter query strings to
    exercise staged_batches()/mark_published() for real, active-release
    lookup included."""

    def __init__(self):
        self.rows: dict[str, dict] = {}
        self._next = 1
        self.active_release_id: str | None = None
        self.releases: dict[str, dict] = {}

    def insert(self, **fields) -> str:
        row_id = f"batch-{self._next}"
        self._next += 1
        self.rows[row_id] = {
            "id": row_id, "release_id": None, "error": None, "updated_at": None,
            **fields,
        }
        return row_id

    def set_active_release(self, release_id: str, canonical_revision: str) -> None:
        self.active_release_id = release_id
        self.releases[release_id] = {"release_id": release_id, "canonical_revision": canonical_revision}

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

        if table == "canonical_vehicle_state":
            assert method == "GET"
            if not self.active_release_id:
                return []
            return [{"active_release_id": self.active_release_id}]

        if table == "canonical_vehicle_releases":
            assert method == "GET"
            release_filter = filters.get("release_id", [""])[0]
            wanted = release_filter[len("eq."):] if release_filter.startswith("eq.") else None
            release = self.releases.get(wanted) if wanted else None
            return [release] if release else []

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


def _init_repo(path: Path) -> Path:
    repo = path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    return repo


def _commit(repo: Path, message: str) -> str:
    (repo / "file.txt").write_text(message, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=repo, check=True)
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                            check=True, capture_output=True, text=True)
    return result.stdout.strip()


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
    assert payload == {"applied": [], "revision": None, "already_published_release_id": None}


# =====================================================================
# FINAL STATUS-RECOVERY FIX: ancestry-aware recovery. All five required
# acceptance tests (A-E) drive _resolve_staged_recovery -- the pure
# decision function -- directly, with real commit shas from real git
# repositories and (except where a test is deliberately checking the
# failure path) the real _git_is_ancestor function.
# =====================================================================

def _row(row_id: str, sha: str, created_at: str) -> dict:
    return {"id": row_id, "batch_key": row_id, "created_at": created_at,
           "pull_request_url": f"https://github.com/org/repo/commit/{sha}"}


def test_real_git_ancestry_true_for_a_direct_descendant(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    sha_a = _commit(repo, "A")
    sha_b = _commit(repo, "B")
    monkeypatch.chdir(repo)
    assert canonical_input_worker._git_is_ancestor(sha_a, sha_b) is True


def test_real_git_ancestry_false_for_diverged_history(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    root = _commit(repo, "root")
    subprocess.run(["git", "checkout", "-b", "branch-a"], cwd=repo, check=True)
    sha_a = _commit(repo, "A")
    subprocess.run(["git", "checkout", root], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-b", "branch-b"], cwd=repo, check=True)
    sha_b = _commit(repo, "B")
    monkeypatch.chdir(repo)
    assert canonical_input_worker._git_is_ancestor(sha_a, sha_b) is False


def test_real_git_ancestry_none_for_an_unknown_revision(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    sha_a = _commit(repo, "A")
    monkeypatch.chdir(repo)
    assert canonical_input_worker._git_is_ancestor("deadbeefdeadbeefdeadbeefdeadbeefdeadbeef", sha_a) is None


def test_A_staged_commit_equals_active_revision_marks_published_no_republish(tmp_path, monkeypatch):
    """TEST A -- exact active revision."""
    repo = _init_repo(tmp_path)
    sha_a = _commit(repo, "A")
    monkeypatch.chdir(repo)

    rows = [_row("batch-a", sha_a, "2026-09-01T00:00:00Z")]
    active_release = {"release_id": "release-A", "canonical_revision": sha_a}

    decision = canonical_input_worker._resolve_staged_recovery(
        rows, active_release, canonical_input_worker._git_is_ancestor)

    assert decision == {
        "mode": "already_published", "release_id": "release-A",
        "applied": [{"id": "batch-a", "batch_key": "batch-a"}],
    }


def test_B_staged_commit_is_ancestor_of_active_revision_marks_published_no_republish(tmp_path, monkeypatch):
    """TEST B -- descendant active revision. This is the exact bug: commit A
    was pushed and staged, commit B (a later batch) descends from A and its
    own publish succeeded, so A's canonical changes are already serving --
    republishing A would be exactly what migration_v44 correctly refuses."""
    repo = _init_repo(tmp_path)
    sha_a = _commit(repo, "A")
    sha_b = _commit(repo, "B")
    monkeypatch.chdir(repo)

    # A second, unrelated STAGED row (a hypothetical batch under commit B
    # itself) must stay untouched: only the oldest group (A) is resolved.
    rows = [
        _row("batch-a", sha_a, "2026-09-01T00:00:00Z"),
        _row("batch-b", sha_b, "2026-09-05T00:00:00Z"),
    ]
    active_release = {"release_id": "release-B", "canonical_revision": sha_b}

    decision = canonical_input_worker._resolve_staged_recovery(
        rows, active_release, canonical_input_worker._git_is_ancestor)

    assert decision["mode"] == "already_published"
    assert decision["release_id"] == "release-B"
    assert decision["applied"] == [{"id": "batch-a", "batch_key": "batch-a"}]
    # batch-b is simply not part of this call's output at all.
    assert all(row["id"] != "batch-b" for row in decision["applied"])


def test_C_diverged_history_keeps_the_existing_republish_path(tmp_path, monkeypatch):
    """TEST C -- active release does NOT contain the staged commit (history
    diverges). Must NOT mark A published; the normal republish-exact-SHA
    path remains required."""
    repo = _init_repo(tmp_path)
    root = _commit(repo, "root")
    subprocess.run(["git", "checkout", "-b", "branch-a"], cwd=repo, check=True)
    sha_a = _commit(repo, "A")
    subprocess.run(["git", "checkout", root], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-b", "branch-b"], cwd=repo, check=True)
    sha_b = _commit(repo, "B")
    monkeypatch.chdir(repo)

    rows = [_row("batch-a", sha_a, "2026-09-01T00:00:00Z")]
    active_release = {"release_id": "release-B", "canonical_revision": sha_b}

    decision = canonical_input_worker._resolve_staged_recovery(
        rows, active_release, canonical_input_worker._git_is_ancestor)

    assert decision == {
        "mode": "republish", "revision": sha_a,
        "applied": [{"id": "batch-a", "batch_key": "batch-a"}],
    }


def test_D_multiple_batches_sharing_the_staged_commit_all_recovered_together(tmp_path, monkeypatch):
    """TEST D -- A1 + A2 share commit A, active revision B descends from A:
    both get release B, and an unrelated STAGED commit C is untouched."""
    repo = _init_repo(tmp_path)
    sha_a = _commit(repo, "A")
    sha_b = _commit(repo, "B")
    sha_c = _commit(repo, "C")
    monkeypatch.chdir(repo)

    rows = [
        _row("a1", sha_a, "2026-09-01T00:00:00Z"),
        _row("a2", sha_a, "2026-09-01T00:00:01Z"),
        _row("c1", sha_c, "2026-09-05T00:00:00Z"),  # a different, newer stuck commit
    ]
    active_release = {"release_id": "release-B", "canonical_revision": sha_b}

    decision = canonical_input_worker._resolve_staged_recovery(
        rows, active_release, canonical_input_worker._git_is_ancestor)

    assert decision["mode"] == "already_published"
    assert decision["release_id"] == "release-B"
    assert {row["id"] for row in decision["applied"]} == {"a1", "a2"}


def test_E_missing_active_release_falls_back_to_republish_never_guesses_published(tmp_path, monkeypatch):
    """TEST E (part 1) -- no active release on record at all."""
    repo = _init_repo(tmp_path)
    sha_a = _commit(repo, "A")
    monkeypatch.chdir(repo)

    rows = [_row("batch-a", sha_a, "2026-09-01T00:00:00Z")]

    decision = canonical_input_worker._resolve_staged_recovery(
        rows, None, canonical_input_worker._git_is_ancestor)

    assert decision == {
        "mode": "republish", "revision": sha_a,
        "applied": [{"id": "batch-a", "batch_key": "batch-a"}],
    }


def test_E_ancestry_check_failure_falls_back_to_republish_never_guesses_published():
    """TEST E (part 2) -- the ancestry check itself could not be answered
    (unknown revision, git error) -- must not be treated as a yes."""
    rows = [_row("batch-a", "deadbeef01", "2026-09-01T00:00:00Z")]
    active_release = {"release_id": "release-X", "canonical_revision": "somethingelse"}

    decision = canonical_input_worker._resolve_staged_recovery(
        rows, active_release, lambda ancestor, descendant: None)

    assert decision == {
        "mode": "republish", "revision": "deadbeef01",
        "applied": [{"id": "batch-a", "batch_key": "batch-a"}],
    }


def test_full_orchestration_staged_batches_writes_already_published_and_mark_published_completes_it(
        db, tmp_path, monkeypatch):
    """End-to-end through staged_batches() itself (not just the pure
    decision function): the active-release DB read, the real git ancestry
    call, the result file it writes, and mark_published() completing the
    row -- all wired together the way canonical-input.yml's recovery steps
    actually call them, with no republish call anywhere in between."""
    repo = _init_repo(tmp_path)
    sha_a = _commit(repo, "A")
    sha_b = _commit(repo, "B")
    monkeypatch.chdir(repo)

    run_id = _staged(db, key="batch-a", sha=sha_a, created_at="2026-09-01T00:00:00Z")
    db.set_active_release("release-B", sha_b)

    result_file = tmp_path / "staged.json"
    canonical_input_worker.staged_batches(result_file, limit=50)

    payload = json.loads(result_file.read_text())
    assert payload["revision"] is None  # no republish needed
    assert payload["already_published_release_id"] == "release-B"
    assert payload["applied"] == [{"id": run_id, "batch_key": "batch-a"}]

    # canonical-input.yml calls mark-published with whichever release_id
    # came back -- here, the active one staged-batches already proved
    # contains this commit.
    canonical_input_worker.mark_published(result_file, "release-B")
    assert db.rows[run_id]["status"] == "PUBLISHED"
    assert db.rows[run_id]["release_id"] == "release-B"
    # The audit link to the original staged commit is untouched.
    assert sha_a in db.rows[run_id]["pull_request_url"]
