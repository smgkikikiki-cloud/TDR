from unittest.mock import patch

from tdr_bridge import publish
from tools import canonical_input_worker as worker


def test_clean_env_value_accepts_bare_assignment_and_quotes():
    cases = [
        ("abc", "abc"),
        (" KEY=abc ", "abc"),
        ("'KEY=abc'", "abc"),
        ('"KEY=abc"', "abc"),
        ('"abc"', "abc"),
        ("'abc'", "abc"),
    ]
    for raw, expected in cases:
        assert worker._clean_env_value(raw, "KEY") == expected
        assert publish._clean_env_value(raw, "KEY") == expected


def test_env_normalizes_copied_supabase_assignments(monkeypatch):
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    monkeypatch.delenv("NEXT_PUBLIC_SUPABASE_URL", raising=False)
    monkeypatch.setenv("SUPABASE_URL", '"SUPABASE_URL=https://example.supabase.co"')
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "'SUPABASE_SERVICE_ROLE_KEY=eyJ.test.value'")
    assert worker._env() == ("https://example.supabase.co", "eyJ.test.value")


def test_env_prefers_modern_secret_key(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co/")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "SUPABASE_SECRET_KEY=sb_secret_live")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SERVICE_ROLE_KEY=legacy")
    assert worker._env() == ("https://example.supabase.co", "sb_secret_live")


def test_publish_request_timeout_exceeds_the_rpcs_own_statement_timeout():
    # publish_vehicle_release(jsonb) carries its own 45s statement_timeout
    # (migration_v47) -- the RPC always errors out on that budget first, so
    # the client only has to outlast it, not guess at some other bound.
    assert publish.REQUEST_TIMEOUT_SECONDS > 45


def test_publish_actually_uses_the_configured_request_timeout():
    release = {"release_id": "vehicle-2026-test"}
    with patch("tdr_bridge.publish.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value.read.return_value = b"{}"
        publish.publish(release, url="https://example.supabase.co", service_key="k")
    assert mock_urlopen.call_args.kwargs["timeout"] == publish.REQUEST_TIMEOUT_SECONDS
