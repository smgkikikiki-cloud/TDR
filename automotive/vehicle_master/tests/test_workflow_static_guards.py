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
