from datetime import date

from tools.pricefeed_guard import _resolve_current_list, ledger_at


MAX_PLUS = "jaecoo.jaecoo_5_ev.j5.trim.max_plus_bev"


def test_guard_can_read_base_ledger_from_consolidated_repo_path() -> None:
    amounts = ledger_at("HEAD", 2026, as_of=date(2026, 9, 9))

    assert amounts[MAX_PLUS] == 699000


def test_guard_resolves_latest_list_start_not_first_json_row() -> None:
    rows = [
        {
            "trim_id": "t",
            "amount_thb": 699000,
            "price_type": "LIST_PRICE",
            "observed_at": "2026-09-01",
        },
        {
            "trim_id": "t",
            "amount_thb": 719000,
            "price_type": "LIST_PRICE",
            "observed_at": "2026-09-10",
        },
    ]

    assert _resolve_current_list(rows, as_of=date(2026, 9, 9))["t"] == 699000
    assert _resolve_current_list(rows, as_of=date(2026, 9, 10))["t"] == 719000


def test_guard_does_not_resurrect_older_open_list_after_newer_row_ends() -> None:
    rows = [
        {
            "trim_id": "t",
            "amount_thb": 699000,
            "price_type": "LIST_PRICE",
            "observed_at": "2026-08-01",
        },
        {
            "trim_id": "t",
            "amount_thb": 719000,
            "price_type": "LIST_PRICE",
            "observed_at": "2026-09-01",
            "effective_to": "2026-09-05",
        },
    ]

    assert "t" not in _resolve_current_list(rows, as_of=date(2026, 9, 6))
