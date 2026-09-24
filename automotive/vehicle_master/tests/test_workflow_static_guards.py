"""STATIC GUARDS. These are lint, not acceptance evidence.

Nothing here proves a workflow works; a workflow is proved by running.
What these catch is a specific regression that has already happened
twice: a production job wired to a command that cannot do the job, and a
writer that pushes to main and trusts some other workflow to publish it.
Both are invisible to every test that only imports Python.

The behaviour these guard is covered by executable tests elsewhere --
``test_pricefeed_writer.py`` for the price path, and the publish step by
``tools/publish_canonical.py``'s read-back of what Supabase serves.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[3] / ".github" / "workflows"
#: Every workflow that pushes canonical data to main.
WRITERS = ("canonical-input.yml", "source-import.yml", "pricefeed.yml")


def _steps(name: str) -> list[dict]:
    document = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    return [step for job in document["jobs"].values() for step in job["steps"]]


def _script(name: str) -> str:
    return "\n".join(str(step.get("run") or "") for step in _steps(name))


def test_the_price_feed_does_not_call_the_evidence_only_command_as_a_writer():
    script = _script("pricefeed.yml")
    assert "--write" not in script, (
        "market price-run rejects --write; the workflow failed on every tick")
    assert "tools.pricefeed_write" in script


@pytest.mark.parametrize("workflow", WRITERS)
def test_a_workflow_that_pushes_also_publishes_what_it_pushed(workflow: str):
    script = _script(workflow)
    if "git push" not in script:
        pytest.skip(f"{workflow} does not push")
    assert "tools.publish_canonical" in script, (
        f"{workflow} pushes to main without publishing; the data would sit unserved")
    assert "--revision" in script, (
        f"{workflow} must publish the exact commit it pushed, not whatever is on main")


def test_all_four_canonical_publishers_share_one_concurrency_group():
    """The primary defense against the race migration_v44 also guards:
    no two of these can run at the same time at all. See
    test_release_activation_staleness_guard_migration_v44.py for the
    behavioural half (an out-of-order queue within that serialization)."""
    for workflow in ("source-import.yml", "canonical-input.yml",
                     "pricefeed.yml", "vehicle-release.yml"):
        document = yaml.safe_load((WORKFLOWS / workflow).read_text(encoding="utf-8"))
        assert document["concurrency"]["group"] == "canonical-vehicle-input", workflow


def test_every_publisher_that_needs_the_ordinal_guard_fetches_full_history():
    """git rev-list --count undercounts on a shallow clone, silently
    disabling migration_v44's guard for that workflow.

    Full history can come either from actions/checkout's own
    fetch-depth: 0, or from a follow-up deepen fetch scoped to just the
    commit actually checked out. The latter replaced the former in every
    one of these workflows: fetch-depth: 0 fetches every branch and tag
    in the repository on every run, which started failing outright
    ("pack has 2 unresolved deltas") once there were enough of them --
    see each workflow's checkout comment. Either way, the requirement
    this test guards is the same: a shallow clone must never reach
    tools.publish_canonical's ordinal computation."""
    for workflow in ("source-import.yml", "canonical-input.yml",
                     "pricefeed.yml", "vehicle-release.yml"):
        checkouts = [step for step in _steps(workflow) if step.get("uses", "").startswith("actions/checkout")]
        assert checkouts, workflow
        full_depth_checkout = any((step.get("with") or {}).get("fetch-depth") == 0 for step in checkouts)
        script = _script(workflow)
        deepen_fetch_scoped_to_this_commit = (
            "git fetch" in script and "--depth=2147483647" in script
            and 'origin "$(git rev-parse HEAD)"' in script
        )
        assert full_depth_checkout or deepen_fetch_scoped_to_this_commit, workflow


def test_canonical_input_marks_its_own_batches_published_after_a_real_publish():
    script = _script("canonical-input.yml")
    assert "mark-published" in script
    assert script.index("tools.publish_canonical") < script.index("mark-published")


def test_source_import_recovers_a_stuck_publish_before_doing_anything_else():
    script = _script("source-import.yml")
    assert "stuck-runs" in script and "mark-committed" in script
    # Recovery has to run before the normal import/commit/publish sequence,
    # so it can fix a prior failure even when this tick has no new work.
    names = [str(step.get("name") or "") for step in _steps("source-import.yml")]
    recover_index = next(i for i, n in enumerate(names) if "stuck" in n.lower())
    import_index = next(i for i, n in enumerate(names) if n == "Import every uploaded file")
    assert recover_index < import_index


def test_the_price_feed_never_loads_a_human_decisions_file():
    """No human publish/approval gate in the normal automated price path
    -- see test_pricefeed_writer.py for the behavioural proof that a
    decisions.json on disk cannot promote a price even if one exists."""
    script = _script("pricefeed.yml")
    assert "--decisions" not in script
    assert "review/decisions.json" not in script
