from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from test_simulator import fixture, policy
from automotive.vehicle_master.catalog_maintainer.offline_runner import (
    FakeClock, OfflineFakeProvider, OfflineRunner, SQLiteJobStore, WorkerInterrupted,
    build_offline_plan, validate_offline_plan, validate_runner_report,
)
from automotive.vehicle_master.catalog_maintainer.validation import validate_policy


ROOT = Path(__file__).parents[2] / "catalog_maintainer"
DAY = 1791676800  # 2026-10-11 00:00:00 UTC


def make_job(key: str, queue: str, *, at: int = DAY, priority: float = 1) -> dict:
    stable=hashlib.sha256(key.encode()).hexdigest()
    return {"idempotency_key":stable,"target_key":f"{queue}:{key}","queue":queue,
            "priority":priority,"payload":{"target":key}}


class OfflineRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "jobs.sqlite"
        self.clock = FakeClock(DAY)
        self.policy = policy()
        self.store = SQLiteJobStore(self.db_path)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def runner(self, response=None):
        provider = OfflineFakeProvider(default=response or {"state":"COMPLETED"},clock=self.clock)
        return OfflineRunner(self.store,self.policy,self.clock,provider),provider

    def enqueue_one(self, key="job-1", queue="SPEC_ENRICH"):
        self.store.enqueue(make_job(key,queue),at=self.clock.now(),
                           max_attempts=1+self.policy["runner"]["maximum_retries_per_job"])

    def explicit_step(self, runner):
        runner.arm_one_manual_mock_step()
        return runner.run_one_manual_step()

    def test_default_pause_and_kill_switch_block_execution_and_rearm_after_one_step(self):
        self.enqueue_one()
        runner,provider=self.runner()
        self.assertEqual(self.store.controls(),{"manual_pause":True,"kill_engaged":True})
        self.assertEqual(runner.run_one_manual_step()["reason"],"KILL_SWITCH_ENGAGED")
        runner.arm_one_manual_mock_step()
        self.assertEqual(runner.run_one_manual_step()["status"],"COMPLETED")
        self.assertEqual(self.store.controls(),{"manual_pause":True,"kill_engaged":True})
        self.assertEqual(len(provider.calls),1)
        runner.arm_one_manual_mock_step()
        runner.kill()
        self.assertEqual(runner.run_one_manual_step()["reason"],"KILL_SWITCH_ENGAGED")
        self.assertEqual(len(provider.calls),1)

    def test_plan_is_document_first_and_skips_snapshot_known_and_cached_hashes(self):
        snap=fixture()
        base=build_offline_plan(snap,self.policy,now=DAY)
        self.assertTrue(base["planner_summary"]["snapshot_checked"])
        self.assertTrue(base["planner_summary"]["cached_evidence_checked"])
        self.assertTrue(base["tasks"])
        task=base["tasks"][0]
        cached={"model_id":task["payload"]["model_id"],"market":"TH","source_authority":"OFFICIAL",
                "field_groups":[task["payload"]["field_group"]],
                "content_sha256":"a"*64,"document_id":"doc-fixture"}
        cached_plan=build_offline_plan(snap,self.policy,now=DAY,cached_documents=[cached])
        cached_task=next(x for x in cached_plan["tasks"] if x["target_key"]==task["target_key"])
        self.assertEqual(cached_task["payload"]["source_action"],"REPLAY_CACHED")
        self.store.record_evidence(target_key=task["target_key"],content_sha256="a"*64,
                                   result=cached,at=DAY)
        unchanged=build_offline_plan(snap,self.policy,now=DAY,cached_documents=[cached],
                                    known_hashes=self.store.cached_hashes())
        self.assertFalse(any(x["target_key"]==task["target_key"] for x in unchanged["tasks"]))
        self.assertIn("UNCHANGED_DOCUMENT_HASH",{x["reason"] for x in unchanged["dispositions"]})

    def test_duplicate_enqueue_is_idempotent_and_payload_mismatch_fails_closed(self):
        job=make_job("stable","RETAIL_AUDIT")
        self.assertTrue(self.store.enqueue(job,at=DAY,max_attempts=3))
        self.assertFalse(self.store.enqueue(job,at=DAY,max_attempts=3))
        changed=copy.deepcopy(job); changed["payload"]["target"]="different"
        with self.assertRaisesRegex(ValueError,"idempotency key reused"):
            self.store.enqueue(changed,at=DAY,max_attempts=3)
        self.assertEqual(len(self.store.list_jobs()),1)

    def test_job_identity_is_scoped_to_relevant_policy_revision(self):
        snapshot=fixture()
        baseline=build_offline_plan(snapshot,self.policy,now=DAY)
        tuned=copy.deepcopy(self.policy)
        tuned["runner"]["max_offline_requests_per_day"]+=1
        validate_policy(tuned)
        changed=build_offline_plan(snapshot,tuned,now=DAY)
        self.assertNotEqual(baseline["tasks"][0]["idempotency_key"],changed["tasks"][0]["idempotency_key"])
        self.assertEqual(baseline["tasks"][0]["payload"]["policy_revision"],
                         baseline["tasks"][-1]["payload"]["policy_revision"])

    def test_normalized_plan_and_persisted_report_contracts_fail_closed(self):
        plan_doc=build_offline_plan(fixture(),self.policy,now=DAY)
        validate_offline_plan(plan_doc)
        invalid=copy.deepcopy(plan_doc)
        invalid["tasks"][0]["idempotency_key"]="bad"
        with self.assertRaisesRegex(ValueError,"invalid task"):
            validate_offline_plan(invalid)
        report=self.store.report()
        validate_runner_report(report)
        report["production_writes"]=1
        with self.assertRaisesRegex(ValueError,"zero boundary"):
            validate_runner_report(report)

    def test_fair_scheduler_services_spec_queue_with_large_retail_backlog(self):
        for i in range(12):
            self.store.enqueue(make_job(f"r{i:02}","RETAIL_AUDIT"),at=DAY,max_attempts=1)
        for i in range(3):
            self.store.enqueue(make_job(f"s{i:02}","SPEC_ENRICH"),at=DAY,max_attempts=1)
        observed=[]
        for _ in range(15):
            job=self.store.claim_next(now=DAY,owner="test",lease_seconds=100,cycle_size=5,spec_slots=1)
            self.assertIsNotNone(job)
            observed.append(job["queue"])
            self.store.finish(job["idempotency_key"],owner="test",status="COMPLETED",now=DAY,result={})
        self.assertEqual(observed[:5],["RETAIL_AUDIT"]*4+["SPEC_ENRICH"])
        self.assertEqual(observed[5:10],["RETAIL_AUDIT"]*4+["SPEC_ENRICH"])
        self.assertEqual(observed[14],"SPEC_ENRICH")

    def test_worker_interruption_checkpoint_persists_and_restart_recovers_after_stale_lease(self):
        self.enqueue_one("crash")
        first_provider=OfflineFakeProvider(default={"state":"COMPLETED","checkpoint":{"stage":"cached-doc-ready"},
            "interrupt_after_checkpoint":True},clock=self.clock)
        first=OfflineRunner(self.store,self.policy,self.clock,first_provider)
        first.arm_one_manual_mock_step()
        with self.assertRaises(WorkerInterrupted):
            first.run_one_manual_step()
        saved=self.store.list_jobs()[0]
        self.assertEqual(saved["status"],"LEASED")
        self.assertEqual(saved["checkpoint"],{"stage":"cached-doc-ready"})
        self.assertEqual(self.store.usage("2026-10-11")["offline_requests"],1)
        self.store.close()

        self.clock.advance(self.policy["runner"]["lease_seconds"]+1)
        self.store=SQLiteJobStore(self.db_path)
        second_provider=OfflineFakeProvider(default={"state":"COMPLETED","source_hash":"b"*64},clock=self.clock)
        second=OfflineRunner(self.store,self.policy,self.clock,second_provider)
        result=self.explicit_step(second)
        self.assertEqual(result["status"],"COMPLETED")
        self.assertEqual(second_provider.calls[0]["checkpoint"],{"stage":"cached-doc-ready"})
        recovered=self.store.list_jobs()[0]
        self.assertEqual(recovered["attempt_count"],2)
        self.assertEqual(recovered["status"],"COMPLETED")
        self.assertEqual(self.store.usage("2026-10-11")["offline_requests"],2)

    def test_stale_lease_recovery_rejects_old_owner_and_releases_for_new_worker(self):
        self.enqueue_one("lease")
        key=self.store.list_jobs()[0]["idempotency_key"]
        old=self.store.claim_next(now=DAY,owner="old",lease_seconds=5,cycle_size=5,spec_slots=1)
        self.store.checkpoint(key,owner="old",checkpoint={"offset":8},now=DAY+1)
        self.clock.advance(6)
        self.assertEqual(self.store.recover_stale_leases(self.clock.now()),1)
        new=self.store.claim_next(now=self.clock.now(),owner="new",lease_seconds=10,cycle_size=5,spec_slots=1)
        self.assertEqual(new["attempt_count"],2)
        self.assertEqual(new["checkpoint"],{"offset":8})
        with self.assertRaisesRegex(ValueError,"lease is missing"):
            self.store.finish(key,owner="old",status="COMPLETED",now=self.clock.now(),result={})

    def test_retry_wait_cooldown_and_terminal_source_broken_are_distinct(self):
        self.policy["runner"]["maximum_retries_per_job"]=1
        validate_policy(self.policy)
        self.enqueue_one("retry")
        key="retry"
        provider=OfflineFakeProvider(responses={"SPEC_ENRICH:"+key:[
            {"state":"SOURCE_BROKEN","retryable":True,"reason":"FIXTURE_TEMPORARY"},
            {"state":"SOURCE_BROKEN","retryable":True,"reason":"FIXTURE_STILL_BROKEN"}]},clock=self.clock)
        runner=OfflineRunner(self.store,self.policy,self.clock,provider)
        self.assertEqual(self.explicit_step(runner)["status"],"RETRY_WAIT")
        self.clock.advance(3600-1)
        self.assertEqual(self.explicit_step(runner)["status"],"IDLE")
        self.clock.advance(1)
        self.assertEqual(self.explicit_step(runner)["status"],"SOURCE_BROKEN")
        row=self.store.list_jobs()[0]
        self.assertEqual((row["attempt_count"],row["status"]),(2,"SOURCE_BROKEN"))
        self.assertEqual(len(provider.calls),2)

    def test_negative_cache_suppresses_until_expiry_then_new_idempotency_epoch(self):
        snapshot=fixture()
        runner,provider=self.runner({"state":"SOURCE_EXHAUSTED","reason":"MOCK_NO_SOURCE"})
        plan_doc=runner.enqueue_plan(snapshot)
        first=next(j for j in self.store.list_jobs() if j["queue"]=="RETAIL_AUDIT")
        self.assertEqual(self.explicit_step(runner)["status"],"SOURCE_EXHAUSTED")
        second_plan=build_offline_plan(snapshot,self.policy,now=DAY+86400,
            known_hashes=self.store.cached_hashes(),negative_cache=self.store.negative_cache_rows(DAY+86400))
        self.assertTrue(any(d["target_key"]==first["target_key"] and d["status"]=="SOURCE_EXHAUSTED"
                            for d in second_plan["dispositions"]))
        self.clock.advance(self.policy["research"]["negative_cache_days"]*86400+1)
        expired=build_offline_plan(snapshot,self.policy,now=self.clock.now(),
            known_hashes=self.store.cached_hashes(),negative_cache=self.store.negative_cache_rows(self.clock.now()))
        renewed=next(t for t in expired["tasks"] if t["target_key"]==first["target_key"])
        self.assertNotEqual(renewed["idempotency_key"],first["idempotency_key"])
        self.assertEqual(plan_doc["planner_summary"]["external_http_calls"],0)

    def test_measured_request_budget_exhaustion_resets_on_next_day(self):
        self.policy["runner"]["max_offline_requests_per_day"]=1
        validate_policy(self.policy)
        self.enqueue_one("request-1","RETAIL_AUDIT")
        self.enqueue_one("request-2","SPEC_ENRICH")
        runner,provider=self.runner({"state":"COMPLETED"})
        self.assertEqual(self.explicit_step(runner)["status"],"COMPLETED")
        result=self.explicit_step(runner)
        self.assertEqual(result["status"],"BUDGET_EXHAUSTED")
        self.assertEqual(len(provider.calls),1)
        self.enqueue_one("request-3","RETAIL_AUDIT")
        self.clock.advance(86400)
        self.assertEqual(self.explicit_step(runner)["status"],"COMPLETED")
        self.assertEqual(self.store.usage("2026-10-12")["offline_requests"],1)

    def test_zero_token_spend_and_elapsed_budgets_fail_closed_on_measured_mock_usage(self):
        cases=[
            ({"usage_tokens":1},"MEASURED_USAGE_EXCEEDED_POLICY"),
            ({"usage_spend_thb":0.01},"MEASURED_USAGE_EXCEEDED_POLICY"),
            ({"elapsed_seconds":3601},"MEASURED_USAGE_EXCEEDED_POLICY"),
        ]
        for i,(metrics,reason) in enumerate(cases):
            with self.subTest(metrics=metrics):
                self.policy["runner"]["lease_seconds"]=7200
                temp=SQLiteJobStore(Path(self.temp.name)/f"budget-{i}.sqlite")
                clock=FakeClock(DAY)
                temp.enqueue(make_job(f"budget-{i}","SPEC_ENRICH"),at=DAY,max_attempts=2)
                response={"state":"COMPLETED",**metrics}
                provider=OfflineFakeProvider(default=response,clock=clock)
                runner=OfflineRunner(temp,self.policy,clock,provider)
                runner.arm_one_manual_mock_step()
                self.assertEqual(runner.run_one_manual_step()["status"],"BUDGET_EXHAUSTED")
                report=temp.report()
                self.assertEqual(report["paid_tokens"],0)
                self.assertEqual(report["paid_spend_thb"],0)
                self.assertEqual(temp.list_jobs()[0]["failure_code"],reason)
                temp.close()

    def test_duplicate_evidence_hash_is_ignored_and_conflicts_are_terminal_dispositions(self):
        digest="c"*64
        target="SPEC_ENRICH:model:powertrain"
        self.assertTrue(self.store.record_evidence(target_key=target,content_sha256=digest,result={"value":1},at=DAY))
        self.assertFalse(self.store.record_evidence(target_key=target,content_sha256=digest,result={"value":1},at=DAY+1))
        snap=fixture()
        snap["facts"].append({"trim_id":"atto.standard","field_key":"engine.displacement_cc",
            "value_state":"ABSENT","value":None,"verification_status":None})
        result=build_offline_plan(snap,self.policy,now=DAY)
        self.assertIn("CONFLICT",{x["status"] for x in result["dispositions"]})
        self.assertEqual(self.store.report()["external_http_calls"],0)

    def test_identity_ambiguity_is_a_terminal_planning_disposition(self):
        snap=fixture()
        snap["models"].append({"id":"orphan.current","status":"CURRENT"})
        result=build_offline_plan(snap,self.policy,now=DAY)
        finding=next(x for x in result["dispositions"] if x["target_key"]=="IDENTITY:orphan.current")
        self.assertEqual(finding["status"],"IDENTITY_AMBIGUOUS")

    def test_policy_fails_closed_when_any_external_or_autonomous_flag_is_enabled(self):
        for section,key in (("runner","background_execution"),("runner","external_http_enabled"),
                            ("runner","paid_ai_enabled"),("runner","production_database_enabled")):
            changed=copy.deepcopy(self.policy); changed[section][key]=True
            with self.subTest(key=key),self.assertRaises(ValueError):
                validate_policy(changed)

    def test_report_measures_zero_external_paid_and_production_activity(self):
        self.enqueue_one()
        runner,provider=self.runner()
        self.explicit_step(runner)
        report=runner.report()
        self.assertEqual(report["external_http_calls"],0)
        self.assertEqual(report["paid_model_calls"],0)
        self.assertEqual(report["paid_tokens"],0)
        self.assertEqual(report["paid_spend_thb"],0)
        self.assertEqual(report["production_database_accesses"],0)
        self.assertEqual(report["production_writes"],0)
        self.assertEqual(report["background_workers_started"],0)
        self.assertEqual(report["daily_usage"][0]["offline_requests"],1)
        self.assertEqual(provider.external_calls,0)


if __name__ == "__main__":
    unittest.main()
