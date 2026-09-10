from tools import canonical_input_worker as worker


def test_clean_env_value_accepts_bare_assignment_and_quotes():
    assert worker._clean_env_value("abc", "KEY") == "abc"
    assert worker._clean_env_value(" KEY=abc ", "KEY") == "abc"
    assert worker._clean_env_value("'KEY=abc'", "KEY") == "KEY=abc"
    assert worker._clean_env_value('"abc"', "KEY") == "abc"


def test_env_normalizes_copied_supabase_assignments(monkeypatch):
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    monkeypatch.delenv("NEXT_PUBLIC_SUPABASE_URL", raising=False)
    monkeypatch.setenv("SUPABASE_URL", " SUPABASE_URL=https://example.supabase.co ")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", " SUPABASE_SERVICE_ROLE_KEY=eyJ.test.value ")
    assert worker._env() == ("https://example.supabase.co", "eyJ.test.value")


def test_env_prefers_modern_secret_key(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co/")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "SUPABASE_SECRET_KEY=sb_secret_live")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SERVICE_ROLE_KEY=legacy")
    assert worker._env() == ("https://example.supabase.co", "sb_secret_live")
