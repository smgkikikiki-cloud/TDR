from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from automotive.vehicle_master.catalog_maintainer.eligibility import evaluate_model
from automotive.vehicle_master.catalog_maintainer.gap_inventory import gaps_for_model
from automotive.vehicle_master.catalog_maintainer.planner import plan
from automotive.vehicle_master.catalog_maintainer.reconcile import evaluate_trim_change
from automotive.vehicle_master.catalog_maintainer.simulator import simulate

ROOT = Path(__file__).parents[2] / "catalog_maintainer"


def fixture():
    return json.loads((ROOT / "fixtures" / "sample_snapshot.json").read_text())


def policy():
    return json.loads((ROOT / "contract" / "policy.yaml").read_text())


class CatalogMaintainerTests(unittest.TestCase):
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
        snap["models"][1]["observed_current_trim_ids"] = ["atto.extended", "new.unapproved"]
        snap["trims"].append({"id":"atto.not_in_set","model_id":"byd.atto_3","generation_id":"atto_3.g1","status":"CURRENT","powertrain":"BEV"})
        row = evaluate_model(snap, snap["models"][1])
        self.assertEqual(row.decision, "ELIGIBLE_ENRICH")
        self.assertEqual(row.admitted_trim_ids, ("atto.extended", "atto.standard"))
        self.assertIn("OWNER_SET_CONFLICT_REVIEW_REQUIRED", row.reasons)
        decision = next(x for x in plan(snap, policy())["decisions"] if x["model_id"] == "byd.atto_3")
        self.assertTrue(decision["review_required"])
        self.assertIn({"trim_id":"atto.not_in_set","decision":"EXCLUDED_NON_MEMBER"}, decision["trim_decisions"])

    def test_unknown_not_applicable_payload_dedupe_and_tombstone(self):
        snap = fixture()
        result = gaps_for_model(snap, ("atto.extended", "atto.standard"))
        flattened = {key for group in result["groups"].values() for key in group["field_keys"]}
        self.assertNotIn("battery_kwh", flattened)  # fact and variant payload already contain it
        self.assertNotIn("engine_cc", flattened)  # not applicable to BEV
        self.assertNotIn("wheel_size", flattened)  # P3 has no independent research
        self.assertIn("length_mm", flattened)
        states = {(d["field_key"], d["state"]) for d in result["dispositions"]}
        self.assertIn(("engine_cc", "NOT_APPLICABLE"), states)
        self.assertIn(("length_mm", "UNKNOWN"), states)
        self.assertIn(("drive_type", "ALREADY_KNOWN"), states)
        self.assertIn(("battery_kwh", "NEEDS_SOURCE_TRACE"), states)
        city = gaps_for_model(snap, ("city.sv",))
        self.assertIn(("engine_cc", "TOMBSTONED_LOCKED"), {(d["field_key"],d["state"]) for d in city["dispositions"]})

    def test_registration_changes_score_not_decision(self):
        snap = fixture()
        before = {r["model_id"]: r["eligibility"] for r in plan(snap, policy())["decisions"]}
        changed = copy.deepcopy(snap)
        changed["registration_signals"] = [{"model_id":"toyota.yaris_ativ","stratum":"passenger","count":1}]
        after = {r["model_id"]: r["eligibility"] for r in plan(changed, policy())["decisions"]}
        self.assertEqual(before, after)
        self.assertTrue(all(not item["registration_is_evidence"] for item in plan(changed, policy())["queue"]))

    def test_audit_anti_starvation_reserves_one_slot_in_five(self):
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

    def test_unsafe_policy_fails_closed(self):
        p = policy()
        p["autonomy"]["allow_external_http"] = True
        with self.assertRaisesRegex(ValueError, "unsafe policy"):
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
