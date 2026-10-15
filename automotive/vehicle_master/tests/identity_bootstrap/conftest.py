"""Explicit skip report for the Identity Bootstrap suite.

Some real-data tests need inputs that are deliberately NOT committed (the archived M7.0 Ice package) or git objects that an isolated CI checkout may lack (the PR #200
commit). They skip rather than fail. This hook prints, for every run, which tests skipped and why, and which portable invariants (`test_ib_committed_artifacts.py`)
still ran over the committed outputs, and appends the same text to $GITHUB_STEP_SUMMARY when present."""
from __future__ import annotations

import collections
import os

_skips: list[tuple[str, str]] = []
_portable_ran = collections.Counter()


def pytest_runtest_logreport(report):
    if report.skipped and report.when in ("setup", "call"):
        reason = report.longrepr[2] if isinstance(report.longrepr, tuple) else str(report.longrepr)
        _skips.append((report.nodeid, reason.replace("Skipped: ", "")))
    if report.when == "call" and report.passed and "test_ib_committed_artifacts.py" in report.nodeid:
        _portable_ran["passed"] += 1


def pytest_terminal_summary(terminalreporter):
    by_reason = collections.defaultdict(list)
    for node, reason in _skips:
        by_reason[reason].append(node)
    real_data = [n for r, ns in by_reason.items() if "package" in r or "commit" in r or "PR #200" in r for n in ns]
    lines = ["IDENTITY BOOTSTRAP SKIP REPORT", f"  skipped in tests/identity_bootstrap: {len(_skips)}"]
    for reason, nodes in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"    {len(nodes):3d} x {reason}")
    lines.append(f"  real-data skips (archived M7.0 package / PR #200 git object not present): {len(real_data)}")
    lines.append(f"  portable committed-artifact invariants that ran regardless: {_portable_ran['passed']} (tests/identity_bootstrap/test_ib_committed_artifacts.py)")
    terminalreporter.write_sep("-", "identity bootstrap skip report")
    for line in lines:
        terminalreporter.write_line(line)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("### " + lines[0] + "\n\n" + "\n".join("- " + l.strip() for l in lines[1:]) + "\n")
