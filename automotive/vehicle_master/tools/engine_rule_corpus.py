"""Build the Phase 0 step 4 rule-parity corpus from the Python engine itself.

    python -m tools.engine_rule_corpus            # rewrite tests/fixtures/engine_rule_corpus.json
    python -m tools.engine_rule_corpus --check    # exit 1 if the committed corpus is stale

Every expected value in the corpus is produced here by running the existing
engine (vehreg / tdr_bridge) on the case input -- nothing is hand-written.
scripts/check-vehicle-engine-rules.ts then requires the TypeScript port
(lib/vehicle-engine/) to give the same result for every case, and
tests/test_engine_rule_corpus.py fails when the engine and the committed corpus
disagree, so the corpus cannot drift from the reference.

Database-enforced rules (migration_v59) are tested against the same engine
directly in tests/test_vehicle_engine_rules_migration_v59.py.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date
import json
import re
from pathlib import Path
import sys
import tempfile
from typing import Any, Callable

from tdr_bridge.lifecycle import apply_retail_lifecycle
from tdr_bridge.release import ReleaseBuilder
from vehreg import taxonomy
from vehreg.catalog import DATA_DIR, Catalog
from vehreg.comparable_specs import (
    ComparableSpecError, SpecFact, SpecLedger, SpecRegistry, ValueState, VerificationStatus,
)
from vehreg.current_retail import replace_current_retail_set
from vehreg.entities import cross_check, to_jsonable
from vehreg.homologation import ECOStickerSpecStore
from vehreg.model_operational_state import upsert_model_operational_state
from vehreg.pricing import PriceLedger, PricingError, _parse_campaign
from vehreg.product import close_price, correct_price
from vehreg.retail_lifecycle_review import (
    upsert_bootstrap_trim_lifecycle_disposition, upsert_trim_lifecycle_disposition,
)

VM_ROOT = Path(__file__).resolve().parents[1]
CORPUS = VM_ROOT / "tests" / "fixtures" / "engine_rule_corpus.json"
YEAR = 2026
REGISTRY_DIR = DATA_DIR / str(YEAR) / "product" / "comparable_specs"


#: Where a message names the file or in-memory source it came from. That part
#: is the loader's bookkeeping (and a temp path here), not the rule.
_SOURCE_PREFIX = re.compile(r"^(?:<memory>|<case>|\S+\.json): ")


def _outcome(fn: Callable[[], Any]) -> dict:
    """{"ok": True, "value": ...} or {"ok": False, "error_type": ..., "error": ...}."""
    try:
        return {"ok": True, "value": fn()}
    except Exception as exc:  # the engine's own exception, recorded verbatim
        return {"ok": False, "error_type": type(exc).__name__, "error": _SOURCE_PREFIX.sub("", str(exc))}


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Facet parsing (taxonomy.Facet.parse)
# ---------------------------------------------------------------------------

FACETS = ("Segment", "BodyType", "CabType", "MarketPosition", "Powertrain", "ImportType",
          "BrandSegment", "RegistrationType", "RetailStatus", "MarketScope", "Drivetrain")


def taxonomy_cases() -> list[dict]:
    raws: list[Any] = [None, True, False, 1, 2, 3, 0, "", " ", "unknown", "e-power", "range extender",
                       "Hybrid", " mhev ", "Plug-in Hybrid", "plug in hybrid", "4x4", "Four-WD",
                       "4wd", "fourwd", "2WD", "pick-up", "Pick Up", "suv", "SUV BOF", "crew cab",
                       "Cab 4", "4-door", "n/a", "na", "none", "รย.1", "รย.3", "ry 2", "RY-12",
                       "เกรย์", "grey market", "official", "luxury", "Premium Tech", "imported",
                       "Local", "cbu", "ckd ", "a", "f", "X", "electric", "EV", "fcev", "hydrogen"]
    for facet in FACETS:
        cls = getattr(taxonomy, facet)
        for member in cls:
            raws += [member.name, member.value, member.value.lower(), f" {member.value.lower()} "]
        raws += list(taxonomy.FACET_ALIASES.get(facet, {}))
    seen: set[str] = set()
    cases = []
    for facet in FACETS:
        cls = getattr(taxonomy, facet)
        for raw in raws:
            key = json.dumps([facet, raw], ensure_ascii=False)
            if key in seen:
                continue
            seen.add(key)
            cases.append({"facet": facet, "raw": raw, **_outcome(lambda: cls.parse(raw).value)})
    return cases


# ---------------------------------------------------------------------------
# 2. Resolution-chain rules (Catalog.validate -> cross_check)
# ---------------------------------------------------------------------------

def _resolution(catalog: Catalog) -> dict:
    declared = {m.id for m in catalog.models.values() if m.incomplete}
    problems: list[str] = []
    for resolved in catalog.iter_resolved():
        if catalog.model_for_variant(resolved.variant_id).id in declared:
            continue
        if catalog.variants[resolved.variant_id].incomplete:
            continue
        problems += cross_check(resolved)
    return {
        "year": catalog.year,
        "rows": {
            "brands": [to_jsonable(b) for b in catalog.brands.values()],
            "models": [to_jsonable(m) for m in catalog.models.values()],
            "generations": [to_jsonable(g) for g in catalog.generations.values()],
            "variants": [to_jsonable(v) for v in catalog.variants.values()],
        },
        "problems": problems,
    }


def _brand(models: list[dict], *, brand_id: str = "acme", origin: str = "CN",
           overrides: dict | None = None) -> dict:
    return {"brand": {"id": brand_id, "name_en": brand_id.title(), "name_th": "", "brand_segment": "MASS",
                      "oem_group": "Acme", "brand_origin": origin, "overrides": overrides or {}},
            "models": models}


def _model(model_id: str, *, body: str = "SEDAN", cab: str = "", reg: str = "", segment: str = "C",
           variants: list[dict] | None = None, incomplete: bool = False, overrides: dict | None = None,
           gen_overrides: dict | None = None) -> dict:
    return {"id": model_id, "name_en": model_id.replace("_", " ").title(), "body_type": body,
            "cab_type": cab, "registration_type": reg, "incomplete": incomplete,
            "overrides": overrides or {},
            "generations": [{"code": "G1", "segment": segment, "seats": 5, "launched": "2024-01-01",
                             "overrides": gen_overrides or {},
                             "variants": variants if variants is not None else [
                                 {"id": "base", "name": "Base", "powertrain": "ICE", "engine_cc": 1500,
                                  "import_type": "CBU", "origin_country": "JP"}]}]}


def resolution_cases() -> list[dict]:
    cases = [{"name": "repository catalog 2026", **_resolution(Catalog.load(DATA_DIR, YEAR))}]
    synthetic = {
        "pickup must be segment F": [_model("p1", body="PICKUP", cab="DOUBLE_CAB", segment="C")],
        "segment F only for pickups": [_model("s1", segment="F")],
        "pickup override segment from generation": [
            _model("p2", body="PICKUP", cab="SINGLE_SMART", segment="F", gen_overrides={"segment": "D"})],
        "ICE with battery": [_model("i1", variants=[{"id": "x", "name": "X", "powertrain": "ICE",
                                                     "engine_cc": 1500, "battery_kwh": 1.2}])],
        "PHEV battery from generation override": [_model("ph", gen_overrides={"battery_kwh": 18},
            variants=[{"id": "x", "name": "X", "powertrain": "PHEV", "engine_cc": 1500}])],
        "PHEV missing everything": [_model("ph2", variants=[{"id": "x", "name": "X", "powertrain": "PHEV"}])],
        "incomplete variant skipped": [_model("iv", variants=[{"id": "x", "name": "X", "powertrain": "PHEV",
                                                               "incomplete": True}])],
        "incomplete model skipped": [_model("im", body="OTHER", segment="F", incomplete=True,
                                            variants=[{"id": "x", "name": "X", "powertrain": "BEV"}])],
        "CKD origin from brand": [_model("ck", variants=[{"id": "x", "name": "X", "powertrain": "ICE",
                                                          "engine_cc": 1500, "import_type": "CKD"}])],
        "CKD with TH origin": [_model("ck2", variants=[{"id": "x", "name": "X", "powertrain": "ICE",
                                                        "engine_cc": 1500, "import_type": "SKD",
                                                        "origin_country": " th "}])],
        "registration override on model": [_model("r1", overrides={"registration_type": "RY3"})],
        "van is exempt": [_model("v1", body="VAN", reg="RY3")],
        "single cab registered RY1": [_model("sc", body="PICKUP", cab="SINGLE_SMART", reg="RY1", segment="F")],
        "variant cab override is ignored by resolve": [_model("lo", variants=[
            {"id": "x", "name": "X", "powertrain": "ICE", "engine_cc": 1500, "overrides": {"cab_type": "DOUBLE_CAB"}}])],
        "brand overrides segment": [_model("bo", segment="UNKNOWN")],
    }
    for name, models in synthetic.items():
        catalog = Catalog(YEAR)
        overrides = {"segment": "F"} if name == "brand overrides segment" else None
        catalog.add_brand_payload(_brand(models, overrides=overrides), source=name)
        cases.append({"name": name, **_resolution(catalog)})
    return cases


# ---------------------------------------------------------------------------
# 3. Price rows and campaigns: parsing (PriceLedger.add_payload, _parse_campaign)
# ---------------------------------------------------------------------------

def _parse_price(raw: Any, trims: set[str]) -> dict:
    ledger = PriceLedger(YEAR)
    ledger.catalog = type("C", (), {"trims": {t: None for t in trims}})()
    # Parse only: PriceLedger.add_payload raises before validate for parse
    # errors; a parsed row that fails PriceRecord.validate is reported under
    # "validate" so the database test can own it.
    from vehreg import pricing
    original = pricing.PriceRecord.validate
    pricing.PriceRecord.validate = lambda self: []  # type: ignore[method-assign]
    try:
        out = _outcome(lambda: (ledger.add_payload({"prices": [raw]}), to_jsonable(ledger.records[0]))[1])
    finally:
        pricing.PriceRecord.validate = original  # type: ignore[method-assign]
    if out["ok"]:
        out["validate"] = pricing.PriceRecord(**{**out["value"], "price_type": pricing.PriceType(out["value"]["price_type"])}).validate()
    return out


def price_parse_cases() -> list[dict]:
    trims = {"acme.a.g1.trim.base_ice"}
    t = "acme.a.g1.trim.base_ice"
    base = {"trim_id": t, "amount_thb": 899000, "price_type": "LIST_PRICE", "effective_from": "2026-01-01"}
    raws = [
        base, {**base, "amount_thb": "899000"}, {**base, "amount_thb": 899000.0}, {**base, "amount_thb": True},
        {**base, "amount_thb": -1}, {**base, "amount_thb": "8,990"}, {**base, "amount_thb": 0},
        {k: v for k, v in base.items() if k != "amount_thb"}, {**base, "price_type": "list_price "},
        {**base, "price_type": None}, {**base, "price_type": "msrp"}, {**base, "trim_id": " " + t + " "},
        {**base, "trim_id": "acme.a.g1.trim.ghost"}, {**base, "colour": "red"}, "not an object",
        {**base, "effective_from": "2026-02-30"}, {**base, "effective_from": "2026-1-01"},
        {**base, "effective_from": None, "observed_at": None},
        {**base, "effective_to": "2025-12-31"},
        {**base, "price_type": "CAMPAIGN_PRICE"},
        {**base, "price_type": "CAMPAIGN_PRICE", "campaign_id": " c1 ", "option_id": " o1 "},
        {**base, "option_id": "o1"}, {**base, "campaign_id": "c1"},
        {**base, "reference_price_thb": "999000"}, {**base, "reference_price_thb": 0},
        {**base, "reference_price_thb": 1.5}, {**base, "source_document_id": "sha256:" + "a" * 64},
        {**base, "source_document_id": "sha256:XYZ"}, {**base, "retracted_at": "2026-02-01"},
        {**base, "retracted_at": "2026-02-01", "retraction_reason": " typo "},
        {**base, "notes": None, "source": None, "reviewed_by": " Owner "},
        {**base, "price_type": "ECO_STICKER_PRICE", "effective_from": None},
    ]
    return [{"raw": raw, **_parse_price(raw, trims),
             **({"js_integral_float": True} if _has_integral_float(raw) else {})} for raw in raws]


def _has_integral_float(value: Any) -> bool:
    """A float like 899000.0: Python sees a float, JSON.parse sees the integer.

    TypeScript cannot tell the two apart after JSON.parse, so such cases are
    reported as a known language gap (ENGINE_RULES.md, finding F2) rather than
    compared."""
    if isinstance(value, float):
        return value.is_integer()
    if isinstance(value, dict):
        return any(_has_integral_float(v) for v in value.values())
    if isinstance(value, list):
        return any(_has_integral_float(v) for v in value)
    return False


def campaign_parse_cases() -> list[dict]:
    option = {"id": "cash", "label": "Cash", "status": "ACTIVE"}
    base = {"id": "c1", "brand_id": "acme", "name": " Q4 ", "starts": "2026-10-01", "ends": "2026-12-31",
            "options": [option]}
    raws = [
        base, {**base, "extra": 1}, {**base, "options": "cash"}, {**base, "options": ["cash"]},
        {**base, "options": [{**option, "colour": "red"}]}, {**base, "options": None},
        {**base, "quota_units": "200"}, {**base, "quota_units": True}, {**base, "quota_units": -5},
        {**base, "starts": "2026/10/01"}, {**base, "options": [{**option, "status": "sold_out"}]},
        {**base, "options": [{**option, "status": "paused"}]}, {**base, "options": [{**option, "status": None}]},
        {**base, "options": [{**option, "conditions": {"text": " booking in Oct ", "quota_units": "50"}}]},
        {**base, "options": [{**option, "conditions": {"finance_required": "yes"}}]},
        {**base, "options": [{**option, "conditions": {"colour": "red"}}]},
        {**base, "options": [{**option, "conditions": []}]},
        {**base, "options": [{**option, "conditions": None}]},
        {**base, "options": [{**option, "conditions": {"booking_from": "2026-13-01"}}]},
        {**base, "gifts": None, "notes": None, "source": " oem "},
        "campaign",
    ]

    def parse(raw):
        return to_jsonable(_parse_campaign(raw, "<case>"))

    out = []
    for raw in raws:
        result = _outcome(lambda: parse(raw))
        if result["ok"]:
            result["validate"] = _parse_campaign(raw, "<case>").validate()
        out.append({"raw": raw, **result})
    return out


# ---------------------------------------------------------------------------
# 4. Comparable-spec registry and the registry-dependent fact rules
# ---------------------------------------------------------------------------

#: SpecRegistry.load's own load errors (raised before validate runs). Anything
#: else it raises is SpecRegistry.validate's problem list joined with "; ".
_REGISTRY_LOAD_ERRORS = ("invalid registry schema", "invalid field definition", "unknown value_type",
                         "unknown comparison_rule", "duplicate spec field", "invalid profile")


def _registry_problems(registry: dict, profiles: dict | None) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / str(YEAR) / "product" / "comparable_specs"
        _write(root / "registry.json", registry)
        if profiles is not None:
            _write(root / "profiles.json", profiles)

        def run():
            try:
                return SpecRegistry.load(Path(tmp), YEAR).validate()
            except ComparableSpecError as exc:
                if any(marker in str(exc) for marker in _REGISTRY_LOAD_ERRORS):
                    raise
                return str(exc).split("; ")
        return _outcome(run)


def registry_cases() -> list[dict]:
    registry = json.loads((REGISTRY_DIR / "registry.json").read_text(encoding="utf-8"))
    profiles = json.loads((REGISTRY_DIR / "profiles.json").read_text(encoding="utf-8"))
    first = registry["fields"][0]
    numeric = next(f for f in registry["fields"] if f["value_type"] == "NUMBER")

    def mutate(**change):
        return {**registry, "fields": [{**first, **change}, *registry["fields"][1:]]}

    variants = {
        "repository registry": (registry, profiles),
        "bad key": (mutate(key="Bad Key"), None),
        "price field": (mutate(key="vehicle.price_thb"), None),
        "price unit": (mutate(canonical_unit="THB"), None),
        "missing label": (mutate(label_th=""), None),
        "numeric without unit": ({**registry, "fields": [{**numeric, "canonical_unit": ""},
                                  *[f for f in registry["fields"] if f is not numeric]]}, None),
        "negative precision": (mutate(display_precision=-1), None),
        "unknown key in definition": (mutate(colour="red"), None),
        "unknown value_type": (mutate(value_type="FLOAT"), None),
        "duplicate field": ({**registry, "fields": [first, first]}, None),
        "wrong schema": ({**registry, "schema_version": 2}, None),
        "profile unknown field": (registry, {**profiles, "profiles": [{"id": "p", "fields": ["nope.field"]}]}),
        "profile duplicate field": (registry, {**profiles, "profiles": [{"id": "p", "fields": [first["key"], first["key"]]}]}),
    }
    return [{"name": name, "registry": reg, "profiles": prof, **_registry_problems(reg, prof)}
            for name, (reg, prof) in variants.items()]


def fact_cases() -> list[dict]:
    registry = SpecRegistry.load(DATA_DIR, YEAR)
    catalog = Catalog(YEAR)
    trims = []
    for pt in ("ICE", "HEV", "PHEV", "BEV"):
        variant = {"id": pt.lower(), "name": pt, "powertrain": pt, "engine_cc": None if pt == "BEV" else 1500,
                   "battery_kwh": None if pt in ("ICE", "HEV") else 40, "import_type": "CBU", "origin_country": "CN"}
        trims.append({"id": f"t_{pt.lower()}", "name": pt, "powertrain": pt})
        catalog_variant = variant
    catalog.add_brand_payload(_brand([{**_model("f", variants=[catalog_variant]),
                                       "generations": [{"code": "G1", "segment": "C", "variants": [catalog_variant],
                                                        "trims": trims}]}]), source="facts")
    ledger = SpecLedger(registry, YEAR, catalog=catalog)
    by_type: dict[str, dict] = {}
    for definition in registry.fields.values():
        by_type.setdefault(definition.value_type.value, asdict(definition))
    powertrain_limited = next(d for d in registry.fields.values() if d.applicable_powertrains)
    qualified = next(d for d in registry.fields.values() if d.comparison_qualifiers)
    samples = {"NUMBER": [12, 0, -1, 1.5, "12", True, None], "BOOLEAN": [True, False, 1, "true", None],
               "ENUM": ["AWD", "", "  ", 3, None], "TEXT": ["x", "", 1, None],
               "SET": [["a"], [], ["a", ""], "a", [1], None]}
    cases = []

    def run(fact: dict, trim_powertrain: str) -> None:
        trim_id = f"acme.f.g1.trim.t_{trim_powertrain.lower()}"
        spec = SpecFact(fact_id=fact.get("fact_id", "oem:case"), trim_id=trim_id, field_key=fact["field_key"],
                        value_state=ValueState(fact.get("value_state", "KNOWN")), value=fact.get("value"),
                        unit=fact.get("unit", ""), qualifiers=fact.get("qualifiers", {}),
                        observed_at="2026-01-01", verification_status=VerificationStatus.VERIFIED,
                        source="oem", source_ref="https://example.test")
        problems = ledger._validate_fact(spec)
        cases.append({"fact": {"value_state": "KNOWN", **fact, "trim_id": trim_id}, "trim_powertrain": trim_powertrain,
                      "problems": problems})

    for value_type, definition in sorted(by_type.items()):
        for value in samples[value_type]:
            for unit in sorted({"", definition["canonical_unit"]}):
                run({"field_key": definition["key"], "value": value, "unit": unit}, "ICE")
        for state in ("UNKNOWN", "NOT_AVAILABLE", "NOT_APPLICABLE"):
            run({"field_key": definition["key"], "value_state": state, "value": None,
                 "unit": ""}, "ICE")
            run({"field_key": definition["key"], "value_state": state, "value": samples[value_type][0],
                 "unit": ""}, "ICE")
    run({"field_key": "nope.field", "value": 1, "unit": ""}, "ICE")
    for pt in ("ICE", "HEV", "PHEV", "BEV"):
        sample = samples[powertrain_limited.value_type.value][0]
        run({"field_key": powertrain_limited.key, "value": sample,
             "unit": powertrain_limited.canonical_unit}, pt)
    q = qualified.comparison_qualifiers[0]
    sample = samples[qualified.value_type.value][0]
    unit = qualified.canonical_unit
    ok_pt = qualified.applicable_powertrains[0] if qualified.applicable_powertrains else "ICE"
    run({"field_key": qualified.key, "value": sample, "unit": unit, "qualifiers": {q: "X"}}, ok_pt)
    run({"field_key": qualified.key, "value": sample, "unit": unit, "qualifiers": {"zzz": "X", q: "Y"}}, ok_pt)
    return cases


# ---------------------------------------------------------------------------
# 5. Mini data trees: write planners and served computations
# ---------------------------------------------------------------------------

def _tree(root: Path, *, trims: list[dict], ended: str | None = None, retail_status: str = "CURRENT",
          second_generation: bool = False, extra_variants: list[dict] | None = None) -> None:
    gens = [{"code": "G1", "segment": "C", "seats": 5, "launched": "2024-01-01", "ended": ended,
             "variants": [{"id": "base", "name": "Base", "powertrain": "ICE", "engine_cc": 1500,
                           "import_type": "CKD", "origin_country": "TH"}, *(extra_variants or [])],
             "trims": trims}]
    if second_generation:
        gens.append({"code": "G2", "segment": "D", "seats": 7, "launched": "2026-06-01",
                     "variants": [{"id": "hev", "name": "HEV", "powertrain": "HEV", "engine_cc": 2000,
                                   "battery_kwh": 1.6, "import_type": "CBU", "origin_country": "JP"}],
                     "trims": [{"id": "next_hev", "name": "Next", "powertrain": "HEV", "variant": "HEV"}]})
    _write(root / str(YEAR) / "models" / "acme.json", _brand([{
        "id": "a", "name_en": "Acme A", "body_type": "SEDAN", "retail_status": retail_status,
        "retail_checked_at": "2026-09-01", "retail_source": "https://example.test/a", "generations": gens}],
        origin="JP"))


TRIMS = [{"id": "base_ice", "name": "Base", "powertrain": "ICE", "variant": "Base"},
         {"id": "plus_ice", "name": "Plus", "powertrain": "ICE", "variant": "Base"},
         {"id": "top_ice", "name": "Top", "powertrain": "ICE", "variant": "Base"}]
T_BASE, T_PLUS, T_TOP = (f"acme.a.g1.trim.{t['id']}" for t in TRIMS)


def _prices(root: Path, rows: list[dict], name: str = "seed") -> None:
    _write(root / str(YEAR) / "market" / "prices" / f"{name}.json", {"prices": rows})


def _ledger_rows(root: Path) -> list[dict]:
    ledger = PriceLedger.load(root, year=YEAR)
    return [to_jsonable(r) for r in ledger.records]


SEED_PRICES = [
    {"trim_id": T_BASE, "amount_thb": 899000, "price_type": "LIST_PRICE", "effective_from": "2026-01-01",
     "observed_at": "2026-01-01", "source": "oem", "source_ref": "https://example.test/p"},
    {"trim_id": T_PLUS, "amount_thb": 999000, "price_type": "LIST_PRICE", "observed_at": "2026-03-01"},
    {"trim_id": T_PLUS, "amount_thb": 1049000, "price_type": "LIST_PRICE", "effective_from": "2026-08-01",
     "effective_to": "2026-12-31"},
    {"trim_id": T_TOP, "amount_thb": 1199000, "price_type": "LIST_PRICE", "effective_from": "2026-02-01"},
    {"trim_id": T_TOP, "amount_thb": 1149000, "price_type": "CAMPAIGN_PRICE", "effective_from": "2026-09-01",
     "campaign_id": "acme_q4", "option_id": "cash", "reference_price_thb": 1199000},
]
CAMPAIGNS = {"campaigns": [{"id": "acme_q4", "brand_id": "acme", "name": "Q4", "starts": "2026-09-01",
                            "ends": "2026-12-31", "gifts": "film",
                            "options": [{"id": "cash", "label": "Cash", "status": "ACTIVE",
                                         "conditions": {"text": "book by Nov", "booking_to": "2026-11-30"}},
                                        {"id": "loan", "label": "0%", "status": "SOLD_OUT",
                                         "closed_at": "2026-09-20"},
                                        {"id": "trade", "label": "Trade-in", "status": "ACTIVE"}]}]}


def planner_cases() -> list[dict]:
    scenarios = [
        ("supersede", "correct", dict(trim_id=T_BASE, price_type="LIST_PRICE", amount_thb=929000, reason="new list",
                                      reviewer="Owner", mode="supersede", effective_from="2026-10-01", as_of=date(2026, 10, 1))),
        ("supersede same amount", "correct", dict(trim_id=T_BASE, price_type="LIST_PRICE", amount_thb=899000,
                                                  reason="x", reviewer="Owner", as_of=date(2026, 10, 1))),
        ("supersede before start", "correct", dict(trim_id=T_BASE, price_type="LIST_PRICE", amount_thb=929000,
                                                   reason="x", reviewer="Owner", effective_from="2025-12-01",
                                                   as_of=date(2026, 10, 1))),
        ("retract", "correct", dict(trim_id=T_BASE, price_type="LIST_PRICE", amount_thb=909000, reason="typo",
                                    reviewer="Owner", mode="retract", as_of=date(2026, 10, 1))),
        ("no reviewer", "correct", dict(trim_id=T_BASE, price_type="LIST_PRICE", amount_thb=909000, reason="typo",
                                        reviewer="", as_of=date(2026, 10, 1))),
        ("bad mode", "correct", dict(trim_id=T_BASE, price_type="LIST_PRICE", amount_thb=909000, reason="typo",
                                     reviewer="Owner", mode="rewrite", as_of=date(2026, 10, 1))),
        ("no live row", "correct", dict(trim_id=T_PLUS, price_type="LIST_PRICE", amount_thb=1, reason="x",
                                        reviewer="Owner", as_of=date(2026, 2, 1))),
        ("two live rows", "correct", dict(trim_id=T_PLUS, price_type="LIST_PRICE", amount_thb=1, reason="x",
                                          reviewer="Owner", as_of=date(2026, 9, 1))),
        ("campaign scope", "correct", dict(trim_id=T_TOP, price_type="CAMPAIGN_PRICE", amount_thb=1129000,
                                           reason="deeper", reviewer="Owner", campaign_id="acme_q4", option_id="cash",
                                           effective_from="2026-10-01", as_of=date(2026, 10, 1))),
        ("close", "close", dict(trim_id=T_BASE, price_type="LIST_PRICE", ends="2026-10-31", reason="end of MY",
                                reviewer="Owner", as_of=date(2026, 10, 1))),
        ("close before start", "close", dict(trim_id=T_BASE, price_type="LIST_PRICE", ends="2025-10-31", reason="x",
                                             reviewer="Owner", as_of=date(2026, 10, 1))),
        ("close bad date", "close", dict(trim_id=T_BASE, price_type="LIST_PRICE", ends="2026-13-01", reason="x",
                                         reviewer="Owner", as_of=date(2026, 10, 1))),
    ]
    cases = []
    for name, op, args in scenarios:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _tree(root, trims=TRIMS)
            _prices(root, SEED_PRICES)
            _write(root / str(YEAR) / "market" / "campaigns" / "acme.json", CAMPAIGNS)
            before = _ledger_rows(root)
            fn = correct_price if op == "correct" else close_price
            result = _outcome(lambda: fn(root, YEAR, write=True, **args))
            if result["ok"]:
                result = {"ok": True, "value": {"changed": bool(result["value"].get("changed")),
                                                "after": _ledger_rows(root)}}
            cases.append({"name": name, "op": op, "args": {k: (v.isoformat() if isinstance(v, date) else v)
                                                           for k, v in args.items()},
                          "before": before, **result})
    return cases


def append_cases() -> list[dict]:
    from vehreg.canonical_write import CanonicalWriteCommand, CanonicalWritePipeline
    scenarios = {
        "new start appends": {"amount_thb": 919000, "price_type": "LIST_PRICE", "effective_from": "2026-11-01",
                              "observed_at": "2026-10-02", "source": "oem", "source_ref": "https://example.test/n"},
        "same start same amount is a no-op": {"amount_thb": 899000, "price_type": "LIST_PRICE",
                                              "effective_from": "2026-01-01", "observed_at": "2026-01-01"},
        "same start new amount retracts and replaces": {"amount_thb": 889000, "price_type": "LIST_PRICE",
                                                        "effective_from": "2026-01-01", "observed_at": "2026-01-01"},
        "campaign scope is separate": {"amount_thb": 1139000, "price_type": "CAMPAIGN_PRICE",
                                       "effective_from": "2026-09-01", "campaign_id": "acme_q4", "option_id": "cash"},
    }
    cases = []
    for name, record in scenarios.items():
        trim_id = T_TOP if record["price_type"] == "CAMPAIGN_PRICE" else T_BASE
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _tree(root, trims=TRIMS)
            _prices(root, SEED_PRICES)
            _write(root / str(YEAR) / "market" / "campaigns" / "acme.json", CAMPAIGNS)
            before = _ledger_rows(root)
            command = CanonicalWriteCommand.from_dict({
                "command_id": "case-1", "operation": "APPEND_PRICE", "year": YEAR, "actor": "Owner",
                "reason": "case", "canonical_id": trim_id, "payload": record,
                "submitted_at": "2026-10-02T00:00:00+00:00"})
            result = _outcome(lambda: CanonicalWritePipeline(root).apply(command))
            if result["ok"]:
                result = {"ok": True, "value": {"after": _ledger_rows(root)}}
            cases.append({"name": name, "trim_id": trim_id, "record": {**record, "trim_id": trim_id},
                          "before": before, **result})
    return cases


def sidecar_cases() -> list[dict]:
    cases = []
    lifecycle = [
        ("current with evidence", "CURRENT", None, dict(action="current", source_ref="https://example.test/x")),
        ("current without evidence", "CURRENT", None, dict(action="current", source_ref="")),
        ("current with non-url evidence", "CURRENT", None, dict(action="current", source_ref="owner said")),
        ("historical", "CURRENT", None, dict(action="historical", source_ref="https://example.test/x")),
        ("reopen", "CURRENT", None, dict(action="reopen", source_ref="ignored")),
        ("unknown action", "CURRENT", None, dict(action="archive", source_ref="https://example.test/x")),
        ("agent reviewer", "CURRENT", None, dict(action="current", reviewer="agent", source_ref="https://example.test/x")),
        ("bad date", "CURRENT", None, dict(action="current", reviewed_at="2026-02-30", source_ref="https://example.test/x")),
        ("compact date", "CURRENT", None, dict(action="current", reviewed_at="20260927", source_ref="https://example.test/x")),
        ("week date", "CURRENT", None, dict(action="current", reviewed_at="2026-W39-7", source_ref="https://example.test/x")),
        ("parent historical", "HISTORICAL", None, dict(action="historical", source_ref="https://example.test/x")),
        ("parent unverified without set", "UNVERIFIED", None, dict(action="historical", source_ref="https://example.test/x")),
        ("parent unverified, non-member historical", "UNVERIFIED", [T_PLUS],
         dict(action="historical", source_ref="https://example.test/x")),
        ("parent unverified, member historical", "UNVERIFIED", [T_BASE],
         dict(action="historical", source_ref="https://example.test/x")),
        ("parent unverified, current", "UNVERIFIED", [T_PLUS], dict(action="current", source_ref="https://example.test/x")),
        ("bootstrap historical without evidence", "CURRENT", None, dict(action="historical", source_ref="", bootstrap=True)),
        ("bootstrap current", "CURRENT", None, dict(action="current", source_ref="", bootstrap=True)),
        ("unknown trim", "CURRENT", None, dict(action="current", trim_id="acme.a.g1.trim.ghost",
                                              source_ref="https://example.test/x")),
    ]
    for name, parent, approved, args in lifecycle:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _tree(root, trims=TRIMS, retail_status=parent)
            if approved:
                _write(root / str(YEAR) / "market" / "trims" / "current_retail.json", {
                    "schema_version": 1, "models": [{"model_id": "acme.a", "trim_ids": approved,
                                                     "reviewer": "Owner", "reviewed_at": "2026-09-01"}]})
            call = {"trim_id": args.get("trim_id", T_BASE), "action": args["action"],
                    "reviewer": args.get("reviewer", "Owner"), "reviewed_at": args.get("reviewed_at", "2026-09-27"),
                    "source_ref": args["source_ref"], "notes": " checked ", "write": True}
            fn = upsert_bootstrap_trim_lifecycle_disposition if args.get("bootstrap") else upsert_trim_lifecycle_disposition
            result = _outcome(lambda: fn(data_dir=root, year=YEAR, **call))
            if result["ok"]:
                path = root / str(YEAR) / "market" / "retail_lifecycle" / "trim_review.json"
                stored = json.loads(path.read_text(encoding="utf-8"))["decisions"] if path.exists() else []
                result = {"ok": True, "value": {"decisions": stored}}
            cases.append({"kind": "trim_lifecycle", "name": name, "parent_retail_status": parent,
                          "approved": approved, "call": {k: v for k, v in call.items() if k != "write"},
                          "bootstrap": bool(args.get("bootstrap")),
                          "trim_exists": call["trim_id"] in {T_BASE, T_PLUS, T_TOP}, **result})
    current_sets = [
        ("ok", dict(trim_ids=[T_TOP, " " + T_BASE + " "])),
        ("empty", dict(trim_ids=[])),
        ("blank entry", dict(trim_ids=[T_BASE, " "])),
        ("duplicate", dict(trim_ids=[T_BASE, T_BASE])),
        ("system reviewer", dict(trim_ids=[T_BASE], reviewer="System")),
        ("ftp evidence", dict(trim_ids=[T_BASE], source_ref="ftp://x")),
        ("bad date", dict(trim_ids=[T_BASE], reviewed_at="09/27/2026")),
    ]
    for name, args in current_sets:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _tree(root, trims=TRIMS)
            call = {"model_id": "acme.a", "trim_ids": args["trim_ids"], "reviewer": args.get("reviewer", "Owner"),
                    "reviewed_at": args.get("reviewed_at", "2026-09-27"), "source_ref": args.get("source_ref", ""),
                    "notes": " lineup "}
            result = _outcome(lambda: replace_current_retail_set(data_dir=root, year=YEAR, write=True, **call))
            if result["ok"]:
                stored = json.loads((root / str(YEAR) / "market" / "trims" / "current_retail.json")
                                    .read_text(encoding="utf-8"))["models"]
                result = {"ok": True, "value": {"models": stored}}
            cases.append({"kind": "current_retail", "name": name, "call": call, **result})
    operational = [("maintenance", "under_maintenance"), ("normal", "normal"), ("bad", "paused")]
    for name, action in operational:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _tree(root, trims=TRIMS)
            call = {"model_id": "acme.a", "action": action, "reviewer": "Owner", "reviewed_at": "2026-09-27",
                    "source_ref": " note ", "notes": ""}
            result = _outcome(lambda: upsert_model_operational_state(data_dir=root, year=YEAR, write=True, **call))
            if result["ok"]:
                path = root / str(YEAR) / "market" / "operational_state" / "model_state.json"
                stored = json.loads(path.read_text(encoding="utf-8"))["decisions"] if path.exists() else []
                result = {"ok": True, "value": {"decisions": stored}}
            cases.append({"kind": "model_operational_state", "name": name, "call": call, **result})
    return cases


def served_cases() -> list[dict]:
    """Release values computed by the engine, with the master rows they come from."""
    registry_rows = json.loads((REGISTRY_DIR / "registry.json").read_text(encoding="utf-8"))
    number = next(f for f in registry_rows["fields"] if f["value_type"] == "NUMBER" and not f.get("comparison_qualifiers")
                  and not f.get("applicable_powertrains"))
    scenarios = {
        "prices, campaigns, specs, sidecars": dict(as_of="2026-10-01", second_generation=True,
                                                   approved=None, decisions=[], maintenance=False, ended=None),
        "approved set and historical decision": dict(as_of="2026-10-01", second_generation=False,
                                                     approved=[T_BASE, T_TOP],
                                                     decisions=[{"trim_id": T_PLUS, "status": "HISTORICAL"}],
                                                     maintenance=False, ended=None),
        "decision without set": dict(as_of="2026-10-01", second_generation=False, approved=None,
                                     decisions=[{"trim_id": T_TOP, "status": "HISTORICAL"}],
                                     maintenance=False, ended=None),
        "maintenance and ended generation": dict(as_of="2026-10-01", second_generation=True, approved=None,
                                                 decisions=[], maintenance=True, ended="2026-06-30"),
        "earlier as_of": dict(as_of="2026-09-05", second_generation=True, approved=None, decisions=[],
                              maintenance=False, ended=None),
        # Boundaries: the loan option closes on 2026-09-20; the cash option's
        # booking window ends 2026-11-30; the G1 generation ends on as_of itself.
        "campaign's first day": dict(as_of="2026-09-01", second_generation=True, approved=None,
                                     decisions=[], maintenance=False, ended=None),
        "on the day an option closes": dict(as_of="2026-09-20", second_generation=True, approved=None,
                                            decisions=[], maintenance=False, ended=None),
        "the day before it closes": dict(as_of="2026-09-19", second_generation=True, approved=None,
                                         decisions=[], maintenance=False, ended=None),
        "last booking day": dict(as_of="2026-11-30", second_generation=True, approved=None,
                                 decisions=[], maintenance=False, ended=None),
        "after the booking window": dict(as_of="2026-12-01", second_generation=True, approved=None,
                                         decisions=[], maintenance=False, ended=None),
        "campaign's last day": dict(as_of="2026-12-31", second_generation=True, approved=None,
                                    decisions=[], maintenance=False, ended=None),
        "after a price window closes": dict(as_of="2027-01-15", second_generation=True, approved=None,
                                            decisions=[], maintenance=False, ended=None),
        "generation ends on as_of": dict(as_of="2026-10-01", second_generation=True, approved=None,
                                         decisions=[], maintenance=False, ended="2026-10-01"),
    }
    cases = []
    for name, sc in scenarios.items():
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _tree(root, trims=TRIMS, second_generation=sc["second_generation"], ended=sc["ended"])
            _prices(root, SEED_PRICES + [
                {"trim_id": T_BASE, "amount_thb": 879000, "price_type": "LIST_PRICE", "effective_from": "2026-01-01",
                 "retracted_at": "2026-01-05", "retraction_reason": "typo"},
                {"trim_id": T_TOP, "amount_thb": 1159000, "price_type": "FINANCE_PRICE",
                 "effective_from": "2026-09-01", "campaign_id": "acme_q4", "option_id": "loan"},
                {"trim_id": T_BASE, "amount_thb": 869000, "price_type": "CAMPAIGN_PRICE",
                 "effective_from": "2026-09-01", "campaign_id": "acme_q4", "option_id": "trade",
                 "reference_price_thb": 899000}])
            _write(root / str(YEAR) / "market" / "campaigns" / "acme.json", CAMPAIGNS)
            for f in ("registry.json", "profiles.json"):
                _write(root / str(YEAR) / "product" / "comparable_specs" / f,
                       json.loads((REGISTRY_DIR / f).read_text(encoding="utf-8")))
            facts = [
                {"fact_id": "oem:b1", "trim_id": T_BASE, "field_key": number["key"], "value_state": "KNOWN",
                 "value": 10, "unit": number["canonical_unit"], "observed_at": "2026-01-01",
                 "source": "oem", "source_ref": "https://example.test/s"},
                {"fact_id": "oem:b2", "trim_id": T_BASE, "field_key": number["key"], "value_state": "KNOWN",
                 "value": 11, "unit": number["canonical_unit"], "observed_at": "2026-09-01",
                 "source": "oem", "source_ref": "https://example.test/s"},
                {"fact_id": "oem:b3", "trim_id": T_BASE, "field_key": number["key"], "value_state": "KNOWN",
                 "value": 12, "unit": number["canonical_unit"], "observed_at": "2026-09-20",
                 "verification_status": "PROVISIONAL", "source": "oem", "source_ref": "https://example.test/s"},
                {"fact_id": "oem:p1", "trim_id": T_PLUS, "field_key": number["key"], "value_state": "UNKNOWN",
                 "value": None, "unit": "", "observed_at": "2026-02-01", "effective_to": "2026-09-01",
                 "source": "oem", "source_ref": "https://example.test/s"},
            ]
            _write(root / str(YEAR) / "product" / "comparable_specs" / "facts" / "case.json",
                   {"schema_version": 1, "facts": facts})
            if sc["approved"]:
                _write(root / str(YEAR) / "market" / "trims" / "current_retail.json", {
                    "schema_version": 1, "models": [{"model_id": "acme.a", "trim_ids": sc["approved"],
                                                     "reviewer": "Owner", "reviewed_at": "2026-09-01"}]})
            if sc["decisions"]:
                _write(root / str(YEAR) / "market" / "retail_lifecycle" / "trim_review.json", {
                    "schema_version": 1, "decisions": [{**d, "reviewer": "Owner", "reviewed_at": "2026-09-01",
                                                        "source_ref": "https://example.test/d", "notes": ""}
                                                       for d in sc["decisions"]]})
            if sc["maintenance"]:
                _write(root / str(YEAR) / "market" / "operational_state" / "model_state.json", {
                    "schema_version": 1, "decisions": [{"model_id": "acme.a", "status": "UNDER_MAINTENANCE",
                                                        "reviewer": "Owner", "reviewed_at": "2026-09-01"}]})
            as_of = date.fromisoformat(sc["as_of"])
            builder = ReleaseBuilder({"brands": [], "models": []}, data_dir=root, year=YEAR)
            release = apply_retail_lifecycle(builder.build(as_of=as_of), data_dir=root, year=YEAR)
            master = builder.master
            ledger = PriceLedger.load(root, year=YEAR)
            spec_ledger = SpecLedger.load(root, YEAR)
            rows = {
                "models": [{"canonical_id": m["canonical_id"], "payload": m["payload"]} for m in release["models"]],
                "generations": [g["payload"] for g in release["generations"]],
                "variants": [to_jsonable(v) for v in master.catalog.variants.values()],
                "trims": [{"canonical_id": t["canonical_id"], "model_id": t["model_id"],
                           "generation_id": t["generation_id"],
                           "catalog_payload": to_jsonable(master.catalog.trims[t["canonical_id"]])}
                          for t in release["market_trims"]],
                "prices": [to_jsonable(r) for r in ledger.records],
                "campaigns": [to_jsonable(c) for c in ledger.campaigns.values()],
                "facts": [to_jsonable(asdict(f)) for f in spec_ledger.facts],
                "eco": [],
                "approved": {"acme.a": sc["approved"]} if sc["approved"] else {},
                "decisions": [{**d, "reviewer": "Owner", "reviewed_at": "2026-09-01",
                               "source_ref": "https://example.test/d", "notes": ""} for d in sc["decisions"]],
                "maintenance": ["acme.a"] if sc["maintenance"] else [],
            }
            expected = {
                "models": [{k: m[k] for k in ("canonical_id", "generation_id", "segment", "status",
                                               "retail_price_min", "retail_price_max")}
                           | {"payload": {k: m["payload"][k] for k in ("generation", "seats", "powertrains",
                                                                       "production_type", "production_country",
                                                                       "launch_year")}}
                           for m in release["models"]],
                "trims": [{"canonical_id": t["canonical_id"], "status": t["status"],
                           "current_list_price": t["current_list_price"], "campaign_quote": t["campaign_quote"],
                           "price_history": t["price_history"],
                           "comparable_specs": t["payload"]["comparable_specs"],
                           "ecosticker_evidence": t["payload"]["ecosticker_evidence"]}
                          for t in release["market_trims"]],
            }
            cases.append({"name": name, "as_of": sc["as_of"], "rows": rows, "expected": expected})
    return cases


def build() -> dict:
    return {
        "_about": "Generated by tools/engine_rule_corpus.py from the Python engine; do not edit by hand.",
        "taxonomy": taxonomy_cases(),
        "resolution": resolution_cases(),
        "price_parse": price_parse_cases(),
        "campaign_parse": campaign_parse_cases(),
        "registry": registry_cases(),
        "facts": fact_cases(),
        "price_planners": planner_cases(),
        "append_price": append_cases(),
        "sidecars": sidecar_cases(),
        "served": served_cases(),
    }


def render(corpus: dict) -> str:
    return json.dumps(corpus, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the committed corpus is stale")
    args = parser.parse_args(argv)
    text = render(build())
    if args.check:
        current = CORPUS.read_text(encoding="utf-8") if CORPUS.exists() else ""
        if current != text:
            print(f"{CORPUS} is stale; run python -m tools.engine_rule_corpus", file=sys.stderr)
            return 1
        print("engine rule corpus is current")
        return 0
    CORPUS.parent.mkdir(parents=True, exist_ok=True)
    CORPUS.write_text(text, encoding="utf-8")
    print(f"wrote {CORPUS} ({len(text):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
