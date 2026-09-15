"""The registration cutover switch: argument validation and the
no-credentials fail-closed path (rollback-selector coverage)."""

import pytest

from tools import registration_v2_cutover as cutover


def test_exactly_one_action_is_required():
    parser = cutover._parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_status_switch_and_boundary_are_mutually_exclusive():
    parser = cutover._parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--status", "--switch", "v2"])


def test_switch_only_accepts_legacy_or_v2():
    parser = cutover._parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--switch", "something-else"])
    args = parser.parse_args(["--switch", "v2"])
    assert args.switch == "v2"
    args = parser.parse_args(["--switch", "legacy"])
    assert args.switch == "legacy"


def test_main_fails_closed_with_no_credentials_on_status(monkeypatch, capsys):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("NEXT_PUBLIC_SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    exit_code = cutover.main(["--status"])
    assert exit_code == 2
    err = capsys.readouterr().err
    assert "no server-side Supabase credentials found" in err
    assert "Nothing was read or written" in err


def test_main_fails_closed_with_no_credentials_on_switch(monkeypatch, capsys):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("NEXT_PUBLIC_SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    exit_code = cutover.main(["--switch", "legacy"])
    assert exit_code == 2
    assert "no server-side Supabase credentials found" in capsys.readouterr().err


def test_main_fails_closed_with_no_credentials_on_set_boundary(monkeypatch, capsys):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("NEXT_PUBLIC_SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    exit_code = cutover.main(["--set-boundary", "2026-08"])
    assert exit_code == 2
    assert "no server-side Supabase credentials found" in capsys.readouterr().err


def test_rollback_is_the_same_switch_mechanism_as_cutover():
    # Both directions go through the identical set_serving_source RPC call
    # shape - rollback is not a special/different code path.
    import inspect
    source = inspect.getsource(cutover.main)
    assert source.count("set_serving_source(args.switch)") == 1
