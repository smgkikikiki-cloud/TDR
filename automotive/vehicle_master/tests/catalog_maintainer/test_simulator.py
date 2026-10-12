from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

# CI runs this suite with cwd=automotive/vehicle_master. Derive the repo root
# from this test file so root and Vehicle Master working-directory runs agree.
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from automotive.vehicle_master.catalog_maintainer.eligibility import evaluate_model
from automotive.vehicle_master.catalog_maintainer.gap_inventory import gaps_for_model
from automotive.vehicle_master.catalog_maintainer.planner import plan
from automotive.vehicle_master.catalog_maintainer.reconcile import evaluate_trim_change
from automotive.vehicle_master.catalog_maintainer.simulator import simulate
from automotive.vehicle_master.catalog_maintainer.prioritizer import registration_relevance
from automotive.vehicle_master.catalog_maintainer.validation import validate_fixture, validate_policy
from automotive.vehicle_master.catalog_maintainer.replay import replay, ReplayContractError
from automotive.vehicle_master.catalog_maintainer.retail_reconcile import reconcile_retail_lineup, validate_source_completeness
from automotive.vehicle_master.catalog_maintainer.registry_adapter import load_registry, resolve_key, RegistryDriftError
from automotive.vehicle_master.catalog_maintainer.replay_contracts import SourceDocument

ROOT = Path(__file__).parents[2] / "catalog_maintainer"


def fixture():
    return json.loads((ROOT / "fixtures" / "sample_snapshot.json").read_text())


def policy():
    return json.loads((ROOT / "contract" / "policy.yaml").read_text())


