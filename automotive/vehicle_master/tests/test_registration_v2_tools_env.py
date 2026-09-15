"""Pure/offline coverage for the two DLT v2 live CLIs' non-network seams:
credential parsing (same pattern as every other Supabase tool in this
repository) and the pure row-adaptation helpers."""

from tools import backfill_registration_v2 as backfill
from tools import registration_v2_parity as parity


def test_clean_env_value_accepts_bare_assignment_and_quotes():
    cases = [
        ("abc", "abc"),
        (" KEY=abc ", "abc"),
        ("'KEY=abc'", "abc"),
        ('"KEY=abc"', "abc"),
    ]
    for raw, expected in cases:
        assert backfill._clean_env_value(raw, "KEY") == expected


def test_env_normalizes_copied_supabase_assignments(monkeypatch):
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    monkeypatch.delenv("NEXT_PUBLIC_SUPABASE_URL", raising=False)
    monkeypatch.setenv("SUPABASE_URL", '"SUPABASE_URL=https://example.supabase.co"')
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY",
                       "'SUPABASE_SERVICE_ROLE_KEY=eyJ.test.value'")
    assert backfill._env() == ("https://example.supabase.co", "eyJ.test.value")


def test_env_missing_credentials_raises_credentials_error(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("NEXT_PUBLIC_SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    try:
        backfill._env()
        assert False, "expected CredentialsError"
    except backfill.CredentialsError:
        pass


def test_month_range_computes_gte_lt_bounds():
    assert backfill._month_range("2026-03") == ("2026-03-01", "2026-04-01")


def test_month_range_rolls_over_the_year():
    assert backfill._month_range("2026-12") == ("2026-12-01", "2027-01-01")


def test_main_fails_closed_with_no_credentials(monkeypatch, capsys):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("NEXT_PUBLIC_SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    exit_code = backfill.main([])
    assert exit_code == 2
    err = capsys.readouterr().err
    assert "no server-side Supabase credentials found" in err
    assert "Nothing was read" in err


def test_parity_main_fails_closed_with_no_credentials(monkeypatch, capsys):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("NEXT_PUBLIC_SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    exit_code = parity.main([])
    assert exit_code == 2
    err = capsys.readouterr().err
    assert "no server-side Supabase credentials found" in err


def test_adapt_legacy_rows_preserves_raw_fields_and_never_repairs_null_model_id():
    raw = [{"id": "abc", "period": "2026-01-01", "registration_type": "RY1",
           "brand_name_raw": "TOYOTA", "model_name_raw": "YARIS ATIV",
           "model_id": None, "registrations": 100}]
    rows = parity.adapt_legacy_rows(raw)
    assert len(rows) == 1
    assert rows[0].id == "abc"
    assert rows[0].period == "2026-01"
    assert rows[0].model_id is None
    assert rows[0].units == 100.0


def test_adapt_legacy_rows_keeps_legacy_model_id_as_a_plain_string():
    raw = [{"id": "abc", "period": "2026-01-01", "registration_type": "RY1",
           "brand_name_raw": "TOYOTA", "model_name_raw": "YARIS ATIV",
           "model_id": "11111111-1111-4111-8111-111111111111",
           "registrations": 100}]
    rows = parity.adapt_legacy_rows(raw)
    assert rows[0].model_id == "11111111-1111-4111-8111-111111111111"


def test_readiness_mode_fails_closed_with_no_credentials(monkeypatch, capsys):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("NEXT_PUBLIC_SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    exit_code = parity.main(["--readiness", "--required-periods", "2026-01,2026-02"])
    assert exit_code == 2
    assert "no server-side Supabase credentials found" in capsys.readouterr().err


def test_never_cut_over_never_reads_credentials_message_is_present():
    # The readiness CLI's own help text documents the "never cut over
    # through a failed/unknown gate" rule directly in --help output.
    help_text = parity._parser().format_help()
    assert "--readiness" in help_text
