"""Direct DLT -> v2 ingest: classification reuse (no duplicated Resolver
logic), skipped-class accounting, and the CLI's own argument/credential
guards."""

from unittest.mock import patch

from vehreg import dlt
from tools.registration_v2_dlt_ingest import DltFetchError, fetch_month_observations, main


def _resource(period="2026-08"):
    return dlt.Resource(id="res-1", name="test resource", period=period, year=2026)


def test_ry1_records_become_observations():
    records = [
        {"_id": 1, "ยี่ห้อ": "TOYOTA", "รุ่น": "YARIS ATIV", "จำนวน": "100",
        "ประเภทรถ": "รถยนต์นั่งส่วนบุคคลไม่เกิน 7 คน"},
    ]
    with patch.object(dlt, "fetch_records", return_value=iter(records)):
        observations, skipped = fetch_month_observations(
            "2026-08", resources={"2026-08": _resource()})
    assert len(observations) == 1
    assert observations[0].registration_type == "RY1"
    assert observations[0].raw_brand == "TOYOTA"
    assert skipped == {}


def test_non_car_classes_are_counted_not_dropped():
    records = [
        {"_id": 1, "ยี่ห้อ": "TOYOTA", "รุ่น": "YARIS ATIV", "จำนวน": "100",
        "ประเภทรถ": "รถยนต์นั่งส่วนบุคคลไม่เกิน 7 คน"},
        {"_id": 2, "ยี่ห้อ": "HONDA", "รุ่น": "WAVE", "จำนวน": "50",
        "ประเภทรถ": "รถจักรยานยนต์"},
    ]
    with patch.object(dlt, "fetch_records", return_value=iter(records)):
        observations, skipped = fetch_month_observations(
            "2026-08", resources={"2026-08": _resource()})
    assert len(observations) == 1
    assert skipped == {"รถจักรยานยนต์": 50}


def test_unknown_period_raises():
    try:
        fetch_month_observations("2099-01", resources={"2026-08": _resource()})
        assert False, "expected DltFetchError"
    except DltFetchError:
        pass


def test_observation_ids_are_keyed_by_ckan_record_id():
    records = [
        {"_id": 7, "ยี่ห้อ": "TOYOTA", "รุ่น": "YARIS ATIV", "จำนวน": "100",
        "ประเภทรถ": "รถยนต์นั่งส่วนบุคคลไม่เกิน 7 คน"},
    ]
    with patch.object(dlt, "fetch_records", return_value=iter(records)):
        observations, _ = fetch_month_observations(
            "2026-08", resources={"2026-08": _resource()})
    assert observations[0].source_ref == "res-1:7"


def test_main_requires_at_least_one_period(capsys):
    exit_code = main([])
    assert exit_code == 2
    assert "at least one --period" in capsys.readouterr().err


def test_main_fails_closed_with_no_credentials_during_apply(monkeypatch, capsys):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("NEXT_PUBLIC_SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    records = [
        {"_id": 1, "ยี่ห้อ": "TOYOTA", "รุ่น": "YARIS ATIV", "จำนวน": "100",
        "ประเภทรถ": "รถยนต์นั่งส่วนบุคคลไม่เกิน 7 คน"},
    ]
    with patch.object(dlt, "monthly_index", return_value={"2026-08": _resource()}), \
         patch.object(dlt, "fetch_records", return_value=iter(records)):
        exit_code = main(["--period", "2026-08", "--apply"])
    assert exit_code == 2
    assert "no server-side Supabase credentials found" in capsys.readouterr().err


def test_dry_run_performs_no_writes_and_exits_zero(capsys):
    records = [
        {"_id": 1, "ยี่ห้อ": "TOYOTA", "รุ่น": "YARIS ATIV", "จำนวน": "100",
        "ประเภทรถ": "รถยนต์นั่งส่วนบุคคลไม่เกิน 7 คน"},
    ]
    with patch.object(dlt, "monthly_index", return_value={"2026-08": _resource()}), \
         patch.object(dlt, "fetch_records", return_value=iter(records)):
        exit_code = main(["--period", "2026-08"])
    assert exit_code == 0
    assert "dry run: nothing written" in capsys.readouterr().err
