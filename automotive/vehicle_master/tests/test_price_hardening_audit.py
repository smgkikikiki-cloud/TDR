from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path

import pytest

from tools.pricefetch_targets import _load_state_bundle
from vehreg.price_fetch import (
    FetchState,
    HttpResponse,
    OmodaJaecooThailandAdapter,
)
from vehreg.price_sources import SourceTarget, TargetRole
from vehreg.pricefeed import content_id
from vehreg.pricing import (
    CampaignOption,
    OfferStatus,
    PriceLedger,
    PricingError,
)


HTML = b"""<!doctype html><html><head><title>J5</title></head>
<body><h1>JAECOO 5 EV MAX+</h1><p>Price THB 699,000</p></body></html>"""


@dataclass
class FakeTransport:
    responses: list[HttpResponse]

    def __post_init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str], float]] = []

    def fetch(self, url: str, *, headers, timeout: float) -> HttpResponse:
        self.calls.append((url, dict(headers), timeout))
        if not self.responses:
            raise AssertionError("unexpected fetch")
        return self.responses.pop(0)


def _target() -> SourceTarget:
    return SourceTarget(
        id="jaecoo_test",
        source_id="official_jaecoo_th",
        url="https://www.omodajaecoo.co.th/th/model/jaecoo-5-ev",
        role=TargetRole.PRICE_LIST,
        model_hint="jaecoo.jaecoo_5_ev",
    )


def test_304_price_revalidation_performs_fresh_body_observation() -> None:
    previous = FetchState(
        target_id="jaecoo_test",
        content_hash=content_id(HTML),
        first_seen_at="2026-09-09T01:00:00+00:00",
        etag='"stable"',
        last_modified="Wed, 09 Sep 2026 01:00:00 GMT",
    )
    transport = FakeTransport([
        HttpResponse(status=304, url=_target().url, headers={}),
        HttpResponse(
            status=200,
            url=_target().url,
            headers={"content-type": "text/html", "etag": '"stable"'},
            body=HTML,
        ),
    ])
    adapter = OmodaJaecooThailandAdapter(
        transport=transport,
        clock=lambda: "2026-09-10T02:00:00+00:00",
    )

    result = adapter.fetch(
        _target(), previous=previous, refetch_not_modified=True)

    assert result.not_modified is False
    assert result.document is not None
    assert result.document.document_id == previous.content_hash
    assert result.document.first_seen_at == previous.first_seen_at
    assert result.document.fetched_at == "2026-09-10T02:00:00+00:00"
    assert len(transport.calls) == 2
    assert transport.calls[0][1]["If-None-Match"] == '"stable"'
    assert "If-None-Match" not in transport.calls[1][1]
    assert "If-Modified-Since" not in transport.calls[1][1]


def test_discovered_promotion_targets_round_trip_in_fetch_state(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "states": [{
            "target_id": "jaecoo_promotions:promotion:september",
            "content_hash": "sha256:" + "a" * 64,
            "first_seen_at": "2026-09-09T00:00:00+00:00",
            "etag": '"promo"',
            "last_modified": "",
        }],
        "discovered_targets": [{
            "id": "jaecoo_promotions:promotion:september",
            "source_id": "official_jaecoo_th",
            "url": "https://www.omodajaecoo.co.th/th/promotion/september",
            "role": "PROMOTION",
            "model_hint": "",
        }],
    }), encoding="utf-8")

    states, discovered = _load_state_bundle(path)

    assert "jaecoo_promotions:promotion:september" in states
    item = discovered["jaecoo_promotions:promotion:september"]
    assert item.role is TargetRole.PROMOTION
    assert item.as_source_target().url.endswith("/promotion/september")


def test_sold_out_option_closes_on_closed_at_day_not_day_after() -> None:
    option = CampaignOption(
        id="cash",
        status=OfferStatus.SOLD_OUT,
        closed_at="2026-08-25",
    )

    assert option.open_on(date(2026, 8, 24))
    assert not option.open_on(date(2026, 8, 25))
    assert option.status_on(date(2026, 8, 24)) is OfferStatus.ACTIVE
    assert option.status_on(date(2026, 8, 25)) is OfferStatus.SOLD_OUT


def test_campaign_parser_rejects_string_boolean_instead_of_truthy_coercion() -> None:
    ledger = PriceLedger(2026)
    with pytest.raises(PricingError, match="finance_required must be boolean"):
        ledger.add_campaign_payload({"campaigns": [{
            "id": "campaign.acme.bad",
            "brand_id": "acme",
            "options": [{
                "id": "finance",
                "conditions": {"finance_required": "false"},
            }],
        }]})


def test_campaign_quote_includes_finance_price_alternative() -> None:
    ledger = PriceLedger(2026)
    ledger.add_campaign_payload({"campaigns": [{
        "id": "campaign.acme.september",
        "brand_id": "acme",
        "name": "September",
        "options": [{
            "id": "finance",
            "label": "Finance",
            "conditions": {"finance_required": True, "text": "approved finance"},
        }],
    }]})
    ledger.add_payload({"prices": [{
        "trim_id": "acme.one.g1.trim.max",
        "amount_thb": 899_000,
        "price_type": "FINANCE_PRICE",
        "observed_at": "2026-09-01",
        "campaign_id": "campaign.acme.september",
        "option_id": "finance",
        "source": "official_oem",
    }]})

    quote = ledger.campaign_quote(
        "acme.one.g1.trim.max", as_of=date(2026, 9, 9))

    assert len(quote["campaign_options"]) == 1
    offer = quote["campaign_options"][0]
    assert offer["amount_thb"] == 899_000
    assert offer["price_type"] == "FINANCE_PRICE"
    assert offer["campaign_id"] == "campaign.acme.september"
    assert offer["option_id"] == "finance"
    assert offer["conditions"] == {
        "finance_required": True,
        "text": "approved finance",
    }


def test_legacy_admin_editor_is_not_a_price_writer_anymore() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    action = (repo_root / "app" / "admin" / "catalog-actions.ts").read_text(
        encoding="utf-8")

    assert "price_baht:t.priceBaht" not in action
    assert "retail_price_min:retailMin" not in action
    assert "retail_price_max:retailMax" not in action
