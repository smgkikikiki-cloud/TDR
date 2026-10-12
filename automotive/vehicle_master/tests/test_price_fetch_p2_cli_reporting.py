"""Real-source smoke CLI must not report zero fetched documents as success.

All tests are network-free. They exercise the actual CLI, not the OEM website.
"""
from __future__ import annotations

import json

import pytest

from tools import pricefetch_targets as cli
from vehreg.price_fetch import FetchError, HttpResponse, OmodaJaecooThailandAdapter


TARGET = "jaecoo_th_home_price_cards"


def _read(out):
    return json.loads(out.read_text(encoding="utf-8"))


def test_robots_unknown_is_nonzero_and_writes_empty_result(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_robots_allowed", lambda *_: False)
    out = tmp_path / "result.json"
    code = cli.main(["--target", TARGET, "--out", str(out)])
    result = _read(out)
    summary = json.loads(capsys.readouterr().out)

    assert code == 2
    assert summary["status"] == "ROBOTS_BLOCKED"
    assert summary["fetched"] == 0
    assert summary["skipped_robots"] == 1
    assert result["results"] == []


def test_fetch_timeout_is_reported_without_traceback_or_fake_claim(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_robots_allowed", lambda *_: True)

    class SlowAdapter:
        def fetch(self, target, *, previous=None, timeout=45.0, refetch_not_modified=False):
            assert timeout == 120.0
            raise FetchError("read operation timed out")

    monkeypatch.setattr(cli, "adapter_for", lambda *args: SlowAdapter())
    out = tmp_path / "failure.json"
    code = cli.main([
        "--target", TARGET, "--fetch-timeout", "120", "--out", str(out),
    ])
    data = _read(out)
    streams = capsys.readouterr()
    summary = json.loads(streams.out)

    assert code == 2
    assert summary["status"] == "FETCH_ERROR"
    assert summary["fetched"] == 0
    assert summary["fetch_errors"][0]["target_id"] == TARGET
    assert data["fetch_errors"][0]["error"] == "read operation timed out"
    assert data["results"] == []
    assert "FETCH_ERROR" in streams.err


def test_fetch_timeout_option_passed_into_real_adapter(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_robots_allowed", lambda *_: True)
    timeouts = []

    class OneResponseTransport:
        def fetch(self, url, *, headers, timeout):
            timeouts.append(timeout)
            return HttpResponse(
                status=200,
                url=url,
                headers={"content-type": "text/html; charset=utf-8"},
                body=b"<html><head><title>Price test</title></head><body>OEM</body></html>",
            )

    monkeypatch.setattr(
        cli, "adapter_for",
        lambda *args: OmodaJaecooThailandAdapter(transport=OneResponseTransport()),
    )
    out = tmp_path / "ok.json"
    code = cli.main(["--target", TARGET, "--fetch-timeout", "120", "--out", str(out)])
    summary = json.loads(capsys.readouterr().out)
    data = _read(out)

    assert code == 0
    assert timeouts == [120.0]
    assert summary["status"] == "OK"
    assert summary["fetched"] == 1
    assert data["results"][0]["document"]["content_hash"].startswith("sha256:")
    assert data["fetch_errors"] == []


@pytest.mark.parametrize("bad", ["0", "-2", "181", "nan"])
def test_timeout_bounds_fail_at_cli_parse(bad):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--target", TARGET, "--fetch-timeout", bad])
    assert exc.value.code == 2
