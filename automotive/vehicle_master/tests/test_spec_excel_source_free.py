from types import SimpleNamespace

import pytest

from vehreg.comparable_specs import (
    ComparableSpecError,
    ComparisonRule,
    SpecFieldDefinition,
    SpecLedger,
    SpecRegistry,
    ValueType,
)
from vehreg.spec_excel import compile_rows


TRIM_ID = "test.model.g1.trim.base"
FIELD_KEY = "safety.aeb"


def _registry() -> SpecRegistry:
    return SpecRegistry([
        SpecFieldDefinition(
            key=FIELD_KEY,
            group="safety",
            label_th="AEB",
            label_en="AEB",
            value_type=ValueType.BOOLEAN,
            comparison_rule=ComparisonRule.PRESENCE,
        )
    ])


def _catalog():
    trim = SimpleNamespace(
        id=TRIM_ID,
        generation_id="test.model.g1",
        name="Base",
        powertrain=SimpleNamespace(value="BEV"),
    )
    generation = SimpleNamespace(id="test.model.g1", model_id="test.model", code="g1")
    model = SimpleNamespace(id="test.model", brand_id="test")
    return SimpleNamespace(
        trims={TRIM_ID: trim},
        generations={generation.id: generation},
        models={model.id: model},
    )


def test_excel_compiler_emits_source_free_admin_fact():
    compiled = compile_rows(
        [{"canonical_trim_id": TRIM_ID, FIELD_KEY: "YES"}],
        catalog=_catalog(),
        registry=_registry(),
        observed_at="2026-09-29",
        audit_ref="must-not-be-written-to-fact",
    )

    spec_command = next(
        command for command in compiled.commands
        if command["operation"] == "APPEND_SPEC"
    )
    payload = spec_command["payload"]

    assert payload["fact_id"].startswith("admin:")
    assert "source" not in payload
    assert "source_ref" not in payload
    assert "source_locator" not in payload
    assert payload["observed_at"] == "2026-09-29"


def test_spec_ledger_accepts_source_free_admin_fact():
    ledger = SpecLedger(_registry())
    ledger.add_payload({
        "schema_version": 1,
        "facts": [{
            "fact_id": f"admin:{TRIM_ID}:{FIELD_KEY}",
            "trim_id": TRIM_ID,
            "field_key": FIELD_KEY,
            "value_state": "KNOWN",
            "value": True,
            "observed_at": "2026-09-29",
        }],
    })

    assert len(ledger.facts) == 1
    assert ledger.facts[0].source == ""
    assert ledger.facts[0].source_ref == ""


def test_non_admin_fact_still_requires_source_evidence():
    ledger = SpecLedger(_registry())

    with pytest.raises(ComparableSpecError, match="source and source_ref are required"):
        ledger.add_payload({
            "schema_version": 1,
            "facts": [{
                "fact_id": f"oem:{TRIM_ID}:{FIELD_KEY}",
                "trim_id": TRIM_ID,
                "field_key": FIELD_KEY,
                "value_state": "KNOWN",
                "value": True,
                "observed_at": "2026-09-29",
            }],
        })