class CatalogMaintainerTests(unittest.TestCase):
    def recorded(self, name):
        return json.loads((ROOT / "fixtures" / "recorded_docs" / name).read_text(encoding="utf-8"))

    def run_replay(self, snapshot, docs):
        with tempfile.TemporaryDirectory() as temp:
            snapshot_path = Path(temp) / "snapshot.json"
            snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
            paths = []
            for index, doc in enumerate(docs):
                path = Path(temp) / f"doc-{index}.json"
                path.write_text(json.dumps(doc), encoding="utf-8")
                paths.append(path)
            out = Path(temp) / "out"
            summary = replay(snapshot_path, paths, out, root=REPOSITORY_ROOT)
            return summary, json.loads((out / "gap_diff.json").read_text()), [
                json.loads(line) for line in (out / "field_candidates.jsonl").read_text().splitlines()]

    def claim_doc(self, content, *, document_id="doc-regression"):
        doc = self.recorded("th-spec-complete.json")
        doc["document_id"] = document_id
        doc["local_source_id"] = f"fixture://{document_id}"
        doc["content"] = content
        doc["content_sha256"] = hashlib.sha256(content.encode()).hexdigest()
        return doc

    def test_replay_reconciles_canonicalized_existing_values_at_all_payload_layers(self):
        for layer, key, value in (("trim", "length_mm", 4400), ("generation", "width_mm", 1800),
                                  ("model", "height_mm", 1600)):
            with self.subTest(layer=layer):
                snap = fixture()
                snap["facts"] = [fact for fact in snap["facts"] if fact["field_key"] != key]
                owner = next(row for row in snap[{"trim":"trims", "generation":"generations", "model":"models"}[layer]]
                             if row["id"] == {"trim":"atto.standard", "generation":"atto_3.g1", "model":"byd.atto_3"}[layer])
                owner["specs"] = {key: value}
                canonical_key = {"length_mm":"vehicle.length_mm", "width_mm":"vehicle.width_mm", "height_mm":"vehicle.height_mm"}[key]
                same = self.claim_doc(f"claim|{canonical_key}|atto.standard|{value} mm")
                _, _, rows = self.run_replay(snap, [same])
                row = next(r for r in rows if r["field_key"] == canonical_key)
                self.assertEqual((row["candidate_status"], row["reason_code"]), ("HELD", "ALREADY_PRESENT"))
                conflict = self.claim_doc(f"claim|{canonical_key}|atto.standard|{value + 1} mm")
                _, _, rows = self.run_replay(snap, [conflict])
                row = next(r for r in rows if r["field_key"] == canonical_key)
                self.assertEqual((row["candidate_status"], row["reason_code"]), ("HELD", "CONFLICT_WITH_CURRENT_VALUE"))

    def test_replay_qualifiers_separate_range_facts_and_candidates(self):
        snap = fixture()
        snap["facts"] = [f for f in snap["facts"] if f["field_key"] not in {"rated_range_km", "ev.rated_range_km"}]
        snap["field_registry"].append({"key":"ev.rated_range_km","group":"electrification","tier":"P1",
                                        "applicable_powertrains":["BEV","PHEV","REEV"],
                                        "comparison_qualifiers":["measurement_basis","range_scope"]})
        for basis, scope, value in (("NEDC", "FULL", 420), ("WLTP", "FULL", 500), ("CLTC", "ELECTRIC_ONLY", 450)):
            snap["facts"].append({"trim_id":"atto.standard", "field_key":"rated_range_km", "value":value,
                                  "value_state":"KNOWN", "verification_status":"VERIFIED", "source_ref":"fixture://range",
                                  "qualifiers":{"measurement_basis":basis,"range_scope":scope}})
        docs = [self.claim_doc(f"claim|rated_range_km|atto.standard|{value} km|measurement_basis={basis};range_scope={scope}",
                               document_id=f"range-{basis}-{scope}-{value}")
                for basis, scope, value in (("NEDC", "FULL", 420), ("WLTP", "FULL", 600),
                                            ("CLTC", "ELECTRIC_ONLY", 450), ("WLTP", "ELECTRIC_ONLY", 350))]
        _, gap, rows = self.run_replay(snap, docs)
        self.assertNotIn("CONFLICT", {d["state"] for d in gap["dispositions"] if d["field_key"] == "ev.rated_range_km"})
        statuses = {(r["qualifiers"]["measurement_basis"], r["qualifiers"]["range_scope"]): (r["candidate_status"], r["reason_code"])
                    for r in rows if r["field_key"] == "ev.rated_range_km"}
        self.assertEqual(statuses[("NEDC", "FULL")], ("HELD", "ALREADY_PRESENT"))
        self.assertEqual(statuses[("WLTP", "FULL")], ("HELD", "CONFLICT_WITH_CURRENT_VALUE"))
        self.assertEqual(statuses[("CLTC", "ELECTRIC_ONLY")], ("HELD", "ALREADY_PRESENT"))
        self.assertEqual(statuses[("WLTP", "ELECTRIC_ONLY")], ("HELD", "CURRENT_VALUE_QUALIFIERS_DIFFER"))

    def test_replay_requires_explicit_units_for_dimensional_numbers(self):
        doc = self.claim_doc("claim|battery_kwh|atto.standard|60.48\nclaim|max_power_kw|atto.standard|150|output_scope=TOTAL;rating_basis=PEAK\nclaim|seats|atto.standard|5")
        _, gap, rows = self.run_replay(fixture(), [doc])
        held = {(x.get("source_field"), x["reason_code"]) for x in gap["held_or_rejected"] if x["reason_code"] == "UNIT_EVIDENCE_MISSING"}
        self.assertEqual(held, {("battery_kwh", "UNIT_EVIDENCE_MISSING"), ("max_power_kw", "UNIT_EVIDENCE_MISSING")})
        seats = next(r for r in rows if r["field_key"] == "vehicle.seats")
        self.assertNotEqual(seats.get("reason_code"), "UNIT_EVIDENCE_MISSING")
        self.assertIsNone(seats["unit"])

    def test_same_hash_with_conflicting_scope_is_held_not_deduplicated(self):
        first = self.recorded("th-spec-complete.json")
        second = copy.deepcopy(first)
        second.update(document_id="same-bytes-other-market", local_source_id="fixture://other-market", market="OTHER")
        summary, gap, rows = self.run_replay(fixture(), [first, second])
        held = [r for r in gap["held_or_rejected"] if r["reason_code"] == "DUPLICATE_HASH_METADATA_CONFLICT"]
        self.assertEqual({r["document_id"] for r in held}, {first["document_id"], second["document_id"]})
        self.assertEqual(summary["duplicate_hash_suppressions"], 0)
        self.assertEqual(rows, [])

    def test_not_available_is_not_search_exhaustion(self):
        snap = fixture()
        for variant in snap["variants"]:
            if variant["id"] == "atto.bev":
                variant["specs"].pop("battery_kwh", None)
        snap["facts"] = [f for f in snap["facts"] if not (f["trim_id"] == "atto.standard" and f["field_key"] == "battery_kwh")]
        snap["facts"].append({"trim_id":"atto.standard", "field_key":"battery_kwh", "value":None,
                              "value_state":"NOT_AVAILABLE", "verification_status":"VERIFIED"})
        result = gaps_for_model(snap, ("atto.standard",))
        states = {d["state"] for d in result["dispositions"] if d["field_key"] == "battery_kwh"}
        self.assertEqual(states, {"NOT_AVAILABLE"})
        self.assertIn("battery_kwh", result["groups"]["electrification"]["field_keys"])
        self.assertNotIn("SOURCE_EXHAUSTED", states)

    def test_replay_validates_normalized_snapshot_before_indexing(self):
        snap = fixture()
        snap["trims"].append(copy.deepcopy(snap["trims"][0]))
        with self.assertRaisesRegex(ValueError, "identifiers must be present and unique"):
            self.run_replay(snap, [self.recorded("th-spec-complete.json")])

    def test_official_thai_candidate_closes_a_genuinely_missing_p1_gap(self):
        snap = fixture()
        snap["facts"] = [f for f in snap["facts"] if not (f["trim_id"] == "atto.standard" and f["field_key"] == "length_mm")]
        for layer in (snap["trims"], snap["variants"], snap["generations"], snap["models"]):
            for row in layer:
                row.get("specs", {}).pop("length_mm", None)
        doc = self.claim_doc("claim|vehicle.length_mm|atto.standard|4455 mm", document_id="official-missing-p1")
        doc["source_authority"] = "OFFICIAL"
        summary, gap, rows = self.run_replay(snap, [doc])
        candidate = next(r for r in rows if r["field_key"] == "vehicle.length_mm")
        self.assertEqual(candidate["candidate_status"], "ACCEPTED_CANDIDATE")
        self.assertGreater(summary["priority_gap_items_before_replay"], 0)
        self.assertEqual(summary["priority_gap_items_after_replay"], summary["priority_gap_items_before_replay"] - 1)
        disposition = next(x for x in gap["dispositions"] if x["trim_id"] == "atto.standard" and x["field_key"] == "vehicle.length_mm")
        self.assertEqual(disposition["replay_state"], "CANDIDATE_PROPOSED")
        # Proposal status is not a canonical fact verification/write.
        self.assertEqual(summary["production_writes"], 0)

    def test_mixed_fact_states_are_order_independent_and_conflicting(self):
        snap = fixture()
        snap["facts"] = [f for f in snap["facts"] if not (f["trim_id"] == "atto.standard" and f["field_key"] == "length_mm")]
        mixed = [
            {"trim_id":"atto.standard","field_key":"length_mm","value":4400,"value_state":"KNOWN","verification_status":"VERIFIED"},
            {"trim_id":"atto.standard","field_key":"length_mm","value":None,"value_state":"UNKNOWN"},
        ]
        outcomes = []
        for rows in (mixed, list(reversed(mixed))):
            snap["facts"] = [f for f in snap["facts"] if not (f["trim_id"] == "atto.standard" and f["field_key"] == "length_mm")] + rows
            outcomes.append(gaps_for_model(snap, ("atto.standard",)))
        self.assertEqual(outcomes[0], outcomes[1])
        state = next(d["state"] for d in outcomes[0]["dispositions"] if d["field_key"] == "length_mm")
        self.assertEqual(state, "CONFLICT")

    def test_qualifier_review_stays_explicit_and_does_not_become_proposed(self):
        snap = fixture()
        snap["facts"] = [f for f in snap["facts"] if f["field_key"] not in {"rated_range_km", "ev.rated_range_km"}]
        snap["field_registry"].append({"key":"ev.rated_range_km","group":"electrification","tier":"P1",
                                        "applicable_powertrains":["BEV","PHEV","REEV"],
                                        "comparison_qualifiers":["measurement_basis","range_scope"]})
        snap["facts"].append({"trim_id":"atto.standard","field_key":"rated_range_km","value":420,
                              "value_state":"KNOWN","verification_status":"VERIFIED","source_ref":"fixture://range"})
        doc = self.claim_doc("claim|rated_range_km|atto.standard|420 km|measurement_basis=NEDC;range_scope=FULL")
        summary, gap, rows = self.run_replay(snap, [doc])
        disposition = next(x for x in gap["dispositions"] if x["trim_id"] == "atto.standard" and x["field_key"] == "ev.rated_range_km")
        self.assertEqual(disposition["state"], "NEEDS_QUALIFIER_REVIEW")
        self.assertEqual(disposition["replay_state"], "NEEDS_QUALIFIER_REVIEW")
        self.assertEqual(next(r for r in rows if r["field_key"] == "ev.rated_range_km")["candidate_status"], "HELD")
        self.assertEqual(summary["priority_gap_items_proposed"], 0)

    def _complete_lineup_doc(self, ids, *, model_id="byd.atto_3", generation_id="atto_3.g1",
                             captured_at="2026-10-10", edition_id="oem-edition-a",
                             capture_id="capture-a", powertrain_by_id=None,
                             model_year=None, facelift_id=None):
        doc = self.recorded("complete-lineup.json")
        doc.update(model_id=model_id, generation_id=generation_id, captured_at=captured_at,
                   published_at=min(captured_at, "2026-10-01"), source_id="synthetic-oem-th",
                   edition_id=edition_id, lineage_id="synthetic-oem-lineage")
        doc["trim_ids"] = list(ids)
        doc["capture_manifest"].update(listed_trim_ids=list(ids), row_count=len(ids),source_page_count=1)
        scope_line = (f"lineup_attestation|COMPLETE_CURRENT_THAI_RETAIL_LINEUP|model={model_id}|"
                      f"generation={generation_id}|model_year={model_year if model_year is not None else 'NONE'}|"
                      f"facelift={facelift_id if facelift_id is not None else 'NONE'}")
        lines = [f"lineup|trim|{tid}" for tid in ids]
        lines.extend([scope_line, f"capture|edition={edition_id}|capture_id={capture_id}|captured_at={captured_at}|method=LOCAL_FIXTURE_CAPTURE"])
        doc["content"] = "\n".join(lines)
        doc["content_sha256"] = hashlib.sha256(doc["content"].encode()).hexdigest()
        doc["completeness_evidence"] = {"publisher_declared_complete":True,"quote":lines[-1],
            "locator":f"line:{len(lines)-1}","capture_status":"COMPLETE","expected_page_count":1,"captured_page_count":1}
        doc["completeness_evidence"]["quote"] = scope_line
        doc["capture_provenance"] = {"capture_id":capture_id,"capture_method":"LOCAL_FIXTURE_CAPTURE",
                                      "captured_at":captured_at,"captured_page_count":1}
        doc["lineup_rows"] = []
        for tid in ids:
            t = next((x for x in fixture()["trims"] if x["id"] == tid), None)
            doc["lineup_rows"].append({"market_trim_id":tid,"model_id":model_id,
                "generation_id":generation_id,"grade":t.get("grade") if t else None,
                "powertrain":(powertrain_by_id or {}).get(tid,t["powertrain"] if t else "BEV"),
                "model_year":model_year,"facelift_id":facelift_id})
        return doc

    def test_retail_source_completeness_requires_explicit_bound_evidence(self):
        doc = self.recorded("complete-lineup.json")
        self.assertTrue(validate_source_completeness(doc)["complete"])
        incomplete = copy.deepcopy(doc)
        incomplete["capture_manifest"]["pagination_complete"] = False
        self.assertFalse(validate_source_completeness(incomplete)["complete"])
        incomplete = copy.deepcopy(doc)
        incomplete["completeness_evidence"]["quote"] = "Complete lineup"
        self.assertIn("PUBLISHER_COMPLETENESS_NOT_EVIDENCED", validate_source_completeness(incomplete)["reason_codes"])

    def test_pure_retail_reconciliation_keeps_exact_identity_and_proposes_new_trim(self):
        snap = fixture()
        doc = self._complete_lineup_doc(["atto.extended", "atto.standard", "atto.new_grade"])
        next(r for r in doc["lineup_rows"] if r["market_trim_id"] == "atto.new_grade")["grade"] = "New Grade"
        result = reconcile_retail_lineup(snap, doc, policy=policy())
        statuses = {x["market_trim_id"]:x["outcome"] for x in result["outcomes"]}
        self.assertEqual(statuses["atto.standard"], "KEEP")
        self.assertEqual(statuses["atto.new_grade"], "ADD_PROPOSAL")
        self.assertEqual(result["canonical_writes"], 0)

    def test_incomplete_lineup_never_discontinues_and_protected_set_is_reviewed(self):
        snap = fixture()
        doc = self._complete_lineup_doc(["atto.extended"])
        doc["completeness_evidence"]["capture_status"] = "PARTIAL"
        result = reconcile_retail_lineup(snap, doc, policy=policy())
        self.assertTrue(all(x["outcome"] == "HOLD" for x in result["outcomes"]))
        complete = self._complete_lineup_doc(["atto.extended"])
        result = reconcile_retail_lineup(snap, complete, policy=policy())
        protected = next(x for x in result["outcomes"] if x["market_trim_id"] == "atto.standard")
        self.assertEqual(protected["outcome"], "REVIEW")
        self.assertIn("OWNER_OR_ADMIN_PROTECTED_TRIM", protected["reason_codes"])

    def test_historical_trim_in_active_model_is_never_auto_discontinued(self):
        snap = fixture()
        doc = self._complete_lineup_doc(["city.sv"],model_id="honda.city_hatchback",generation_id="city_hb.g3",
                                        powertrain_by_id={"city.sv":"ICE"})
        result = reconcile_retail_lineup(snap, doc, policy=policy())
        old = next(x for x in result["outcomes"] if x["market_trim_id"] == "city.old")
        self.assertEqual(old["outcome"], "REVIEW")
        self.assertIn("HISTORICAL_TRIM_NOT_AUTO_RETIRED", old["reason_codes"])

    def test_identity_collision_is_review_not_fuzzy_merge(self):
        snap = fixture()
        doc = self._complete_lineup_doc(["atto.extended", "atto.standard"])
        doc["lineup_rows"][0]["grade"] = "Collision"
        result = reconcile_retail_lineup(snap, doc, policy=policy())
        row = next(x for x in result["outcomes"] if x["market_trim_id"] == "atto.extended")
        self.assertEqual(row["outcome"], "REVIEW")
        self.assertIn("CANONICAL_IDENTITY_COLLISION", row["reason_codes"])

    def test_previous_positive_then_one_negative_lineup_is_not_discontinuation(self):
        snap = fixture()
        snap["trims"].append({"id":"city.base","model_id":"honda.city_hatchback","generation_id":"city_hb.g3",
                              "status":"CURRENT","powertrain":"ICE"})
        current = self._complete_lineup_doc(["city.sv"],model_id="honda.city_hatchback",generation_id="city_hb.g3",
            captured_at="2026-10-10",edition_id="city-edition-current",capture_id="city-capture-current",
            powertrain_by_id={"city.sv":"ICE"})
        prior_positive = self._complete_lineup_doc(["city.sv","city.base"],model_id="honda.city_hatchback",
            generation_id="city_hb.g3",captured_at="2026-08-01",edition_id="city-edition-positive",
            capture_id="city-capture-positive",powertrain_by_id={"city.sv":"ICE","city.base":"ICE"})
        absent = next(x for x in reconcile_retail_lineup(snap,current,policy=policy(),
            prior_complete_documents=[prior_positive])["outcomes"] if x["market_trim_id"] == "city.base")
        self.assertEqual(absent["outcome"], "HOLD")
        self.assertEqual(absent["reason_codes"], ["ABSENCE_IN_COMPLETE_LINEUP_INSUFFICIENT"])

    def _city_discontinuation_case(self):
        snap = fixture()
        snap["trims"].append({"id":"city.base","model_id":"honda.city_hatchback","generation_id":"city_hb.g3",
                              "status":"CURRENT","powertrain":"ICE"})
        current = self._complete_lineup_doc(["city.sv"],model_id="honda.city_hatchback",generation_id="city_hb.g3",
            captured_at="2026-10-10",edition_id="city-edition-current",capture_id="city-capture-current",
            powertrain_by_id={"city.sv":"ICE"})
        older_negative = self._complete_lineup_doc(["city.sv"],model_id="honda.city_hatchback",generation_id="city_hb.g3",
            captured_at="2026-08-01",edition_id="city-edition-older",capture_id="city-capture-older",
            powertrain_by_id={"city.sv":"ICE"})
        return snap,current,older_negative

    def test_two_ordered_independent_negative_lineups_propose_soft_discontinuation(self):
        snap,current,older_negative=self._city_discontinuation_case()
        outcome=next(x for x in reconcile_retail_lineup(snap,current,policy=policy(),
            prior_complete_documents=[older_negative])["outcomes"] if x["market_trim_id"]=="city.base")
        self.assertEqual(outcome["outcome"],"SOFT_DISCONTINUE_PROPOSAL")
        self.assertTrue(outcome["soft_archive_only"])

    def test_reversed_dates_same_edition_or_same_capture_do_not_confirm_absence(self):
        for mutation in ("reversed", "same_edition", "same_capture"):
            with self.subTest(mutation=mutation):
                snap,current,old=self._city_discontinuation_case()
                if mutation=="reversed":
                    old["captured_at"]="2026-10-11"; old["published_at"]="2026-10-11"
                    old["capture_provenance"]["captured_at"]="2026-10-11"
                    old["content"]=old["content"].replace("captured=2026-08-01","captured=2026-10-11")
                    old["content_sha256"]=hashlib.sha256(old["content"].encode()).hexdigest()
                elif mutation=="same_edition":
                    old["edition_id"]=current["edition_id"]
                else:
                    old["capture_provenance"]["capture_id"]=current["capture_provenance"]["capture_id"]
                outcome=next(x for x in reconcile_retail_lineup(snap,current,policy=policy(),
                    prior_complete_documents=[old])["outcomes"] if x["market_trim_id"]=="city.base")
                self.assertEqual(outcome["outcome"],"HOLD")

    def test_two_editions_from_same_publisher_can_be_independent_negative_captures(self):
        snap,current,old=self._city_discontinuation_case()
        self.assertEqual(old["source_id"],current["source_id"])
        self.assertNotEqual(old["edition_id"],current["edition_id"])
        self.assertNotEqual(old["capture_provenance"]["capture_id"],current["capture_provenance"]["capture_id"])
        outcome=next(x for x in reconcile_retail_lineup(snap,current,policy=policy(),prior_complete_documents=[old])["outcomes"]
                     if x["market_trim_id"]=="city.base")
        self.assertEqual(outcome["outcome"],"SOFT_DISCONTINUE_PROPOSAL")

    def test_generation_model_year_and_facelift_omissions_are_out_of_scope(self):
        snap=fixture()
        snap["generations"].append({"id":"atto_3.g2","model_id":"byd.atto_3"})
        snap["trims"].append({"id":"atto.next_gen","model_id":"byd.atto_3","generation_id":"atto_3.g2",
                              "status":"CURRENT","powertrain":"BEV"})
        snap["trims"].append({"id":"atto.refresh","model_id":"byd.atto_3","generation_id":"atto_3.g1",
                              "status":"CURRENT","powertrain":"BEV","model_year":2027,"facelift_id":"refresh-27"})
        doc=self._complete_lineup_doc(["atto.extended","atto.standard"])
        result=reconcile_retail_lineup(snap,doc,policy=policy())
        states={x["market_trim_id"]:(x["outcome"],x["reason_codes"]) for x in result["outcomes"]}
        self.assertEqual(states["atto.next_gen"],("HOLD",["OUT_OF_SCOPE_GENERATION"]))
        self.assertEqual(states["atto.refresh"],("HOLD",["OUT_OF_SCOPE_MODEL_YEAR_OR_FACELIFT"]))

    def test_completeness_requires_scope_attestation_and_matching_page_counts(self):
        doc=self.recorded("complete-lineup.json")
        self.assertTrue(validate_source_completeness(doc)["complete"])
        invalid=copy.deepcopy(doc); invalid["completeness_evidence"]["expected_page_count"]=2
        self.assertIn("PAGE_COUNT_MISMATCH",validate_source_completeness(invalid)["reason_codes"])
        invalid=copy.deepcopy(doc); invalid["completeness_evidence"]["quote"]="Complete current Thai lineup"
        self.assertIn("PUBLISHER_COMPLETENESS_NOT_EVIDENCED",validate_source_completeness(invalid)["reason_codes"])
        invalid=copy.deepcopy(doc); invalid["content"]=invalid["content"].replace("COMPLETE_CURRENT_THAI_RETAIL_LINEUP","PRODUCTION_COMPLETE")
        invalid["content_sha256"]=hashlib.sha256(invalid["content"].encode()).hexdigest()
        self.assertIn("PUBLISHER_ATTESTATION_SEMANTICS_OR_SCOPE_INVALID",validate_source_completeness(invalid)["reason_codes"])

    def test_capture_independence_metadata_must_be_bound_to_exact_source_content(self):
        doc=self.recorded("complete-lineup.json")
        self.assertTrue(validate_source_completeness(doc)["complete"])
        for key, value in (("edition_id", "invented-edition"),
                           ("capture_provenance", {"capture_id":"invented-capture",
                            "capture_method":"LOCAL_FIXTURE_CAPTURE","captured_at":doc["captured_at"],
                            "captured_page_count":1})):
            invalid=copy.deepcopy(doc); invalid[key]=value
            self.assertIn("CAPTURE_PROVENANCE_NOT_BOUND_TO_CONTENT",
                          validate_source_completeness(invalid)["reason_codes"])
        invalid=copy.deepcopy(doc)
        invalid["capture_provenance"]="not-an-object"
        self.assertIn("CAPTURE_PROVENANCE_MISSING_OR_INVALID",
                      validate_source_completeness(invalid)["reason_codes"])

    def test_numeric_model_year_and_facelift_attestation_scope_matches_exact_trim(self):
        snap=fixture()
        snap["trims"].append({"id":"atto.refresh27","model_id":"byd.atto_3","generation_id":"atto_3.g1",
                              "status":"CURRENT","powertrain":"BEV","grade":"Extended",
                              "model_year":2027,"facelift_id":"refresh-27"})
        doc=self._complete_lineup_doc(["atto.refresh27"],model_year=2027,facelift_id="refresh-27")
        doc["lineup_rows"][0]["grade"]="Extended"
        self.assertTrue(validate_source_completeness(doc)["complete"])
        result=reconcile_retail_lineup(snap,doc,policy=policy())
        state=next(x for x in result["outcomes"] if x["market_trim_id"]=="atto.refresh27")
        self.assertEqual(state["outcome"],"KEEP")
        old_scope=next(x for x in result["outcomes"] if x["market_trim_id"]=="atto.standard")
        self.assertEqual(old_scope["reason_codes"],["OUT_OF_SCOPE_MODEL_YEAR_OR_FACELIFT"])

    def test_forged_model_level_lineup_metadata_cannot_unlock_spec_enrichment(self):
        snap=fixture(); model=snap["models"][2]
        model["lineup_evidence"]["source_document"]["content"] += "\nforged complete assertion"
        self.assertEqual(evaluate_model(snap,model).decision,"RETAIL_AUDIT_ONLY")
        with self.assertRaisesRegex(ValueError,"document-bound evidence"):
            validate_fixture(snap)

    def test_production_end_is_not_retail_end_of_sale(self):
        snap,current,_=self._city_discontinuation_case()
        production="production_end|model=honda.city_hatchback|trim=city.base|effective_date=2026-09-01"
        current["content"] += "\n"+production
        current["content_sha256"]=hashlib.sha256(current["content"].encode()).hexdigest()
        current["end_of_sale_evidence"]=[{"market_trim_id":"city.base","first_party_end_of_sale":True,
                                          "quote":production,"locator":"line:4"}]
        outcome=next(x for x in reconcile_retail_lineup(snap,current,policy=policy())["outcomes"]
                     if x["market_trim_id"]=="city.base")
        self.assertEqual(outcome["outcome"],"HOLD")

    def test_quote_bound_explicit_retail_sale_end_is_proposal_only(self):
        snap,current,_=self._city_discontinuation_case()
        line="retail_end_of_sale|market=TH|model=honda.city_hatchback|generation=city_hb.g3|trim=city.base|model_year=NONE|facelift=NONE|effective_date=2026-09-01"
        current["content"] += "\n"+line
        current["content_sha256"]=hashlib.sha256(current["content"].encode()).hexdigest()
        current["end_of_sale_evidence"]=[{"event_type":"RETAIL_SALE_ENDED","market_trim_id":"city.base",
            "model_id":"honda.city_hatchback","generation_id":"city_hb.g3","effective_date":"2026-09-01",
            "quote":line,"locator":"line:4"}]
        outcome=next(x for x in reconcile_retail_lineup(snap,current,policy=policy())["outcomes"]
                     if x["market_trim_id"]=="city.base")
        self.assertEqual(outcome["outcome"],"SOFT_DISCONTINUE_PROPOSAL")

    def test_structural_interval_is_validated_policy_and_reported_pending_approval(self):
        snap,current,old=self._city_discontinuation_case()
        p=policy(); p["structural_evidence"]["minimum_independent_negative_interval_days"]=90
        result=reconcile_retail_lineup(snap,current,policy=p,prior_complete_documents=[old])
        outcome=next(x for x in result["outcomes"] if x["market_trim_id"]=="city.base")
        self.assertEqual(outcome["outcome"],"HOLD")
        self.assertEqual(result["evidence_policy"],{"approval_status":"PENDING_OWNER_APPROVAL",
            "minimum_independent_negative_interval_days":90})
        p["structural_evidence"]["approval_status"]="APPROVED"
        with self.assertRaisesRegex(ValueError,"PENDING_OWNER_APPROVAL"):
            validate_policy(p)
        p=policy(); p["structural_evidence"]["minimum_independent_negative_interval_days"]=90
        p["structural_evidence"]["minimum_interval_constraints"]["maximum_days"]=60
        with self.assertRaisesRegex(ValueError,"structural_evidence interval"):
            validate_policy(p)

    def test_normalized_complete_lineup_contract_requires_document_binding(self):
        snap = fixture()
        validate_fixture(snap)
        snap["models"][2]["lineup_evidence"].pop("source_document")
        self.assertEqual(evaluate_model(snap,snap["models"][2]).decision,"RETAIL_AUDIT_ONLY")
        with self.assertRaisesRegex(ValueError, "document-bound evidence"):
            validate_fixture(snap)

    def test_canonical_registry_adapter_is_pinned_and_aliases_are_canonical(self):
        registry = load_registry(root=REPOSITORY_ROOT)
        self.assertEqual(registry["schema_version"], 1)
        self.assertEqual(registry["registry_sha256"], "dff3100caec596fa6911f25b622f1cce65b3ffa6247bf5ce1e6d133acd5f419c")
        self.assertEqual(registry["editor_sha256"], "31ce6feef19e1b477f8fa28ff9ca4d9afff32d7ae0c436aa56404063afba6f8b")
        self.assertEqual(resolve_key("engine_cc", registry), "engine.displacement_cc")
        self.assertEqual(resolve_key("battery_kwh", registry), "battery.catalog_capacity_kwh")
        self.assertEqual(registry["fields"]["ev.rated_range_km"]["comparison_qualifiers"], ["measurement_basis", "range_scope"])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "automotive/vehicle_master/vehreg/data/2026/product/comparable_specs/registry.json"
            target.parent.mkdir(parents=True)
            target.write_text("{}")
            with self.assertRaisesRegex(RegistryDriftError, "checksum drift"):
                load_registry(root=root)

    def test_replay_accepts_exact_trim_evidence_without_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "out"
            summary = replay(ROOT / "fixtures/sample_snapshot.json",
                             [ROOT / "fixtures/recorded_docs/th-spec-complete.json"], out,
                             root=REPOSITORY_ROOT)
            rows = [json.loads(line) for line in (out / "field_candidates.jsonl").read_text().splitlines()]
            self.assertEqual(summary["accepted_candidates"], 3)
            self.assertEqual(summary["proposed_canonical_writes"], 0)
            self.assertEqual(summary["paid_model_calls"], 0)
            self.assertEqual({r["field_key"] for r in rows}, {"battery.catalog_capacity_kwh", "ev.rated_range_km", "powertrain.max_power_kw", "safety.aeb"})
            battery = next(r for r in rows if r["field_key"] == "battery.catalog_capacity_kwh")
            self.assertEqual((battery["candidate_status"], battery["reason_code"]), ("HELD", "ALREADY_PRESENT"))
            self.assertEqual(sum(r["candidate_status"] == "ACCEPTED_CANDIDATE" for r in rows), 3)
            self.assertEqual(summary["applicable_gaps_after_replay"], summary["applicable_gaps_before"])
            self.assertEqual(next(r for r in rows if r["field_key"] == "ev.rated_range_km")["locator"], "line:2")

    def test_replay_rejects_forged_hash_invalid_contract_and_bad_lineage(self):
        forged = self.recorded("th-spec-complete.json")
        forged["content"] += "\nclaim|battery_kwh|atto.standard|70 kWh"
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "forged.json"
            p.write_text(json.dumps(forged))
            with self.assertRaisesRegex(ReplayContractError, "content hash mismatch"):
                replay(ROOT / "fixtures/sample_snapshot.json", [p], Path(temp) / "out", root=REPOSITORY_ROOT)
        for name, reason in (("wrong-market.json", "WRONG_MARKET"), ("wrong-trim.json", "TRIM_MISMATCH"),
                             ("wrong-powertrain.json", "POWERTRAIN_NOT_APPLICABLE"),
                             ("wrong-variant.json", "VARIANT_MISMATCH"), ("old-spec.json", "SOURCE_STALE")):
            with tempfile.TemporaryDirectory() as temp:
                out = Path(temp) / "out"
                replay(ROOT / "fixtures/sample_snapshot.json", [ROOT / "fixtures/recorded_docs" / name], out,
                       root=REPOSITORY_ROOT)
                gap = json.loads((out / "gap_diff.json").read_text())
                self.assertIn(reason, {x["reason_code"] for x in gap["held_or_rejected"]})
        wrong_year = self.recorded("th-spec-complete.json")
        wrong_year["model_year_by_trim"] = {"atto.standard": 2026}
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "year.json"; p.write_text(json.dumps(wrong_year))
            out = Path(temp) / "out"
            replay(ROOT / "fixtures/sample_snapshot.json", [p], out, root=REPOSITORY_ROOT)
            gap = json.loads((out / "gap_diff.json").read_text())
            self.assertIn("MODEL_YEAR_UNRESOLVED", {x["reason_code"] for x in gap["held_or_rejected"]})
        wrong_generation = self.recorded("th-spec-complete.json")
        wrong_generation["generation_id"] = "city_hb.g3"
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "generation.json"; p.write_text(json.dumps(wrong_generation))
            out = Path(temp) / "out"
            replay(ROOT / "fixtures/sample_snapshot.json", [p], out, root=REPOSITORY_ROOT)
            gap = json.loads((out / "gap_diff.json").read_text())
            self.assertIn("MODEL_GENERATION_MISMATCH", {x["reason_code"] for x in gap["held_or_rejected"]})
        bad = self.recorded("th-spec-complete.json"); bad.pop("local_source_id")
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "bad.json"; p.write_text(json.dumps(bad))
            with self.assertRaisesRegex(ReplayContractError, "missing keys"):
                replay(ROOT / "fixtures/sample_snapshot.json", [p], Path(temp) / "out", root=REPOSITORY_ROOT)

    def test_partial_lineup_and_unverified_trim_never_unlock_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "out"
            replay(ROOT / "fixtures/sample_snapshot.json", [ROOT / "fixtures/recorded_docs/partial-lineup.json"], out,
                   root=REPOSITORY_ROOT)
            gap = json.loads((out / "gap_diff.json").read_text())
            self.assertIn("TRIM_NOT_EXPLICITLY_ADMITTED", {x["reason_code"] for x in gap["held_or_rejected"]})
            self.assertEqual(json.loads((out / "field_candidates.jsonl").read_text() or "{}"), {})
        complete = self.recorded("complete-lineup.json")
        self.assertEqual(complete["capture_manifest"]["listed_trim_ids"], ["atto.extended", "atto.standard"])
        self.assertEqual(set(complete["trim_ids"]), set(complete["capture_manifest"]["listed_trim_ids"]))
        forged = copy.deepcopy(complete)
        forged["capture_manifest"]["pagination_complete"] = False
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "false-complete.json"; p.write_text(json.dumps(forged))
            with self.assertRaisesRegex(ReplayContractError, "COMPLETE_LINEUP requires"):
                replay(ROOT / "fixtures/sample_snapshot.json", [p], Path(temp) / "out", root=REPOSITORY_ROOT)

    def test_replay_known_provisional_trace_match_and_locked_tombstone_hold(self):
        snap = fixture()
        snap["facts"] = [f for f in snap["facts"] if not (f["trim_id"] == "atto.standard" and f["field_key"] == "length_mm")]
        snap["facts"].append({"trim_id":"atto.standard","field_key":"length_mm","value":4400,
                              "value_state":"KNOWN","verification_status":"PROVISIONAL","source_ref":"fixture://provisional"})
        doc = self.recorded("th-spec-complete.json")
        doc["document_id"] = "doc-trace-and-tombstone"
        doc["content"] = "claim|length_mm|atto.standard|4400 mm\nclaim|seats|atto.standard|5 seat"
        doc["content_sha256"] = hashlib.sha256(doc["content"].encode()).hexdigest()
        with tempfile.TemporaryDirectory() as temp:
            snap_path, doc_path = Path(temp)/"snapshot.json", Path(temp)/"doc.json"
            snap_path.write_text(json.dumps(snap)); doc_path.write_text(json.dumps(doc))
            out = Path(temp)/"out"
            replay(snap_path,[doc_path],out,root=REPOSITORY_ROOT)
            rows = [json.loads(line) for line in (out/"field_candidates.jsonl").read_text().splitlines()]
            by_key = {r["field_key"]: r for r in rows}
            self.assertEqual((by_key["vehicle.length_mm"]["candidate_status"], by_key["vehicle.length_mm"]["reason_code"]),
                             ("ACCEPTED_CANDIDATE", "SOURCE_TRACE_MATCHED"))
            self.assertEqual((by_key["vehicle.seats"]["candidate_status"], by_key["vehicle.seats"]["reason_code"]),
                             ("HELD", "ADMIN_LOCKED_TOMBSTONE"))

    def test_range_basis_and_scope_are_distinct_and_p3_price_are_not_retrieval_fields(self):
        nedc = self.recorded("th-spec-complete.json")
        wltp = copy.deepcopy(nedc)
        wltp["document_id"] = "doc-wltp-electric-only"
        wltp["local_source_id"] = "fixture://doc-wltp-electric-only"
        wltp["content"] = "claim|rated_range_km|atto.standard|310 km|measurement_basis=WLTP;range_scope=ELECTRIC_ONLY"
        wltp["content_sha256"] = hashlib.sha256(wltp["content"].encode()).hexdigest()
        p3 = copy.deepcopy(nedc)
        p3["document_id"] = "doc-p3-price"
        p3["local_source_id"] = "fixture://doc-p3-price"
        p3["content"] = "claim|wheel_size|atto.standard|18 inch\nclaim|LIST_PRICE|atto.standard|1200000 THB"
        p3["content_sha256"] = hashlib.sha256(p3["content"].encode()).hexdigest()
        with tempfile.TemporaryDirectory() as temp:
            wpath, ppath = Path(temp) / "wltp.json", Path(temp) / "p3.json"
            wpath.write_text(json.dumps(wltp)); ppath.write_text(json.dumps(p3))
            out = Path(temp) / "out"
            replay(ROOT / "fixtures/sample_snapshot.json", [ROOT / "fixtures/recorded_docs/th-spec-complete.json", wpath, ppath],
                   out, root=REPOSITORY_ROOT)
            rows = [json.loads(line) for line in (out / "field_candidates.jsonl").read_text().splitlines()]
            ranges = [r for r in rows if r["field_key"] == "ev.rated_range_km"]
            self.assertEqual({(r["qualifiers"]["measurement_basis"], r["qualifiers"]["range_scope"]) for r in ranges},
                             {("NEDC", "FULL"), ("WLTP", "ELECTRIC_ONLY")})
            self.assertNotIn("wheel_size", {r["field_key"] for r in rows})
            self.assertNotIn("LIST_PRICE", {r["field_key"] for r in rows})
            diff = json.loads((out / "gap_diff.json").read_text())
            out_rows = [r for r in diff["dispositions"] if r["state"] == "OUT_OF_SCOPE"]
            self.assertIn(("wheel_size", "P3_NO_STANDALONE_RETRIEVAL"), {(r["field_key"], r["reason_code"]) for r in out_rows})
            self.assertIn(("LIST_PRICE", "PRICE_LEDGER_OWNED"), {(r["field_key"], r["reason_code"]) for r in out_rows})

    def test_replay_gap_adapter_preserves_fact_states_and_out_of_scope_semantics(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "out"
            replay(ROOT / "fixtures/sample_snapshot.json", [ROOT / "fixtures/recorded_docs/th-spec-complete.json"], out,
                   root=REPOSITORY_ROOT)
            diff = json.loads((out / "gap_diff.json").read_text())
            states = {(r["trim_id"], r["field_key"], r["state"]) for r in diff["dispositions"]}
            self.assertIn(("atto.standard", "vehicle.length_mm", "UNKNOWN"), states)
            self.assertIn(("atto.standard", "vehicle.seats", "TOMBSTONED_LOCKED"), states)
            self.assertIn(("atto.standard", "battery.catalog_capacity_kwh", "ALREADY_KNOWN"), states)
            self.assertIn(("atto.extended", "battery.catalog_capacity_kwh", "ALREADY_KNOWN"), states)
            self.assertIn(("city.sv", "engine.displacement_cc", "TOMBSTONED_LOCKED"), states)
            self.assertIn(("atto.standard", "drive_type", "OUT_OF_SCOPE"), states)

    def test_documents_from_same_lineage_do_not_count_as_independent(self):
        first = self.recorded("th-spec-complete.json")
        second = copy.deepcopy(first)
        second["document_id"] = "doc-second-capture-same-release"
        second["local_source_id"] = "fixture://second-capture"
        second["content"] = "reformatted copy of the same release\n" + first["content"].splitlines()[2]
        second["content_sha256"] = hashlib.sha256(second["content"].encode()).hexdigest()
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "same-lineage.json"; p.write_text(json.dumps(second))
            out = Path(temp) / "out"
            replay(ROOT / "fixtures/sample_snapshot.json", [ROOT / "fixtures/recorded_docs/th-spec-complete.json", p], out,
                   root=REPOSITORY_ROOT)
            summary = json.loads((out / "replay_summary.json").read_text())
            rows = [json.loads(line) for line in (out / "field_candidates.jsonl").read_text().splitlines()]
            powers = [r for r in rows if r["field_key"] == "powertrain.max_power_kw"]
            self.assertEqual(summary["lineage_independent_source_count"], 1)
            self.assertEqual(sum(r["candidate_status"] == "ACCEPTED_CANDIDATE" for r in powers), 1)
            self.assertEqual(sum(r.get("reason_code") == "DUPLICATE_LINEAGE_CLAIM" for r in powers), 1)

    def test_replay_range_basis_scope_units_and_source_conflicts_are_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "out"
            replay(ROOT / "fixtures/sample_snapshot.json", [ROOT / "fixtures/recorded_docs/misleading-range.json"], out,
                   root=REPOSITORY_ROOT)
            gap = json.loads((out / "gap_diff.json").read_text())
            self.assertIn("MISSING_MEASUREMENT_QUALIFIER", {x["reason_code"] for x in gap["held_or_rejected"]})
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "out"
            replay(ROOT / "fixtures/sample_snapshot.json", [ROOT / "fixtures/recorded_docs/wrong-unit.json"], out,
                   root=REPOSITORY_ROOT)
            gap = json.loads((out / "gap_diff.json").read_text())
            self.assertIn("UNIT_MISMATCH", {x["reason_code"] for x in gap["held_or_rejected"]})
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "out"
            replay(ROOT / "fixtures/sample_snapshot.json",
                   [ROOT / "fixtures/recorded_docs/th-spec-complete.json", ROOT / "fixtures/recorded_docs/conflict.json"],
                   out, root=REPOSITORY_ROOT)
            rows = [json.loads(line) for line in (out / "field_candidates.jsonl").read_text().splitlines()]
            battery = [r for r in rows if r["field_key"] == "battery.catalog_capacity_kwh"]
            self.assertEqual(len(battery), 2)
            self.assertTrue(all(r["candidate_status"] == "HELD" and r["reason_code"] == "CONFLICTING_SOURCE_VALUES" for r in battery))

    def test_replay_duplicate_hash_lineage_and_byte_stability(self):
        doc = self.recorded("th-spec-complete.json")
        duplicate = copy.deepcopy(doc); duplicate["document_id"] = "same-hash-copy"
        duplicate["local_source_id"] = "fixture://copy"
        with tempfile.TemporaryDirectory() as temp:
            a, b = Path(temp) / "a", Path(temp) / "b"
            source = Path(temp) / "duplicate.json"; source.write_text(json.dumps(duplicate))
            replay(ROOT / "fixtures/sample_snapshot.json", [ROOT / "fixtures/recorded_docs/th-spec-complete.json", source], a,
                   root=REPOSITORY_ROOT)
            replay(ROOT / "fixtures/sample_snapshot.json", [source, ROOT / "fixtures/recorded_docs/th-spec-complete.json"], b,
                   root=REPOSITORY_ROOT)
            self.assertEqual({p.name:p.read_bytes() for p in a.iterdir()}, {p.name:p.read_bytes() for p in b.iterdir()})
            summary = json.loads((a / "replay_summary.json").read_text())
            self.assertEqual(summary["duplicate_hash_suppressions"], 1)

    def test_eligibility_scope_and_two_queues(self):
        snap = fixture()
        statuses = {r["model_id"]: r["eligibility"] for r in plan(snap, policy())["decisions"]}
        self.assertEqual(statuses["toyota.yaris_ativ"], "RETAIL_AUDIT_ONLY")
        self.assertEqual(statuses["byd.atto_3"], "ELIGIBLE_ENRICH")
        self.assertEqual(statuses["legacy.example"], "EXCLUDED_HISTORICAL")
        self.assertEqual(statuses["upcoming.example"], "EXCLUDED_UPCOMING")
        self.assertEqual(statuses["discovered.example"], "EXCLUDED_DISCOVERED")
        queue = plan(snap, policy())["queue"]
        self.assertEqual({r["work_kind"] for r in queue}, {"RETAIL_AUDIT", "SPEC_ENRICH"})
        self.assertEqual({r["model_id"] for r in queue}, {"toyota.yaris_ativ", "byd.atto_3", "honda.city_hatchback"})

    def test_owner_set_membership_beats_trim_status_and_observation(self):
        snap = fixture()
        snap["trims"].append({"id":"atto.not_in_set","model_id":"byd.atto_3","generation_id":"atto_3.g1","status":"CURRENT","powertrain":"BEV"})
        atto = next(m for m in snap["models"] if m["id"] == "byd.atto_3")
        atto["observed_current_trim_ids"] = ["atto.extended", "new.unapproved"]
        row = evaluate_model(snap, atto)
        self.assertEqual(row.decision, "ELIGIBLE_ENRICH")
        self.assertEqual(row.admitted_trim_ids, ("atto.extended", "atto.standard"))
        self.assertIn("OWNER_SET_CONFLICT_REVIEW_REQUIRED", row.reasons)
        decision = next(x for x in plan(snap, policy())["decisions"] if x["model_id"] == "byd.atto_3")
        self.assertTrue(decision["review_required"])
        self.assertIn({"trim_id":"atto.not_in_set","decision":"EXCLUDED_NON_MEMBER","reason_code":"NOT_IN_OWNER_SET"}, decision["trim_decisions"])

    def test_unknown_not_applicable_payload_dedupe_and_tombstone(self):
        snap = fixture()
        result = gaps_for_model(snap, ("atto.extended", "atto.standard"))
        flattened = {key for group in result["groups"].values() for key in group["field_keys"]}
        self.assertNotIn("battery_kwh", flattened)  # KNOWN fact/payload already contain it
        self.assertNotIn("engine_cc", flattened)  # not applicable to BEV
        self.assertNotIn("wheel_size", flattened)  # P3 has no independent research
        self.assertIn("length_mm", flattened)
        states = {(d["field_key"], d["state"]) for d in result["dispositions"]}
        self.assertIn(("engine_cc", "NOT_APPLICABLE"), states)
        self.assertIn(("length_mm", "UNKNOWN"), states)
        self.assertIn(("drive_type", "ALREADY_KNOWN"), states)
        self.assertIn(("seats", "TOMBSTONED_LOCKED"), states)
        city = gaps_for_model(snap, ("city.sv",))
        city_states = {(d["field_key"],d["state"]) for d in city["dispositions"]}
        self.assertIn(("engine_cc", "TOMBSTONED_LOCKED"), city_states)
        self.assertIn(("length_mm", "CONFLICT"), city_states)

    def test_value_state_is_not_verification_status_and_na_is_preserved(self):
        snap = fixture()
        result = gaps_for_model(snap, ("atto.standard",))
        states = {(d["field_key"],d["state"]) for d in result["dispositions"]}
        self.assertIn(("length_mm","UNKNOWN"), states)  # VERIFIED does not promote UNKNOWN to KNOWN
        self.assertIn("length_mm", result["groups"]["dimensions"]["field_keys_by_tier"]["P1"])
        self.assertNotIn("engine_cc", result["groups"].get("powertrain", {}).get("field_keys", []))
        snap["facts"].append({"trim_id":"atto.standard","field_key":"battery_kwh","value_state":"NOT_APPLICABLE","value":None,"locked":False})
        snap["facts"].append({"trim_id":"city.sv","field_key":"aeb","value_state":"NOT_APPLICABLE","value":None,"locked":False})
        result = gaps_for_model(snap, ("atto.standard",))
        states = {(d["trim_id"],d["field_key"],d["state"]) for d in result["dispositions"]}
        self.assertIn(("atto.standard","battery_kwh","CONFLICT"), states)  # explicit NA conflicts with payload value
        result = gaps_for_model(snap, ("city.sv",))
        self.assertIn(("city.sv","aeb","NOT_APPLICABLE"), {(d["trim_id"],d["field_key"],d["state"]) for d in result["dispositions"]})

    def test_mixed_powertrains_and_mixed_tiers_stay_distinct_in_one_bundle(self):
        snap = fixture()
        snap["models"].append({"id":"mix.hybrid_line","status":"CURRENT","business_relevance":0.6})
        snap["generations"].append({"id":"mix.g1","model_id":"mix.hybrid_line"})
        snap["trims"].extend([
            {"id":"mix.ice","model_id":"mix.hybrid_line","generation_id":"mix.g1","status":"CURRENT","powertrain":"ICE"},
            {"id":"mix.hev","model_id":"mix.hybrid_line","generation_id":"mix.g1","status":"CURRENT","powertrain":"HEV"},
        ])
        snap["current_retail_sets"].append({"model_id":"mix.hybrid_line","trim_ids":["mix.ice","mix.hev"]})
        gaps = gaps_for_model(snap, ("mix.ice","mix.hev"))
        powertrain = gaps["groups"]["powertrain"]
        self.assertEqual(powertrain["tiers"], ["P1","P2"])
        self.assertIn("engine_cc", powertrain["field_keys_by_tier"]["P1"])
        self.assertIn("torque_nm", powertrain["field_keys_by_tier"]["P2"])
        na = {(d["trim_id"],d["field_key"],d["state"]) for d in gaps["dispositions"]}
        self.assertIn(("mix.ice","battery_kwh","NOT_APPLICABLE"), na)
        self.assertIn(("mix.hev","battery_kwh","NOT_APPLICABLE"), na)
        job = next(x for x in plan(snap,policy())["queues"]["SPEC_ENRICH"] if x["model_id"] == "mix.hybrid_line")
        self.assertEqual(job["tier"], "P1")
        self.assertEqual(job["field_plan"]["powertrain"]["tiers"], ["P1","P2"])

    def test_owner_set_historical_unverified_and_retired_conflicts_never_enrich(self):
        snap = fixture()
        atto = next(m for m in snap["models"] if m["id"] == "byd.atto_3")
        snap["trims"].extend([
            {"id":"atto.old","model_id":"byd.atto_3","generation_id":"atto_3.g1","status":"HISTORICAL","powertrain":"BEV"},
            {"id":"atto.unverified","model_id":"byd.atto_3","generation_id":"atto_3.g1","status":"UNVERIFIED","powertrain":"BEV"},
            {"id":"atto.retired","model_id":"byd.atto_3","generation_id":"atto_3.g1","status":"CURRENT","owner_retired":True,"powertrain":"BEV"},
        ])
        snap["current_retail_sets"][0]["trim_ids"].extend(["atto.old","atto.unverified","atto.retired"])
        result = evaluate_model(snap, atto)
        self.assertNotIn("atto.old", result.admitted_trim_ids)
        self.assertNotIn("atto.unverified", result.admitted_trim_ids)
        self.assertNotIn("atto.retired", result.admitted_trim_ids)
        self.assertEqual(set(result.conflicting_trim_ids), {"atto.old","atto.unverified","atto.retired"})
        decisions = next(x for x in plan(snap,policy())["decisions"] if x["model_id"] == atto["id"])
        self.assertTrue(decisions["review_required"])
        by_id = {x["trim_id"]:x for x in decisions["trim_decisions"]}
        self.assertEqual(by_id["atto.old"]["reason_code"], "OWNER_SET_HISTORICAL_CONFLICT")
        self.assertEqual(by_id["atto.unverified"]["reason_code"], "OWNER_SET_UNVERIFIED_CONFLICT")
        self.assertEqual(by_id["atto.retired"]["reason_code"], "OWNER_SET_RETIRED_CONFLICT")

    def test_partial_or_incomplete_lineup_cannot_unlock_specs(self):
        snap = fixture()
        yaris = next(m for m in snap["models"] if m["id"] == "toyota.yaris_ativ")
        self.assertEqual(evaluate_model(snap,yaris).decision,"RETAIL_AUDIT_ONLY")
        yaris["lineup_evidence"]["completeness"] = "INDIVIDUAL_TRIM"
        self.assertEqual(evaluate_model(snap,yaris).decision,"RETAIL_AUDIT_ONLY")

    def test_ry1_ry3_scoring_selects_one_series_and_ignores_star_aggregate(self):
        snap = fixture()
        scores = registration_relevance(snap["models"],snap["registration_signals"])
        self.assertEqual(scores["toyota.yaris_ativ"],1.0)
        self.assertEqual(scores["byd.atto_3"],1.0)
        self.assertLess(scores["honda.city_hatchback"],1.0)

    def test_historical_trim_under_active_model_is_not_enriched(self):
        result = plan(fixture(), policy())
        city = next(x for x in result["decisions"] if x["model_id"] == "honda.city_hatchback")
        old = next(x for x in city["trim_decisions"] if x["trim_id"] == "city.old")
        self.assertEqual(old["decision"], "EXCLUDED_HISTORICAL")
        city_job = next(x for x in result["queues"]["SPEC_ENRICH"] if x["model_id"] == "honda.city_hatchback")
        planned_ids = {tid for group in city_job["field_plan"].values() for ids in group["trim_ids_by_field"].values() for tid in ids}
        self.assertNotIn("city.old", planned_ids)

    def test_registration_changes_score_not_decision(self):
        snap = fixture()
        before = {r["model_id"]: r["eligibility"] for r in plan(snap, policy())["decisions"]}
        changed = copy.deepcopy(snap)
        changed["registration_signals"] = [{"model_id":"toyota.yaris_ativ","series":"RY1","stratum":"passenger","source_class":"MODEL","period":"2026-08","count":1}]
        after = {r["model_id"]: r["eligibility"] for r in plan(changed, policy())["decisions"]}
        self.assertEqual(before, after)
        self.assertTrue(all(not item["registration_is_evidence"] for item in plan(changed, policy())["queue"]))

    def test_audit_anti_starvation_reserves_configured_cohort_slot(self):
        snap = fixture()
        for i in range(5):
            mid = f"ordinary.{i}"
            snap["models"].append({"id":mid,"status":"CURRENT","staleness_risk":1,"lineup_recency":1,"document_reuse":1})
            snap["generations"].append({"id":f"{mid}.g1","model_id":mid})
        snap["models"].append({"id":"cohort.low","status":"CURRENT","priority_cohort":"UNDERREPRESENTED"})
        snap["generations"].append({"id":"cohort.low.g1","model_id":"cohort.low"})
        audits = [x["model_id"] for x in plan(snap, policy())["queue"] if x["work_kind"] == "RETAIL_AUDIT"]
        self.assertEqual(audits[4], "cohort.low")

    def test_zero_budget_is_empty(self):
        result = plan(fixture(), policy(), budget=0)
        self.assertEqual(result["queue"], [])
        self.assertEqual(result["summary"]["planned_items"], 0)

    def test_independent_queue_budget_prevents_audit_backlog_starving_spec(self):
        snap=fixture()
        for i in range(12):
            mid=f"audit.backlog_{i:02d}"
            snap["models"].append({"id":mid,"status":"CURRENT","staleness_risk":1})
            snap["generations"].append({"id":f"{mid}.g1","model_id":mid})
        result=plan(snap,policy(),budget=3)
        self.assertEqual(len(result["queues"]["RETAIL_AUDIT"]),3)
        self.assertEqual(len(result["queues"]["SPEC_ENRICH"]),2)
        self.assertEqual({x["work_kind"] for x in result["queue"]},{"RETAIL_AUDIT","SPEC_ENRICH"})

    def test_policy_parameters_control_scoring_and_validate(self):
        snap=fixture(); p=policy()
        score=lambda pol: next(x["score"] for x in plan(snap,pol)["queues"]["RETAIL_AUDIT"] if x["model_id"]=="toyota.yaris_ativ")
        self.assertEqual(score(p),0.845)
        p["priority_policy"]["audit_weights"]={"registration_relevance":0,"catalog_staleness":1,"lineup_recency":0,"document_reuse":0}
        self.assertEqual(score(p),0.8)
        p["priority_policy"]["audit_weights"]["document_reuse"]=0.5
        with self.assertRaisesRegex(ValueError,"summing to 1"):
            validate_policy(p)

    def test_job_key_ignores_unrelated_snapshot_changes(self):
        snap=fixture()
        get_key=lambda s: next(x["job_key"] for x in plan(s,policy())["queues"]["SPEC_ENRICH"] if x["model_id"]=="byd.atto_3")
        first=get_key(snap)
        changed=copy.deepcopy(snap)
        changed["models"].append({"id":"unrelated.current","status":"CURRENT"})
        changed["generations"].append({"id":"unrelated.g1","model_id":"unrelated.current"})
        changed["facts"].append({"trim_id":"city.sv","field_key":"unrelated","value_state":"KNOWN","value":"x"})
        self.assertEqual(first,get_key(changed))

    def test_fixture_contract_validation_rejects_bad_values(self):
        snap=fixture(); validate_fixture(snap)
        broken=copy.deepcopy(snap)
        broken["facts"].append({"trim_id":"atto.standard","field_key":"x","value_state":"BAD"})
        with self.assertRaisesRegex(ValueError,"value_state"):
            validate_fixture(broken)

    def test_unsafe_policy_fails_closed(self):
        p = policy()
        p["autonomy"]["allow_external_http"] = True
        with self.assertRaisesRegex(ValueError, "must remain false"):
            plan(fixture(), p)

    def test_structural_add_and_discontinue_proposals_only(self):
        add = evaluate_trim_change("ADD_TRIM", model_current=True, generation_exists=True,
                                   exact_thai_grade=True, exact_powertrain=True,
                                   corroborated_official=True)
        self.assertEqual(add["proposal"], "PROPOSE_ADD_TRIM")
        blocked = evaluate_trim_change("ADD_TRIM", model_current=True, generation_exists=True)
        self.assertEqual(blocked["proposal"], "REVIEW")
        dis = evaluate_trim_change("DISCONTINUE_TRIM", model_current=True, generation_exists=True,
                                   previously_confirmed_current=True, snapshots_independent=True,
                                   complete_snapshots_days_apart=7)
        self.assertEqual(dis["proposal"], "PROPOSE_DISCONTINUE_TRIM")
        self.assertTrue(dis["soft_archive_only"])
        conflict = evaluate_trim_change("DISCONTINUE_TRIM", model_current=True, generation_exists=True,
                                        previously_confirmed_current=True, explicit_end_of_sale=True,
                                        owner_set_protected=True)
        self.assertEqual(conflict["proposal"], "REVIEW")

    def test_output_replay_is_byte_stable(self):
        with tempfile.TemporaryDirectory() as temp:
            a, b = Path(temp) / "a", Path(temp) / "b"
            simulate(ROOT / "fixtures" / "sample_snapshot.json", a)
            simulate(ROOT / "fixtures" / "sample_snapshot.json", b)
            self.assertEqual({p.name:p.read_bytes() for p in a.iterdir()}, {p.name:p.read_bytes() for p in b.iterdir()})

    def test_simulator_has_no_network_database_or_provider_imports(self):
        source = "\n".join(p.read_text() for p in ROOT.rglob("*.py") if p.name != "__init__.py")
        for forbidden in ("import requests", "import httpx", "urllib.request", "import supabase",
                          "import openai", "import anthropic"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
