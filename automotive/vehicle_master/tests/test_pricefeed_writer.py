"""The automated price path, end to end, against a real ledger on disk.

Every test here drives ``tools.pricefeed_write.run`` -- the command the
production workflow calls -- over a seeded canonical tree, and reads the
result back out of the PriceLedger the site resolves prices from. None of
them asserts on source text: a price is written when the resolver returns
it afterwards, and not written when it does not.
"""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path

import pytest

from tools import pricefeed_write
from vehreg.catalog import Catalog
from vehreg.input_pipeline import CanonicalInputPipeline
from vehreg.pricefeed import content_id
from vehreg.pricing import PriceLedger, PriceType

YEAR = 2026
MODEL_ID = "jaecoo.jaecoo_5_ev"
TRIM_ID = MODEL_ID + ".j5.trim.dynamic_bev"


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


@pytest.fixture()
def data(tmp_path: Path) -> Path:
    return _seed(tmp_path / "data")


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


def _batch_file(data: Path, *, amount: int, name: str, published: str,
                trim_raw: str = "Dynamic", url: str = "https://jaecoo.example/j5",
                price_type: str = "LIST_PRICE") -> Path:
    document_id = content_id(f"{url}|{amount}|{published}")
    payload = {
        "documents": [{
            "document_id": document_id, "source_id": "jaecoo-official", "url": url,
            "content_hash": document_id, "published_at": f"{published}T08:00:00+00:00",
            "first_seen_at": f"{published}T09:00:00+00:00",
            "fetched_at": f"{published}T09:00:00+00:00", "title": "Jaecoo 5 EV price",
        }],
        "claims": [{
            "claim_id": f"claim-{amount}-{published}", "document_id": document_id,
            "source_id": "jaecoo-official", "brand_raw": "Jaecoo",
            "model_raw": "Jaecoo 5 EV", "trim_raw": trim_raw,
            "amount_thb": amount, "price_type": price_type,
            "effective_from": published,
        }],
    }
    target = data / f"{YEAR}/market/pricefeed/{name}.json"
    _write(target, payload)
    return target


def _run(data: Path, path: Path, observed_at: str, **kwargs) -> dict:
    return pricefeed_write.run(path, data_dir=data, year=YEAR, decisions_path=None,
                               observed_at=observed_at, apply=kwargs.pop("apply", True),
                               **kwargs)


def _serving(data: Path, when: str) -> int | None:
    catalog = Catalog.load(data, YEAR)
    ledger = PriceLedger.load(data, year=YEAR, catalog=catalog)
    return ledger.current_list_amount(TRIM_ID, as_of=date.fromisoformat(when))


def _rows(data: Path) -> list:
    catalog = Catalog.load(data, YEAR)
    return PriceLedger.load(data, year=YEAR, catalog=catalog).records_for(
        TRIM_ID, include_retracted=True)


def _manual_price(data: Path, *, amount: int, day: str, batch_id: str) -> None:
    """An owner's Save, through the same pipeline the admin uses."""
    CanonicalInputPipeline(data).apply({
        "schema_version": 1, "batch_id": batch_id, "year": YEAR,
        "source": {"kind": "ADMIN", "ref": "admin"}, "actor": "owner",
        "reason": "owner correction", "submitted_at": f"{day}T10:00:00+00:00",
        "commands": [{
            "operation": "APPEND_PRICE", "canonical_id": TRIM_ID,
            "payload": {
                "trim_id": TRIM_ID, "amount_thb": amount, "price_type": "LIST_PRICE",
                "effective_from": day, "observed_at": day, "source": "admin",
            },
        }],
    })


# --- A: an accepted observation reaches the ledger the site reads ---------

def test_an_official_observation_becomes_a_price_the_resolver_serves(data: Path):
    assert _serving(data, "2026-09-10") is None

    batch = _batch_file(data, amount=899_000, name="batch-a", published="2026-09-10")
    summary = _run(data, batch, "2026-09-10")

    assert summary["canonical_offers"] == 1
    assert summary["planned"]["WRITTEN"] == 1
    assert summary["applied"] is True
    assert summary["now_serving"] == [{
        "trim_id": TRIM_ID, "price_type": "LIST_PRICE",
        "expected_thb": 899_000, "serving_thb": 899_000,
    }]
    assert _serving(data, "2026-09-10") == 899_000
    row = _rows(data)[0]
    assert (row.source, row.source_ref) == ("price_harvest", "https://jaecoo.example/j5")


