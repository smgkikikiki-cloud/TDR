#!/usr/bin/env python3
"""Bounded P2/P3/P4 pilot for Toyota/Honda Thailand static model pages."""
from __future__ import annotations

from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vehreg.price_extract import ExtractionResult, _visible_text  # noqa: E402
from vehreg.price_fetch import ADAPTERS, OfficialOEMAdapter  # noqa: E402
from vehreg.pricefeed import PriceClaim, content_id, grade_tokens, trims_by_model  # noqa: E402
from vehreg.price_match import (  # noqa: E402
    TrimMatchMethod, TrimMatchResult, TrimMatchState,
    match_trim_diagnostic as production_match,
)
from vehreg.pricing import PriceType  # noqa: E402
from vehreg.retail_catalog import load_retail_catalog  # noqa: E402
import tools.pricefetch_targets as runner  # noqa: E402


class _PilotToyotaHondaAdapter(OfficialOEMAdapter):
    adapter_id = "manual"
    allowed_hosts = frozenset({
        "toyota.co.th", "www.toyota.co.th",
        "honda.co.th", "www.honda.co.th",
    })
    source_ids = frozenset({"official_toyota_th", "official_honda_th"})


class _RetailCatalogFacade:
    @classmethod
    def load(cls, data_dir, year):
        return load_retail_catalog(data_dir, year)


ADAPTERS[_PilotToyotaHondaAdapter.adapter_id] = _PilotToyotaHondaAdapter
runner.Catalog = _RetailCatalogFacade


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
        pattern = re.compile(
            r"(e:HEV\s+(?:RS\s+4WD|HuNT|ES|RS|E))\s+"
            r"(\d{1,3}(?:,\d{3})+)\b", re.I,
        )
        for match in pattern.finditer(text):
            claims.append(_claim(result, brand="Honda", model="CR-V",
                                 trim=match.group(1), amount=match.group(2)))
    elif target.id == "toyota_th_corolla_cross":
        pattern = re.compile(
            r"(HEV\s+(?:Premium\s+Luxury|Premium|Smart))\s+"
            r"ราคาเริ่มต้น\s+(\d{1,3}(?:,\d{3})+)\s+บาท", re.I,
        )
        for match in pattern.finditer(text):
            claims.append(_claim(result, brand="Toyota", model="Corolla Cross",
                                 trim=match.group(1), amount=match.group(2)))
    else:
        return runner.extract_oem_price_claims(target, result)
    return ExtractionResult(claims=tuple(claims))


def _relaxed_surface(name: str) -> str:
    # Presentation annotations, not grade identity. This intentionally does NOT
    # erase 4WD/AWD or engine/battery tokens. Transmission omission is accepted
    # only when the relaxed surface resolves to one canonical trim.
    value = re.sub(r"\(\s*\d+\s*[- ]?Seater\s*\)", " ", name, flags=re.I)
    value = re.sub(r"\b(?:Super\s+)?CVT(?:-i)?\b", " ", value, flags=re.I)
    return " ".join(value.split())


def _pilot_match(catalog, claim, *, siblings_by_model=None, model_memo=None):
    first = production_match(
        catalog, claim,
        siblings_by_model=siblings_by_model,
        model_memo=model_memo,
    )
    if first.state is not TrimMatchState.UNMAPPED or first.model_id is None or \
            first.method is not TrimMatchMethod.NO_GRADE_MATCH:
        return first
    model = catalog.models[first.model_id]
    siblings = (siblings_by_model or trims_by_model(catalog)).get(first.model_id, [])
    wanted = grade_tokens(_relaxed_surface(claim.trim_raw), model.name_en)
    candidates = []
    for trim in siblings:
        surfaces = (trim.name, *trim.aliases)
        if wanted and any(
            grade_tokens(_relaxed_surface(surface), model.name_en) == wanted
            for surface in surfaces if surface
        ):
            candidates.append(trim.id)
    candidates = sorted(set(candidates))
    if len(candidates) == 1:
        return TrimMatchResult(
            TrimMatchState.EXACT, first.model_id, candidates[0], tuple(candidates),
            TrimMatchMethod.PARTIAL_GRADE,
            "unique exact grade after dropping non-identity seating/transmission annotations",
            first.normalized_trim_raw,
        )
    if len(candidates) > 1:
        return TrimMatchResult(
            TrimMatchState.AMBIGUOUS, first.model_id, None, tuple(candidates),
            TrimMatchMethod.AMBIGUOUS_PARTIAL,
            "annotation-tolerant grade surface maps to multiple canonical MarketTrims",
            first.normalized_trim_raw,
        )
    return first


runner.extract_oem_price_claims = _pilot_extract
runner.match_trim_diagnostic = _pilot_match


if __name__ == "__main__":
    raise SystemExit(runner.main())
