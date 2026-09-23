"""The production bug: `Write the resolved prices into the ledger` failed
with Postgres 23505 / HTTP 409 on import_runs_storage_path_key, because an
exception-only run derived its storage_path from the calendar date alone
(``pricefeed-{observed_at}-none``) -- two different exception-only
harvests on the same day collided.

This is the client half of the fix: tools.pricefeed_write.run()/
_post_exceptions() must (1) derive a content hash for an exception-only
batch_ref, so two different harvests never collide and a replay of the
identical harvest always does, and (2) call import_runs/
import_run_exceptions the way migration_v49's schema expects --
``on_conflict=storage_path`` with ``resolution=merge-duplicates`` for the
run (its id is needed back either way), ``on_conflict=run_id,
exception_hash`` with ``resolution=ignore-duplicates`` for each exception
row. test_import_run_exceptions_idempotency_migration_v49.py proves that
SQL shape actually behaves as promised against a real Postgres; this
proves the client issues exactly that shape.

No real HTTP or Postgres here -- tools.import_worker._rest is replaced
outright, so these stay fast and only exercise pricefeed_write's own
orchestration and request construction.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from tools import pricefeed_write
from vehreg.catalog import Catalog
from vehreg.pricefeed import content_id

YEAR = 2026
MODEL_ID = "jaecoo.jaecoo_5_ev"
TRIM_ID = MODEL_ID + ".j5.trim.dynamic_bev"


def _write(path: Path, payload: dict) -> None:
    import json
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def _seed(root: Path) -> Path:
    _write(root / f"{YEAR}/models/jaecoo.json", {
        "brand": {
            "id": "jaecoo", "name_en": "Jaecoo", "name_th": "เจคู",
            "brand_segment": "MASS", "brand_origin": "CN", "aliases": [],
        },
        "models": [{
            "id": "jaecoo_5_ev", "name_en": "Jaecoo 5 EV", "nameplate": "Jaecoo 5",
            "body_type": "CROSSOVER", "cab_type": "NOT_APPLICABLE",
            "registration_type": "", "market_scope": "CORE", "aliases": [],
            "generations": [{
                "code": "J5", "segment": "B", "seats": 5,
                "variants": [{
                    "name": "58.9 kWh BEV", "powertrain": "BEV", "drivetrain": "FWD",
                    "battery_kwh": 58.9, "import_type": "CBU", "origin_country": "CN",
                    "aliases": [],
                }],
                "trims": [{
                    "id": "dynamic_bev", "name": "Dynamic", "variant": "58.9 kWh BEV",
                    "powertrain": "BEV", "drivetrain": "FWD", "aliases": [],
                }],
            }],
        }],
    })
    _write(root / f"{YEAR}/market/pricefeed/sources.json", {"sources": [{
        "id": "jaecoo-official", "name": "Jaecoo Thailand", "tier": "A",
        "base_url": "https://jaecoo.example", "adapter": "static",
    }]})
    return root


@pytest.fixture()
def data(tmp_path: Path) -> Path:
    return _seed(tmp_path / "data")


def _batch_file(data: Path, *, amount: int | None, name: str, published: str,
                trim_raw: str = "", url: str = "https://jaecoo.example/j5") -> Path:
    """A batch with an unresolvable claim (no trim_raw -> NO_TRIM_MATCH review
    item -> a PRICE_IDENTITY exception) when ``amount`` is given; a batch that
    matches an existing trim but disagrees would need real fixtures, so every
    test here exercises the exception-only path, which is what the bug hit."""
    document_id = content_id(f"{url}|{amount}|{published}|{name}")
    payload = {
        "documents": [{
            "document_id": document_id, "source_id": "jaecoo-official", "url": url,
            "content_hash": document_id, "published_at": f"{published}T08:00:00+00:00",
            "first_seen_at": f"{published}T09:00:00+00:00",
            "fetched_at": f"{published}T09:00:00+00:00", "title": "Jaecoo news",
        }],
        "claims": [{
            "claim_id": f"claim-{name}", "document_id": document_id,
            "source_id": "jaecoo-official", "brand_raw": "Jaecoo",
            "model_raw": "Some Unmatched Model", "trim_raw": trim_raw,
            "amount_thb": amount, "price_type": "LIST_PRICE",
            "effective_from": published,
        }],
    }
    target = data / f"{YEAR}/market/pricefeed/{name}.json"
    _write(target, payload)
    return target


def _run_with_supabase(data: Path, path: Path, observed_at: str, monkeypatch) -> tuple[dict, list]:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    calls: list[tuple[str, str, object, str | None]] = []

    def fake_rest(method, rest_path, payload=None, *, prefer=None):
        calls.append((method, rest_path, payload, prefer))
        if rest_path.startswith("import_runs"):
            return [{"id": "11111111-1111-1111-1111-111111111111"}]
        return []

    with patch("tools.import_worker._rest", side_effect=fake_rest):
        summary = pricefeed_write.run(path, data_dir=data, year=YEAR,
                                      observed_at=observed_at, apply=True)
    return summary, calls


def test_two_different_exception_only_harvests_the_same_day_get_different_batch_refs(
        data: Path, monkeypatch):
    batch_a = _batch_file(data, amount=899_000, name="batch-x", published="2026-09-23")
    batch_b = _batch_file(data, amount=799_000, name="batch-y", published="2026-09-23")

    summary_a, calls_a = _run_with_supabase(data, batch_a, "2026-09-23", monkeypatch)
    summary_b, calls_b = _run_with_supabase(data, batch_b, "2026-09-23", monkeypatch)

    ref_a = [c for c in calls_a if c[1].startswith("import_runs")][0][2]["storage_path"]
    ref_b = [c for c in calls_b if c[1].startswith("import_runs")][0][2]["storage_path"]
    assert ref_a != ref_b
    assert "-none" not in ref_a and "-none" not in ref_b


def test_replaying_the_identical_exception_only_harvest_gets_the_same_batch_ref(
        data: Path, monkeypatch):
    batch = _batch_file(data, amount=899_000, name="batch-z", published="2026-09-23")

    _summary_1, calls_1 = _run_with_supabase(data, batch, "2026-09-23", monkeypatch)
    _summary_2, calls_2 = _run_with_supabase(data, batch, "2026-09-23", monkeypatch)

    ref_1 = [c for c in calls_1 if c[1].startswith("import_runs")][0][2]["storage_path"]
    ref_2 = [c for c in calls_2 if c[1].startswith("import_runs")][0][2]["storage_path"]
    assert ref_1 == ref_2


def test_post_exceptions_upserts_the_run_and_ignores_duplicate_exception_rows(
        data: Path, monkeypatch):
    batch = _batch_file(data, amount=899_000, name="batch-w", published="2026-09-23")
    _summary, calls = _run_with_supabase(data, batch, "2026-09-23", monkeypatch)

    run_call = [c for c in calls if c[1].startswith("import_runs")][0]
    method, path, _payload, prefer = run_call
    assert method == "POST"
    assert path == "import_runs?on_conflict=storage_path"
    assert prefer == "resolution=merge-duplicates,return=representation"

    exception_calls = [c for c in calls if c[1].startswith("import_run_exceptions")]
    assert exception_calls, "expected at least one import_run_exceptions call"
    method, path, payload, prefer = exception_calls[0]
    assert method == "POST"
    assert path == "import_run_exceptions?on_conflict=run_id,exception_hash"
    assert prefer == "resolution=ignore-duplicates,return=minimal"
    assert all("exception_hash" in row and row["exception_hash"] for row in payload)


def test_no_supabase_url_skips_the_database_entirely(data: Path, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    batch = _batch_file(data, amount=899_000, name="batch-v", published="2026-09-23")
    with patch("tools.import_worker._rest") as mock_rest:
        summary = pricefeed_write.run(batch, data_dir=data, year=YEAR,
                                      observed_at="2026-09-23", apply=True)
    mock_rest.assert_not_called()
    assert summary["exceptions_stored"]["database"] == "skipped"
