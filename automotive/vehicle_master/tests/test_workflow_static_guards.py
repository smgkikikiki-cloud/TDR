"""STATIC GUARDS. These are lint, not acceptance evidence.

Nothing here proves a workflow works; a workflow is proved by running.
What these catch is a specific regression that has already happened
twice: a production job wired to a command that cannot do the job, and a
writer that pushes to main and trusts some other workflow to publish it.
Both are invisible to every test that only imports Python. Since Vehicle DB
v3 Phase 0 step 5 they also hold the cutover: no workflow may write the
legacy file-backed Vehicle Master or publish a release again.

The behaviour these guard is covered by executable tests elsewhere --
``test_pricefeed_writer.py`` for the price path, and the publish step by
``tools/publish_canonical.py``'s read-back of what Supabase serves.
"""

from __future__ import annotations

from pathlib import Path
import re

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[3] / ".github" / "workflows"

#: Vehicle DB v3 Phase 0 step 5 (migration_v60): the legacy file-backed
#: Vehicle Master writers. Each is kept only as a stub that fails loudly, so a
#: stale caller sees why; none may schedule, push, write or publish.
CLOSED_LEGACY_WRITERS = (
    "canonical-input.yml", "enqueue-canonical-batch.yml", "pricefeed.yml", "vehicle-release.yml",
    "retail-lineup-bootstrap-apply.yml", "mark-canonical-batch-status.yml",
)
_WRITE_MARKERS = ("git push", "tools.publish_canonical", "canonical_input_worker",
                  "tools.pricefeed_write", "retail_lineup_apply_worker", "git commit")
#: tdr_bridge.publish only writes with --publish; without it (CI) it validates.
_PUBLISH_FLAG = re.compile(r"tdr_bridge\.publish\b[^\n]*--publish")


def _writes(script: str) -> bool:
    return any(marker in script for marker in _WRITE_MARKERS) or bool(_PUBLISH_FLAG.search(script))


def _document(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _triggers(name: str) -> dict:
    # PyYAML reads the bare key `on` as the boolean True.
    document = _document(name)
    return document.get("on", document.get(True)) or {}


def _steps(name: str) -> list[dict]:
    document = _document(name)
    return [step for job in document["jobs"].values() for step in job["steps"]]


def _script(name: str) -> str:
    return "\n".join(str(step.get("run") or "") for step in _steps(name))


def _writers() -> list[str]:
    """Every workflow that can still write canonical data or publish a release."""
    found = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        document = _document(path.name)
        script = _script(path.name)
        if (document.get("permissions") or {}).get("contents") == "write" or _writes(script):
            found.append(path.name)
    return found


def test_no_workflow_writes_the_legacy_vehicle_master():
    """Phase 0 step 5: git/releases are no longer a write path (VEHICLE_DB_V3 §1.1, §2.5)."""
    assert _writers() == []


@pytest.mark.parametrize("workflow", CLOSED_LEGACY_WRITERS)
def test_closed_legacy_writers_fail_loudly_and_cannot_write(workflow: str):
    document = _document(workflow)
    triggers = _triggers(workflow)
    assert "schedule" not in triggers and "push" not in triggers, workflow
    assert document.get("permissions") == {"contents": "read"}, workflow
    steps = _steps(workflow)
    assert len(steps) == 1 and not any(step.get("uses") for step in steps), workflow
    script = _script(workflow)
    assert "Phase 0 step 5" in script and script.strip().endswith("exit 1"), workflow
    assert not any(word in script for word in ("python", "git ", "curl")), workflow


def test_source_import_only_imports_registrations():
    """DLT registration ingest is out of scope for the cutover and keeps
    running; every legacy canonical kind is refused by the worker."""
    document = _document("source-import.yml")
    assert document.get("permissions") == {"contents": "read"}
    script = _script("source-import.yml")
    assert "tools/import_worker.py run" in script and "--registration-only" in script
    assert not _writes(script)
    assert "retail_lineup_compile_worker" not in script
    checkouts = [step for step in _steps("source-import.yml") if step.get("uses", "").startswith("actions/checkout")]
    assert checkouts and all((step.get("with") or {}).get("persist-credentials") is False for step in checkouts)


@pytest.mark.parametrize("workflow", _writers() or ["<none>"])
def test_a_workflow_that_pushes_also_publishes_what_it_pushed(workflow: str):
    if workflow == "<none>":
        pytest.skip("no workflow writes canonical data (Phase 0 step 5)")
    script = _script(workflow)
    if "git push" not in script:
        pytest.skip(f"{workflow} does not push")
    assert "tools.publish_canonical" in script, (
        f"{workflow} pushes to main without publishing; the data would sit unserved")
    assert "--revision" in script, (
        f"{workflow} must publish the exact commit it pushed, not whatever is on main")


@pytest.mark.parametrize("workflow", _writers() or ["<none>"])
def test_any_remaining_writer_keeps_the_legacy_publisher_guards(workflow: str):
    """If a writer ever reappears it must keep every guard the legacy writers
    had: one shared concurrency group, the full-history ordinal guard that
    fails loudly when shallow, and a checkout pinned to main."""
    if workflow == "<none>":
        pytest.skip("no workflow writes canonical data (Phase 0 step 5)")
    document = _document(workflow)
    assert (document.get("concurrency") or {}).get("group") == "canonical-vehicle-input", workflow
    checkouts = [step for step in _steps(workflow) if step.get("uses", "").startswith("actions/checkout")]
    assert checkouts and any((step.get("with") or {}).get("ref") == "main" for step in checkouts), workflow
    full_depth_checkout = any((step.get("with") or {}).get("fetch-depth") == 0 for step in checkouts)
    script = _script(workflow)
    deepen = ("git fetch" in script and "--depth=2147483647" in script
              and 'origin "$(git rev-parse HEAD)"' in script)
    assert full_depth_checkout or deepen, workflow
    if not full_depth_checkout:
        assert "is-shallow-repository" in script and '!= "false"' in script, workflow


def test_the_price_feed_never_loads_a_human_decisions_file():
    """No human publish/approval gate in the normal automated price path
    -- see test_pricefeed_writer.py for the behavioural proof that a
    decisions.json on disk cannot promote a price even if one exists."""
    script = _script("pricefeed.yml")
    assert "--decisions" not in script
    assert "review/decisions.json" not in script
