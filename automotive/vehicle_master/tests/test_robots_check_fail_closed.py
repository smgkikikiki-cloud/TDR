"""Robots permission must fail closed on transport failures and exact paths.

These tests never make network requests or require an OEM connection.
"""
from __future__ import annotations

import io
import json
import urllib.error
from unittest.mock import patch

import pytest

from tools import pricefetch_targets, robots_check


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.URLError("proxy connect_rejected 403"),
        TimeoutError("connection timed out"),
        urllib.error.HTTPError("https://oem.invalid/robots.txt", 403, "Forbidden", {}, None),
        urllib.error.HTTPError("https://oem.invalid/robots.txt", 429, "Rate limited", {}, None),
        urllib.error.HTTPError("https://oem.invalid/robots.txt", 503, "Unavailable", {}, None),
    ],
)
def test_transport_and_nonmissing_http_errors_are_unknown(error):
    with patch.object(robots_check.urllib.request, "urlopen", side_effect=error):
        report = robots_check.audit("https://oem.invalid/private/price")
    assert report["robots_status"] == "UNREACHABLE"
    assert report["checked_url"] == "https://oem.invalid/private/price"
    assert report["may_fetch"] is False
    assert robots_check.verdict(report) == "unknown: robots.txt unreachable"


@pytest.mark.parametrize("code", [404, 410])
def test_only_explicit_missing_robots_can_be_recorded_as_absent(code):
    error = urllib.error.HTTPError(
        "https://oem.invalid/robots.txt", code, "Missing", {}, None
    )
    with patch.object(robots_check.urllib.request, "urlopen", side_effect=error):
        report = robots_check.audit("https://oem.invalid/sales")
    assert report["robots_status"] == "ABSENT"
    assert report["may_fetch"] is True
    assert robots_check.verdict(report).startswith("allowed")


def test_path_disallow_is_honored_even_when_homepage_is_allowed(monkeypatch):
    robots = "User-agent: tdr-automotive\nDisallow: /private/\n"
    monkeypatch.setattr(robots_check, "fetch", lambda *args, **kwargs: robots)
    public_url = "https://oem.invalid/public/cars"
    private_url = "https://oem.invalid/private/prices"
    assert robots_check.verdict(robots_check.audit(public_url)) == "allowed"
    assert robots_check.verdict(robots_check.audit(private_url)).startswith("refused")
    cache: dict[str, str] = {}
    assert pricefetch_targets._robots_allowed(public_url, cache) is True
    assert pricefetch_targets._robots_allowed(private_url, cache) is False
    assert set(cache) == {public_url, private_url}


def test_fetch_gate_rejects_unknown_robots(monkeypatch):
    monkeypatch.setattr(robots_check, "fetch", lambda *args, **kwargs: None)
    url = "https://oem.invalid/th/model/test"
    cache: dict[str, str] = {}
    assert pricefetch_targets._robots_allowed(url, cache) is False
    assert cache[url] == "unknown: robots.txt unreachable"


def test_robot_audit_cli_exits_nonzero_on_unknown(monkeypatch, capsys):
    monkeypatch.setattr(robots_check, "load_sources", lambda *args: {})
    monkeypatch.setattr(robots_check, "fetch", lambda *args, **kwargs: None)
    code = robots_check.main(["--url", "https://oem.invalid/private"])
    assert code == 2
    printed = json.loads(capsys.readouterr().out)
    assert printed["https://oem.invalid/private"]["robots_status"] == "UNREACHABLE"


def test_available_robots_text_and_content_signal_still_apply():
    response = io.BytesIO(
        b"User-agent: tdr-automotive\nDisallow: /private/\nContent-Signal: ai-input=no\n"
    )
    with patch.object(robots_check.urllib.request, "urlopen", return_value=response):
        report = robots_check.audit("https://oem.invalid/public")
    assert report["robots_status"] == "PRESENT"
    assert report["content_signal"]["ai-input"] == "no"
    assert robots_check.verdict(report).startswith("refused")
