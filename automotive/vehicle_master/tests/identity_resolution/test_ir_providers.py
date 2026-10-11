"""Identity Resolution contract v1: the provider-adapter interface is generic.

A toy second provider ("acme": nameplates, Gregorian dates, no lineage) assembles a valid snapshot without any change to
the contract or to the interface — which is the point of making Ice an adapter rather than a dependency.
"""
from __future__ import annotations

import re

import pytest

from identity_resolution.providers import base

import ir_support as S


class AcmeSubjects:
    provider_id = "acme"

    def source_version(self):
        return {"label": "acme:2026-09:r3", "attributes": {"release": "3"}}

    def as_of_period(self):
        return "2026-09"

    def subjects(self):
        return [{"entity_kind": "nameplate", "entity_id": "acme-roadster", "display_name": "Roadster", "brand": "ACME", "identity_status": "settled",
                 "series": {"start": "2026-01", "counts": [10, 12, None, 9], "coverage_declared": True}}]

    def lineage(self):
        return {"source_present": False, "declared_identity_change": False, "events": []}


class Targets:
    def targets(self):
        return [{"target_kind": "tdr_model", "target_id": "acme_roadster", "brand": "Acme", "display_name": "Roadster", "status": "CURRENT", "deleted": False}]

    def existing_mappings(self):
        return []


def test_a_second_provider_assembles_a_valid_snapshot_without_touching_the_contract():
    snapshot = base.assemble_snapshot(AcmeSubjects(), Targets(), policy_version=S.policy()["policy"]["version"])
    assert snapshot["provider"] == "acme" and snapshot["subjects"][0]["entity_kind"] == "nameplate"
    assert isinstance(AcmeSubjects(), base.SubjectSource) and isinstance(Targets(), base.TargetSource)


def test_a_snapshot_the_engine_would_reject_fails_at_the_boundary():
    class NoVersion(AcmeSubjects):
        def source_version(self):
            return {}

    with pytest.raises(base.SnapshotError, match="label"):
        base.assemble_snapshot(NoVersion(), Targets(), policy_version="1.0.0")

    class BadStatus(AcmeSubjects):
        def subjects(self):
            return [{**super().subjects()[0], "identity_status": "maybe"}]

    with pytest.raises(base.SnapshotError, match="identity_status"):
        base.assemble_snapshot(BadStatus(), Targets(), policy_version="1.0.0")


def test_engine_facing_schemas_carry_no_ice_specific_field_names():
    ice_words = re.compile(r"model_group|reg_count|reg_trend|reg_powertrain|fuel_group|id_changes|panel_id|master_version|buddhist", re.I)

    def names(node, found):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "properties":
                    found.update(value)
                if key == "enum":
                    found.update(str(v) for v in value)
                names(value, found)
        elif isinstance(node, list):
            for item in node:
                names(item, found)
        return found

    for name in ("record.schema.json", "decision.schema.json"):
        bad = {n for n in names(S.schemas()[name], set()) if ice_words.search(n)}
        assert not bad, (name, bad)


def test_policy_and_registry_do_not_name_ice_columns_or_files():
    ice_words = re.compile(r"model_group|reg_count|reg_trend|id_changes|\.csv", re.I)
    text = (S.CONTRACT_DIR / "policy.yaml").read_text(encoding="utf-8")
    keys = re.findall(r"^\s*([A-Za-z_]+):", text, re.M)
    assert not [k for k in keys if ice_words.search(k)]
    for code in S.codes():
        assert not ice_words.search(code), code


def test_the_corpus_uses_ice_only_as_data():
    providers = {c["input"]["provider"] for c in S.cases() if c["kind"] in ("resolve", "lineage") and "provider" in c["input"]}
    assert providers == {"ice"}


# ------------------------------------------------------------------------------------------------ capability data at the adapter boundary (SPEC §3.2)


def _snapshot_with(subject_series):
    class WithSeries(AcmeSubjects):
        def subjects(self):
            return [{**super().subjects()[0], "series": subject_series}]

    return WithSeries()


def test_an_adapter_that_zero_fills_an_unconfirmed_gap_fails_at_its_own_boundary():
    block = {"source": "ice", "semantics": "UNKNOWN", "confirmed": False, "months": ["2026-03"]}
    honest = {"start": "2026-01", "counts": [10, 12, None, 9], "coverage_declared": True, "absent_rows": block}
    assert base.assemble_snapshot(_snapshot_with(honest), Targets(), policy_version="1.0.0")["subjects"][0]["series"]["absent_rows"] == block
    zero_filled = {**honest, "counts": [10, 12, 0, 9]}
    with pytest.raises(base.SnapshotError, match="INPUT_ABSENT_ROW_ZERO_UNCONFIRMED"):
        base.assemble_snapshot(_snapshot_with(zero_filled), Targets(), policy_version="1.0.0")


def test_an_adapter_cannot_claim_semantics_the_contract_does_not_grant():
    claim = {"start": "2026-01", "counts": [10, 12, 0, 9], "coverage_declared": True,
             "absent_rows": {"source": "ice", "semantics": "ABSENT_IS_ZERO", "confirmed": True, "months": ["2026-03"]}}
    with pytest.raises(base.SnapshotError, match="INPUT_CAPABILITY_MISMATCH"):
        base.assemble_snapshot(_snapshot_with(claim), Targets(), policy_version="1.0.0")
    unknown_source = {**claim, "absent_rows": {"source": "acme", "semantics": "UNKNOWN", "confirmed": False, "months": ["2026-03"]}, "counts": [10, 12, None, 9]}
    with pytest.raises(base.SnapshotError, match="INPUT_CAPABILITY_MISMATCH"):
        base.assemble_snapshot(_snapshot_with(unknown_source), Targets(), policy_version="1.0.0")


def test_a_source_the_capability_file_does_not_list_has_no_confirmed_capabilities():
    assert "acme" not in S.capabilities()["sources"], "the toy provider must stay unlisted: unlisted means nothing is confirmed"
