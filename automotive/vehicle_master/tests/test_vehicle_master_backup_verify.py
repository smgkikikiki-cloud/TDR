"""Phase 0 step 6: the backup restore/verification dry-run checker."""

from __future__ import annotations

from datetime import datetime, timezone
import gzip
import json

from tools import vehicle_master_backup as backup
from tools import vehicle_master_backup_verify as verify

FIXED_NOW = datetime(2026, 10, 4, 18, 30, 7, tzinfo=timezone.utc)


def _fake_rest(tables=None):
    from tests.test_vehicle_master_backup import FakeRest, _sample_tables
    return FakeRest(tables if tables is not None else _sample_tables())


def _build(tmp_path, *, tables=None):
    out = tmp_path / "backup.json.gz"
    summary = backup.run(apply=False, out=out, rest=_fake_rest(tables), now=lambda: FIXED_NOW)
    return out, summary


def test_a_freshly_built_backup_verifies_clean(tmp_path):
    out, _ = _build(tmp_path)
    export = verify.load_backup(out.read_bytes())
    assert verify.verify(export) == []


def test_file_sha256_check_passes_for_the_real_file_and_fails_for_a_wrong_one(tmp_path):
    out, summary = _build(tmp_path)
    raw = out.read_bytes()
    assert backup.sha256_hex(raw) == summary["gzip_sha256"]
    assert backup.sha256_hex(raw) != "0" * 64


def test_tampered_checksum_is_caught(tmp_path):
    out, _ = _build(tmp_path)
    export = verify.load_backup(out.read_bytes())
    export["checksum"]["value"] = "0" * 64
    problems = verify.verify(export)
    assert any("checksum mismatch" in p for p in problems)


def test_tampered_row_count_is_caught(tmp_path):
    out, _ = _build(tmp_path)
    export = verify.load_backup(out.read_bytes())
    export["payload"]["row_counts"]["vehicle_brands"] = 999
    problems = verify.verify(export)
    assert any("row_counts['vehicle_brands']" in p or "row_counts[\"vehicle_brands\"]" in p
               or "vehicle_brands" in p for p in problems)


def test_wrong_format_tag_is_caught(tmp_path):
    out, _ = _build(tmp_path)
    export = verify.load_backup(out.read_bytes())
    export["format"] = "something-else"
    problems = verify.verify(export)
    assert any("format" in p for p in problems)


def test_wrong_format_version_is_caught(tmp_path):
    out, _ = _build(tmp_path)
    export = verify.load_backup(out.read_bytes())
    export["format_version"] = 999
    problems = verify.verify(export)
    assert any("format_version" in p for p in problems)


def test_missing_table_in_tables_list_is_caught(tmp_path):
    out, _ = _build(tmp_path)
    export = verify.load_backup(out.read_bytes())
    export["payload"]["tables"] = [t for t in export["payload"]["tables"] if t != "vehicle_brands"]
    problems = verify.verify(export)
    assert any("table list mismatch" in p for p in problems)


def test_load_backup_decompresses_gzip(tmp_path):
    out, _ = _build(tmp_path)
    export = verify.load_backup(out.read_bytes())
    assert export["format"] == backup.FORMAT_NAME


def test_load_backup_accepts_a_plain_uncompressed_json_for_local_testing():
    export = {"format": backup.FORMAT_NAME}
    raw = json.dumps(export).encode("utf-8")
    assert verify.load_backup(raw) == export


def test_verify_never_writes_any_file(tmp_path, monkeypatch):
    out, _ = _build(tmp_path)
    before = sorted(tmp_path.iterdir())

    import builtins
    original_open = builtins.open

    def guarded_open(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in ("w", "a", "x")):
            raise AssertionError(f"verify must never open a file for writing: {file!r} ({mode!r})")
        return original_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    export = verify.load_backup(out.read_bytes())
    verify.verify(export)
    assert sorted(tmp_path.iterdir()) == before


def test_cli_exits_nonzero_on_an_invalid_backup(tmp_path, capsys):
    bad = tmp_path / "bad.json.gz"
    bad.write_bytes(gzip.compress(json.dumps({"format": "nope"}).encode("utf-8")))
    code = verify.main([str(bad)])
    assert code == 1
    assert "INVALID" in capsys.readouterr().out


def test_cli_exits_zero_and_prints_a_summary_for_a_valid_backup(tmp_path, capsys):
    out, _ = _build(tmp_path)
    code = verify.main([str(out)])
    assert code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["valid"] is True
    assert "data" not in printed
