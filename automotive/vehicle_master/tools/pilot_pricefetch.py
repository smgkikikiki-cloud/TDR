#!/usr/bin/env python3
"""Bounded P2/P3 pilot for Toyota/Honda Thailand static model pages.

This file exists only on the price backfill pilot branch. It proves the generic
first-party HTML fetch/extract/match path before production adapter/extractor
registry changes. It does not write PriceLedger or serving data.
"""
from __future__ import annotations

from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vehreg.price_extract import ExtractionResult, _visible_text  # noqa: E402
from vehreg.price_fetch import ADAPTERS, OfficialOEMAdapter  # noqa: E402
from vehreg.pricefeed import PriceClaim, content_id  # noqa: E402
from vehreg.pricing import PriceType  # noqa: E402
import tools.pricefetch_targets as runner  # noqa: E402


class _PilotToyotaHondaAdapter(OfficialOEMAdapter):
    # Main still labels these sources "manual". The pilot overrides that one
    # adapter id in-process and remains bounded by source-id + hostname lists.
    adapter_id = "manual"
    allowed_hosts = frozenset({
        "toyota.co.th",
        "www.toyota.co.th",
        "honda.co.th",
        "www.honda.co.th",
    })
    source_ids = frozenset({"official_toyota_th", "official_honda_th"})


ADAPTERS[_PilotToyotaHondaAdapter.adapter_id] = _PilotToyotaHondaAdapter


def _claim(result, *, brand: str, model: str, trim: str, amount: str) -> PriceClaim:
    amount_thb = int(amount.replace(",", ""))
    semantic = (
        f"{result.document.document_id}|{brand}|{model}|{trim}|"
        f"{amount_thb}|{PriceType.LIST_PRICE.value}"
    )
    claim = PriceClaim(
        claim_id=content_id(semantic)[7:23],
        document_id=result.document.document_id,
        source_id=result.source_id,
        brand_raw=brand,
        model_raw=model,
        trim_raw=" ".join(trim.split()),
        amount_thb=amount_thb,
        price_type=PriceType.LIST_PRICE,
        evidence_text=f"{trim} {amount}",
        extraction_method="pilot:oem_static_grade",
    )
    problems = claim.validate()
    if problems:
        raise ValueError("; ".join(problems))
    return claim


def _pilot_extract(target, result) -> ExtractionResult:
    if result.not_modified or result.document is None:
        return ExtractionResult()
    text = " ".join(_visible_text(result).split())
    claims: list[PriceClaim] = []

    if target.id == "honda_th_crv":
        # The official page currently exposes one literal Grade Levels block.
        pattern = re.compile(
            r"(e:HEV\s+(?:RS\s+4WD|HuNT|ES|RS|E))\s+"
            r"(\d{1,3}(?:,\d{3})+)\b",
            re.I,
        )
        for match in pattern.finditer(text):
            claims.append(_claim(
                result,
                brand="Honda",
                model="CR-V",
                trim=match.group(1),
                amount=match.group(2),
            ))
    elif target.id == "toyota_th_corolla_cross":
        pattern = re.compile(
            r"(HEV\s+(?:Premium\s+Luxury|Premium|Smart))\s+"
            r"ราคาเริ่มต้น\s+(\d{1,3}(?:,\d{3})+)\s+บาท",
            re.I,
        )
        for match in pattern.finditer(text):
            claims.append(_claim(
                result,
                brand="Toyota",
                model="Corolla Cross",
                trim=match.group(1),
                amount=match.group(2),
            ))
    else:
        return runner.extract_oem_price_claims(target, result)

    return ExtractionResult(claims=tuple(claims))


# pricefetch_targets imports the production extractor by value, so replace only
# that local callable for this branch-only pilot.
runner.extract_oem_price_claims = _pilot_extract


if __name__ == "__main__":
    raise SystemExit(runner.main())
