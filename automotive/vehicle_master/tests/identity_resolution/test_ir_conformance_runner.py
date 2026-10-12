"""Contract v1 runnable boundary: golden decisions, provenance, safe mode.

Not a claim of independently calibrated accuracy or production readiness.
"""
from __future__ import annotations

import json

import pytest

from identity_resolution.contract import loader
from identity_resolution.engine.cli import main
from identity_resolution.engine.runner import run_snapshot

CASES = [c for c in loader.load_cases() if c["kind"] == "resolve"
         and "refusal" not in c["expect"]]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_offline_runner_preserves_golden_resolve_decisions(case):
    report = run_snapshot(case["input"])
    assert report["mode"] == "OFFLINE_READ_ONLY"
    assert report["evaluation_backend"] == "contract_calibration_reference"
    assert report["policy_binding"] is False
    assert report["writes_executed"] == report["canonical_mutations"] == 0
    assert report["status"] == "EVALUATED"
    assert report["summary"]["subjects"] == len(case["input"]["subjects"])
    by_subject = {r["subject_id"]: r for r in report["decisions"]}
    assert len(by_subject) == len(case["input"]["subjects"])
    for sid, expectation in case["expect"]["decisions"].items():
        decision = by_subject[sid]
        assert decision["outcome"] == expectation["outcome"], case["id"]
        if "target_ids" in expectation:
            assert sorted(decision["target_ids"]) == sorted(expectation["target_ids"])
        if "primary_code" in expectation:
            assert decision["primary"] == expectation["primary_code"]
        assert decision["policy_binding"] is False
        assert "writes" not in decision
        assert isinstance(decision["advisory_write_plan"], list)


def test_cli_writes_deterministic_real_engine_report(tmp_path, capsys):
    case = next(c for c in CASES if c["id"] == "resolve.clean-auto-city")
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps(case["input"], ensure_ascii=False), encoding="utf-8")
    report_file = tmp_path / "offline-report.json"

    args = ["--snapshot", str(snapshot), "--out", str(report_file)]
    assert main(args) == 0
    first = report_file.read_bytes()
    report = json.loads(first)
    assert report["summary"]["decisions"] == 1
    assert report["decisions"][0]["outcome"] == "AUTO"
    assert report["writes_executed"] == 0
    assert main(args) == 0
    assert report_file.read_bytes() == first


def test_cli_rejects_invalid_snapshot_no_output(tmp_path, capsys):
    payload = tmp_path / "bad.json"
    payload.write_text('{"subjects":[]}', encoding="utf-8")
    out = tmp_path / "never-written.json"
    assert main(["--snapshot", str(payload), "--out", str(out)]) == 2
    assert not out.exists()
    assert "IR_OFFLINE_SMOKE_ERROR" in capsys.readouterr().err


def test_runner_refuses_adoption_binding(monkeypatch):
    case = CASES[0]
    original = loader.load_adoption
    monkeypatch.setattr(loader, "load_adoption", lambda: {**original(), "binding": True})
    with pytest.raises(RuntimeError, match="OFFLINE_ONLY"):
        run_snapshot(case["input"])


def test_known_bad_pair_never_promotes_wrong_model():
    case = next(c for c in CASES if c["id"] == "resolve.dmax-not-mux")
    output = run_snapshot(case["input"])
    assert output["summary"]["decisions"] == 1
    decision = output["decisions"][0]
    assert decision["subject_id"] == "isuzu-isuzu-d-max"
    assert decision["outcome"] == "NO_CANDIDATE"
    assert decision["target_ids"] == []
    assert decision["primary"] == "NO_CANDIDATE_ALL_EXCLUDED"
