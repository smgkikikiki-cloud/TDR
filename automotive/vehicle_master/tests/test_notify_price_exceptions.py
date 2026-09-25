from __future__ import annotations

import json
from pathlib import Path

from tools.notify_price_exceptions import build_notice, main


def _write(path: Path, exceptions: list[dict], *, batch_ref: str = "pricefeed-2026-09-24-abc") -> Path:
    path.write_text(json.dumps({
        "batch_ref": batch_ref,
        "generated_at": "2026-09-24T00:00:00+00:00",
        "exceptions": exceptions,
    }), encoding="utf-8")
    return path


def test_no_notice_when_no_exceptions(tmp_path: Path):
    path = _write(tmp_path / "e.json", [])
    assert build_notice(path) is None


def test_no_notice_when_only_price_conflicts(tmp_path: Path):
    path = _write(tmp_path / "e.json", [{
        "kind": "PRICE_CONFLICT", "reason": "two sources disagree",
        "source_identity": {"trim_id": "t.m.g.trim.x"},
    }])
    assert build_notice(path) is None


def test_notice_lists_unmatched_grade_with_candidates_and_urls(tmp_path: Path):
    path = _write(tmp_path / "e.json", [{
        "kind": "PRICE_IDENTITY", "reason": "no_trim_match",
        "source_identity": {
            "trim_id": None, "trim_candidates": ["t.m.g.trim.premium", "t.m.g.trim.premium_plus"],
            "urls": ["https://example.test/news/new-grade"],
        },
    }])
    notice = build_notice(path)
    assert notice is not None
    assert "1 grade" in notice
    assert "no_trim_match" in notice
    assert "t.m.g.trim.premium" in notice
    assert "https://example.test/news/new-grade" in notice


def test_notice_ignores_price_conflict_rows_but_counts_identity_rows(tmp_path: Path):
    path = _write(tmp_path / "e.json", [
        {"kind": "PRICE_CONFLICT", "reason": "disagree", "source_identity": {}},
        {"kind": "PRICE_IDENTITY", "reason": "no_trim_match", "source_identity": {}},
        {"kind": "PRICE_IDENTITY", "reason": "ambiguous_grade", "source_identity": {}},
    ])
    notice = build_notice(path)
    assert notice is not None
    assert "2 grade" in notice
    assert "disagree" not in notice


def test_main_returns_nonzero_when_nothing_to_notify(tmp_path: Path, capsys):
    path = _write(tmp_path / "e.json", [])
    assert main([str(path)]) == 1
    assert capsys.readouterr().out == ""


def test_main_prints_notice_and_returns_zero(tmp_path: Path, capsys):
    path = _write(tmp_path / "e.json", [{
        "kind": "PRICE_IDENTITY", "reason": "no_trim_match", "source_identity": {},
    }])
    assert main([str(path)]) == 0
    assert "1 grade" in capsys.readouterr().out
