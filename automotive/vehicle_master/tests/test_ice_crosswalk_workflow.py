"""Static regression for .github/workflows/ice-crosswalk-run.yml (Market Track R6).

The legacy Vehicle Master guard (tests/test_workflow_static_guards.py) refuses any workflow
whose scripts mention the legacy writers, including the literal ``canonical_input_worker``.
The R6 workflow's read-only preflight once imported ``_request`` from that module inline and
tripped the guard. The preflight now lives behind ``tools.ice_crosswalk_match
--check-live-import``. These tests keep it that way WITHOUT touching the guard: they run the
guard's own ``_writes`` / ``_writers`` over this workflow and expect it clean.
"""

from __future__ import annotations

from tests.test_workflow_static_guards import _document, _script, _steps, _writers, _writes

WORKFLOW = "ice-crosswalk-run.yml"


def test_the_workflow_never_names_the_legacy_writer_module():
    assert "canonical_input_worker" not in (
        __import__("pathlib").Path(__file__).resolve().parents[3] / ".github" / "workflows" / WORKFLOW
    ).read_text(encoding="utf-8")


def test_the_legacy_guard_sees_this_workflow_as_a_non_writer_without_being_whitelisted():
    assert not _writes(_script(WORKFLOW))
    assert WORKFLOW not in _writers()


def test_the_preflight_goes_through_the_crosswalk_tool_and_is_read_only():
    script = _script(WORKFLOW)
    assert "tools.ice_crosswalk_match" in script and "--check-live-import" in script
    # the three writing phases are still the matcher's own modes, in the roadmap's order
    assert script.index("--check-live-import") < script.index("--process-id-changes") < script.index("--match")


def test_permissions_and_concurrency_are_unchanged():
    document = _document(WORKFLOW)
    assert document["permissions"] == {"contents": "read"}
    assert document["concurrency"] == {"group": "ice-crosswalk-production", "cancel-in-progress": False}


def test_it_is_dispatch_only_behind_production_confirmation_and_never_pushes():
    document = _document(WORKFLOW)
    triggers = document.get("on", document.get(True))
    assert list(triggers) == ["workflow_dispatch"]
    assert document["jobs"]["crosswalk"]["if"] == "${{ inputs.confirm_production }}"
    script = _script(WORKFLOW)
    assert "git push" not in script and "git commit" not in script
    checkouts = [s for s in _steps(WORKFLOW) if s.get("uses", "").startswith("actions/checkout")]
    assert checkouts and all((s.get("with") or {}).get("persist-credentials") is False for s in checkouts)