# --- B: the same observation twice writes one price -----------------------

def test_reading_the_same_page_again_writes_nothing_new(data: Path):
    batch = _batch_file(data, amount=899_000, name="batch-b", published="2026-09-10")
    _run(data, batch, "2026-09-10")
    before = [r.amount_thb for r in _rows(data)]

    again = _run(data, batch, "2026-09-11")

    assert again["planned"]["UNCHANGED"] == 1
    assert again["planned"]["WRITTEN"] == 0
    assert again["batch_id"] is None
    assert [r.amount_thb for r in _rows(data)] == before
    assert _serving(data, "2026-09-11") == 899_000


def test_the_same_commands_are_the_same_batch_and_apply_once(data: Path, tmp_path: Path):
    """The batch id is its content, so a re-send is a replay, not a second price."""
    batch = _batch_file(data, amount=899_000, name="batch-b2", published="2026-09-10")
    planned = _planned_batch(data, batch, "2026-09-10")

    # The same observation prepared against an untouched tree gets the same id.
    elsewhere = _seed(tmp_path / "second")
    same = _planned_batch(elsewhere,
                          _batch_file(elsewhere, amount=899_000, name="batch-b2",
                                      published="2026-09-10"),
                          "2026-09-10")
    assert planned["batch_id"] == same["batch_id"]

    first = CanonicalInputPipeline(data).apply(planned)
    replay = CanonicalInputPipeline(data).apply(planned)

    assert not first.idempotent_replay
    assert replay.idempotent_replay
    assert [r.amount_thb for r in _rows(data)] == [899_000]
    assert _serving(data, "2026-09-10") == 899_000


def _planned_batch(data: Path, path: Path, observed_at: str) -> dict:
    """Plan the file without applying, to get the batch it would send."""
    summary = pricefeed_write.run(path, data_dir=data, year=YEAR, decisions_path=None,
                                  observed_at=observed_at, apply=False)
    return {
        "schema_version": 1, "batch_id": summary["batch_id"], "year": YEAR,
        "submitted_at": f"{observed_at}T00:00:00+00:00",
        "source": {"kind": "PRICE_HARVEST", "ref": "tools/pricefeed_harvest.py"},
        "actor": "price-feed", "reason": "automated price observation",
        "commands": summary["commands"],
    }


# --- C: a manual correction is not overwritten by an older observation ----

def test_an_observation_no_newer_than_a_manual_correction_never_lands(data: Path):
    _manual_price(data, amount=859_000, day="2026-09-12", batch_id="owner-fix-1")
    assert _serving(data, "2026-09-12") == 859_000

    stale = _batch_file(data, amount=899_000, name="batch-c", published="2026-09-12")
    summary = _run(data, stale, "2026-09-12")

    assert summary["planned"]["SUPERSEDED_BY_MANUAL"] == 1
    assert summary["planned"]["WRITTEN"] == 0
    assert _serving(data, "2026-09-12") == 859_000
    assert len(_rows(data)) == 1


def test_an_observation_older_than_the_manual_correction_never_lands(data: Path):
    _manual_price(data, amount=859_000, day="2026-09-12", batch_id="owner-fix-2")
    stale = _batch_file(data, amount=899_000, name="batch-c2", published="2026-09-01")

    summary = _run(data, stale, "2026-09-13")

    assert summary["planned"]["SUPERSEDED_BY_MANUAL"] == 1
    assert _serving(data, "2026-09-13") == 859_000


# --- D: a genuinely newer official price updates, keeping history ---------

def test_a_newer_official_price_supersedes_and_keeps_the_old_row_readable(data: Path):
    _run(data, _batch_file(data, amount=899_000, name="batch-d1",
                           published="2026-09-10"), "2026-09-10")

    summary = _run(data, _batch_file(data, amount=929_000, name="batch-d2",
                                     published="2026-10-01"), "2026-10-01")

    assert summary["planned"]["WRITTEN"] == 1
    assert summary["now_serving"][0]["serving_thb"] == 929_000
    assert _serving(data, "2026-10-01") == 929_000
    # The old price is still true of the period it covered.
    assert _serving(data, "2026-09-15") == 899_000
    rows = sorted(_rows(data), key=lambda r: r.amount_thb)
    assert [(r.amount_thb, r.effective_from, r.effective_to) for r in rows] == [
        (899_000, "2026-09-10", "2026-09-30"),
        (929_000, "2026-10-01", None),
    ]


def test_a_newer_official_price_outranks_an_older_manual_one(data: Path):
    _manual_price(data, amount=859_000, day="2026-09-12", batch_id="owner-fix-3")

    summary = _run(data, _batch_file(data, amount=929_000, name="batch-d3",
                                     published="2026-10-01"), "2026-10-01")

    assert summary["planned"]["WRITTEN"] == 1
    assert _serving(data, "2026-10-01") == 929_000
    assert _serving(data, "2026-09-20") == 859_000


# --- E: a failed fetch changes nothing ------------------------------------

def test_a_batch_that_harvested_nothing_leaves_the_served_price_alone(data: Path):
    _run(data, _batch_file(data, amount=899_000, name="batch-e1",
                           published="2026-09-10"), "2026-09-10")
    before = [(r.amount_thb, r.effective_from, r.effective_to) for r in _rows(data)]

    empty = data / f"{YEAR}/market/pricefeed/batch-e2.json"
    _write(empty, {"documents": [], "claims": []})
    summary = _run(data, empty, "2026-09-20")

    assert summary["canonical_offers"] == 0
    assert summary["batch_id"] is None
    assert summary["applied"] is False
    assert [(r.amount_thb, r.effective_from, r.effective_to) for r in _rows(data)] == before
    assert _serving(data, "2026-09-20") == 899_000


# --- F: an identity nobody can place becomes durable, resolvable work -----

def test_a_price_for_a_trim_nobody_can_place_becomes_an_open_exception(data: Path):
    batch = _batch_file(data, amount=999_000, name="batch-f", published="2026-09-10",
                        trim_raw="Summit Ultra Long Range")
    summary = _run(data, batch, "2026-09-10")

    assert summary["planned"]["WRITTEN"] == 0
    assert summary["exceptions_stored"]["count"] == 1
    stored = json.loads(Path(summary["exceptions_stored"]["file"]).read_text(encoding="utf-8"))
    row = stored["exceptions"][0]
    assert row["kind"] == "PRICE_IDENTITY"
    assert row["source_identity"]["amount_thb"] == 999_000
    assert row["source_identity"]["urls"] == ["https://jaecoo.example/j5"]
    # Nothing was written for it.
    assert _rows(data) == []


def test_an_exception_survives_the_run_that_produced_it(data: Path):
    """The old path kept this in the workflow log, which is gone in a week."""
    batch = _batch_file(data, amount=999_000, name="batch-f2", published="2026-09-10",
                        trim_raw="Summit Ultra Long Range")
    summary = _run(data, batch, "2026-09-10")
    path = Path(summary["exceptions_stored"]["file"])

    assert path.is_file()
    assert path.parent == data / f"{YEAR}/market/pricefeed/exceptions"


# --- G: the writer never calls the evidence-only command ------------------

def test_two_feed_observations_for_one_day_are_an_exception_not_a_coin_toss(data: Path):
    _run(data, _batch_file(data, amount=899_000, name="batch-g1",
                           published="2026-09-10"), "2026-09-10")

    summary = _run(data, _batch_file(data, amount=919_000, name="batch-g2",
                                     published="2026-09-10",
                                     url="https://jaecoo.example/j5-promo"),
                   "2026-09-10")

    assert summary["planned"]["EXCEPTION"] == 1
    assert summary["planned"]["WRITTEN"] == 0
    assert _serving(data, "2026-09-10") == 899_000
    stored = json.loads(Path(summary["exceptions_stored"]["file"]).read_text(encoding="utf-8"))
    assert stored["exceptions"][0]["kind"] == "PRICE_CONFLICT"
