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
        self.assertEqual(cached_task["payload"]["source_action"],"PLAN_RETRIEVAL")
        with self.assertRaisesRegex(ValueError,"validated SourceDocument"):
            self.store.record_evidence(target_key=task["target_key"],content_sha256="a"*64,result=cached,at=DAY)
        unchanged=build_offline_plan(snap,self.policy,now=DAY,cached_documents=[cached],
                                    known_hashes={task["target_key"]:{"a"*64}})
        self.assertTrue(any(x["target_key"]==task["target_key"] for x in unchanged["tasks"]))
        self.assertNotIn("UNCHANGED_DOCUMENT_HASH",{x["reason"] for x in unchanged["dispositions"]})

    def test_cache_requires_content_bound_exact_trim_and_field_coverage(self):
        snap=fixture()
        doc=json.loads((ROOT/"fixtures/recorded_docs/th-spec-complete.json").read_text())
        doc["trim_ids"].append("atto.extended")
        doc["content"] += "\nclaim|safety.aeb|atto.extended|included"
        doc["content_sha256"]=hashlib.sha256(doc["content"].encode()).hexdigest()
        record={"source_document":doc,"content_sha256":doc["content_sha256"],"document_id":doc["document_id"]}
        valid=build_offline_plan(snap,self.policy,now=DAY,cached_documents=[record])
        safety=next(t for t in valid["tasks"] if t["target_key"]=="SPEC_ENRICH:byd.atto_3:safety")
        self.assertEqual(safety["payload"]["source_action"],"REPLAY_CACHED")
        for mutate in ("wrong_trim","wrong_field","partial_scope","unverified","bad_hash","forged_metadata"):
            with self.subTest(mutate=mutate):
                bad=copy.deepcopy(record)
                if mutate=="wrong_trim":
                    bad["source_document"]["content"]=bad["source_document"]["content"].replace("atto.extended","fake.trim")
                    bad["source_document"]["trim_ids"]=["fake.trim"]
                    bad["source_document"]["content_sha256"]=hashlib.sha256(bad["source_document"]["content"].encode()).hexdigest()
                    bad["content_sha256"]=bad["source_document"]["content_sha256"]
                elif mutate=="wrong_field":
                    bad["source_document"]["content"]=bad["source_document"]["content"].replace("safety.aeb","powertrain.max_power_kw")
                    bad["source_document"]["content_sha256"]=hashlib.sha256(bad["source_document"]["content"].encode()).hexdigest()
                    bad["content_sha256"]=bad["source_document"]["content_sha256"]
                elif mutate=="partial_scope":
                    bad["source_document"]["content"]="\n".join(line for line in bad["source_document"]["content"].splitlines()
                        if "atto.extended" not in line)
                    bad["source_document"]["content_sha256"]=hashlib.sha256(bad["source_document"]["content"].encode()).hexdigest()
                    bad["content_sha256"]=bad["source_document"]["content_sha256"]
                elif mutate=="unverified":
                    bad["source_document"]["source_authority"]="UNVERIFIED"
                elif mutate=="bad_hash":
                    bad["content_sha256"]="0"*64
                else:
                    bad={"model_id":"byd.atto_3","generation_id":"atto_3.g1","trim_ids":["atto.standard"],
                         "market":"TH","source_authority":"OFFICIAL","field_groups":["safety"],
                         "content_sha256":"a"*64}
                planned=build_offline_plan(snap,self.policy,now=DAY,cached_documents=[bad])
                actual=next(t for t in planned["tasks"] if t["target_key"]=="SPEC_ENRICH:byd.atto_3:safety")
                self.assertEqual(actual["payload"]["source_action"],"PLAN_RETRIEVAL")

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
            job=self.store.claim_next(now=DAY,owner="test",lease_seconds=100,cycle_size=5,spec_slots=1,
                                      audit_cycle_size=5,audit_slots=1)
            self.assertIsNotNone(job)
            observed.append(job["queue"])
            self.store.finish(job["idempotency_key"],owner="test",status="COMPLETED",now=DAY,result={})
        self.assertEqual(observed[0],"RETAIL_AUDIT")
        self.assertIn("SPEC_ENRICH",observed[:5])
        self.assertIn("SPEC_ENRICH",observed[5:10])
        self.assertIn("SPEC_ENRICH",observed[10:15])

    def test_independent_service_guarantees_with_different_windows_and_conflict_validation(self):
        for i in range(30):
            self.store.enqueue(make_job(f"audit-{i}","RETAIL_AUDIT"),at=DAY,max_attempts=1)
            self.store.enqueue(make_job(f"spec-{i}","SPEC_ENRICH"),at=DAY,max_attempts=1)
        observed=[]
        for _ in range(24):
            if _ == 12:
                self.store.close()
                self.store=SQLiteJobStore(self.db_path)
            job=self.store.claim_next(now=DAY,owner="test",lease_seconds=100,cycle_size=4,spec_slots=1,
                                      audit_cycle_size=3,audit_slots=1)
            observed.append(job["queue"])
            self.store.finish(job["idempotency_key"],owner="test",status="COMPLETED",now=DAY,result={})
        for start in range(0,24,4):
            self.assertIn("SPEC_ENRICH",observed[start:start+4])
        for start in range(0,24,3):
            self.assertIn("RETAIL_AUDIT",observed[start:start+3])
        conflicted=copy.deepcopy(self.policy)
        conflicted["queue_policy"].update(cycle_size=2,spec_enrich_slots_per_cycle=1,
                                          audit_anti_starvation_cycle_size=3,
                                          audit_anti_starvation_slots_per_cycle=2)
        with self.assertRaisesRegex(ValueError,"guarantees conflict"):
            validate_policy(conflicted)

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
        second_provider=OfflineFakeProvider(default={"state":"COMPLETED"},clock=self.clock)
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
        self.assertEqual(result["status"],"DAILY_QUOTA_DEFERRED")
        self.assertEqual(len(provider.calls),1)
        deferred=next(row for row in self.store.list_jobs() if row["target_key"]=="SPEC_ENRICH:request-2")
        self.assertEqual((deferred["status"],deferred["attempt_count"]),("QUEUED",0))
        self.clock.advance(86400)
        self.assertEqual(self.explicit_step(runner)["status"],"COMPLETED")
        resumed=next(row for row in self.store.list_jobs() if row["target_key"]=="SPEC_ENRICH:request-2")
        self.assertEqual((resumed["status"],resumed["attempt_count"]),("COMPLETED",1))
        self.assertEqual(self.store.usage("2026-10-12")["offline_requests"],1)

    def test_elapsed_daily_quota_defers_unclaimed_job_until_next_day(self):
        self.policy["runner"]["max_elapsed_seconds_per_day"]=10
        validate_policy(self.policy)
        self.enqueue_one("elapsed-1","RETAIL_AUDIT")
        self.enqueue_one("elapsed-2","SPEC_ENRICH")
        runner,provider=self.runner({"state":"COMPLETED","elapsed_seconds":10})
        self.assertEqual(self.explicit_step(runner)["status"],"COMPLETED")
        self.assertEqual(self.explicit_step(runner)["status"],"DAILY_QUOTA_DEFERRED")
        deferred=next(row for row in self.store.list_jobs() if row["target_key"]=="SPEC_ENRICH:elapsed-2")
        self.assertEqual((deferred["status"],deferred["attempt_count"]),("QUEUED",0))
        self.clock.advance(86400)
        self.assertEqual(self.explicit_step(runner)["status"],"COMPLETED")
        self.assertEqual(len(provider.calls),2)

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
        with self.assertRaisesRegex(ValueError,"validated SourceDocument"):
            self.store.record_evidence(target_key="SPEC_ENRICH:model:powertrain",content_sha256="c"*64,
                                       result={"value":1},at=DAY)
        document=json.loads((ROOT/"fixtures/recorded_docs/th-spec-complete.json").read_text())
        digest=hashlib.sha256(document["content"].encode()).hexdigest()
        record={"source_document":document}
        self.assertTrue(self.store.record_evidence(target_key="SPEC_ENRICH:model:powertrain",
            content_sha256=digest,result=record,at=DAY))
        self.assertFalse(self.store.record_evidence(target_key="SPEC_ENRICH:model:powertrain",
            content_sha256=digest,result=record,at=DAY+1))
        snap=fixture()
        snap["facts"].append({"trim_id":"atto.standard","field_key":"engine.displacement_cc",
            "value_state":"ABSENT","value":None,"verification_status":None})
        result=build_offline_plan(snap,self.policy,now=DAY)
        self.assertIn("CONFLICT",{x["status"] for x in result["dispositions"]})
        self.assertEqual(self.store.report()["external_http_calls"],0)

    def test_invalid_hash_and_cache_persistence_failure_never_complete_even_after_restart(self):
        self.enqueue_one("malformed-hash")
        runner,_=self.runner({"state":"COMPLETED","source_hash":"not-a-hash"})
        self.assertEqual(self.explicit_step(runner)["status"],"SOURCE_BROKEN")
        self.assertEqual(self.store.list_jobs()[0]["status"],"SOURCE_BROKEN")

        doc=json.loads((ROOT/"fixtures/recorded_docs/th-spec-complete.json").read_text())
        source_hash=hashlib.sha256(doc["content"].encode()).hexdigest()
        self.enqueue_one("cache-failure")
        self.store.db.execute("CREATE TRIGGER fail_evidence BEFORE INSERT ON evidence_cache BEGIN SELECT RAISE(ABORT, 'cache down'); END")
        runner,_=self.runner({"state":"COMPLETED","source_hash":source_hash,"source_document":doc})
        self.assertEqual(self.explicit_step(runner)["status"],"SOURCE_BROKEN")
        job=next(row for row in self.store.list_jobs() if row["target_key"]=="SPEC_ENRICH:cache-failure")
        self.assertNotEqual(job["status"],"COMPLETED")
        self.store.close()
        self.store=SQLiteJobStore(self.db_path)
        self.clock.advance(self.policy["runner"]["lease_seconds"]+1)
        self.store.recover_stale_leases(self.clock.now())
        self.assertNotEqual(next(row for row in self.store.list_jobs() if row["target_key"]=="SPEC_ENRICH:cache-failure")["status"],"COMPLETED")

    def test_default_lease_renews_during_901_second_mock_and_survives_restart(self):
        self.enqueue_one("long-step")
        runner,provider=self.runner({"state":"COMPLETED","elapsed_seconds":901})
        self.assertEqual(self.explicit_step(runner)["status"],"COMPLETED")
        self.assertEqual(self.store.list_jobs()[0]["attempt_count"],1)
        self.assertTrue(any(e["event_type"]=="LEASE_RENEWED" for e in self.store.report()["events"]))
        self.store.close()
        self.store=SQLiteJobStore(self.db_path)
        self.assertEqual(self.store.list_jobs()[0]["status"],"COMPLETED")
        self.assertEqual(self.store.usage("2026-10-11")["elapsed_seconds"],901)

    def test_scoped_completion_rejects_wrong_or_missing_evidence_and_recovers_after_replan(self):
        snapshot=fixture()
        self.policy["runner"]["maximum_retries_per_job"]=6
        validate_policy(self.policy)
        task=next(t for t in build_offline_plan(snapshot,self.policy,now=DAY)["tasks"]
                  if t["target_key"]=="SPEC_ENRICH:byd.atto_3:safety")
        max_attempts=7
        self.store.enqueue(task,at=DAY,max_attempts=max_attempts)
        key=task["idempotency_key"]
        self.store.bind_job_snapshot(key,snapshot,at=DAY)

        def valid_scope_document():
            doc=json.loads((ROOT/"fixtures/recorded_docs/th-spec-complete.json").read_text())
            doc["trim_ids"]=["atto.standard","atto.extended"]
            doc["content"]="\n".join(line for line in doc["content"].splitlines() if "safety.aeb" not in line)
            doc["content"] += "\nclaim|safety.aeb|atto.standard|included\nclaim|safety.aeb|atto.extended|included"
            doc["content_sha256"]=hashlib.sha256(doc["content"].encode()).hexdigest()
            return doc

        good=valid_scope_document()
        bad=[]
        for change in ("wrong_model","wrong_generation","wrong_trim","wrong_field"):
            doc=copy.deepcopy(good)
            if change=="wrong_model":
                doc["model_id"]="honda.city_hatchback"
            elif change=="wrong_generation":
                doc["generation_id"]="city_hb.g3"
            elif change=="wrong_trim":
                doc["trim_ids"]=["atto.standard"]
            elif change=="wrong_field":
                doc["content"]="\n".join(line for line in doc["content"].splitlines() if "safety.aeb" not in line)
                doc["content_sha256"]=hashlib.sha256(doc["content"].encode()).hexdigest()
            bad.append({"state":"COMPLETED","source_document":doc,"source_hash":doc["content_sha256"]})
        bad.append({"state":"COMPLETED"})
        responses={"SPEC_ENRICH:byd.atto_3:safety":bad+[{
            "state":"COMPLETED","source_document":good,"source_hash":good["content_sha256"]}]}
        provider=OfflineFakeProvider(responses=responses,clock=self.clock)
        runner=OfflineRunner(self.store,self.policy,self.clock,provider)

        result=self.explicit_step(runner)
        self.assertEqual((result["status"],result["reason"]),("RETRY_WAIT","EVIDENCE_MODEL_MISMATCH"))
        self.assertEqual(self.store.cached_evidence(),[])
        self.store.close()
        self.store=SQLiteJobStore(self.db_path)
        runner=OfflineRunner(self.store,self.policy,self.clock,provider)
        # Replanning reproduces the same scoped key; it leaves rejected work retryable.
        refreshed=next(t for t in build_offline_plan(snapshot,self.policy,now=self.clock.now())["tasks"]
                       if t["target_key"]==task["target_key"])
        self.assertEqual(refreshed["idempotency_key"],key)
        self.assertFalse(self.store.enqueue(refreshed,at=self.clock.now(),max_attempts=max_attempts))
        self.store.bind_job_snapshot(key,snapshot,at=self.clock.now())
        row=next(j for j in self.store.list_jobs() if j["idempotency_key"]==key)
        self.assertEqual(row["status"],"RETRY_WAIT")

        for reason in ("EVIDENCE_GENERATION_MISMATCH","EVIDENCE_TRIM_OR_FIELD_SCOPE_INCOMPLETE",
                       "EVIDENCE_TRIM_OR_FIELD_SCOPE_INCOMPLETE","COMPLETED_WITHOUT_SOURCE_DOCUMENT"):
            self.clock.advance(self.policy["runner"]["retry_cooldown_seconds"])
            result=self.explicit_step(runner)
            self.assertEqual((result["status"],result["reason"]),("RETRY_WAIT",reason))
            self.assertEqual(self.store.cached_evidence(),[])
        self.clock.advance(self.policy["runner"]["retry_cooldown_seconds"])
        result=self.explicit_step(runner)
        self.assertEqual(result["status"],"COMPLETED")
        self.assertEqual(self.store.list_jobs()[0]["attempt_count"],6)
        self.assertEqual(len(self.store.cached_evidence()),1)

    def test_policy_rejects_lease_shorter_than_safe_renewal_boundary(self):
        self.policy["runner"]["lease_seconds"]=1
        with self.assertRaisesRegex(ValueError,"lease_seconds must be an integer from 2"):
            validate_policy(self.policy)
        self.policy["runner"]["lease_seconds"]=900
        validate_policy(self.policy)

    def test_minimum_supported_two_second_lease_renews_before_expiry(self):
        self.policy["runner"]["lease_seconds"]=2
        validate_policy(self.policy)
        self.enqueue_one("min-lease")
        runner,_=self.runner({"state":"COMPLETED","elapsed_seconds":3})
        self.assertEqual(self.explicit_step(runner)["status"],"COMPLETED")
        self.assertEqual(self.store.list_jobs()[0]["attempt_count"],1)
        self.assertEqual(self.clock.now(),DAY+3)
        self.assertTrue(any(e["event_type"]=="LEASE_RENEWED" for e in self.store.report()["events"]))

    def test_replan_reopens_legacy_wrong_scope_completion_after_restart(self):
        snapshot=fixture()
        task=next(t for t in build_offline_plan(snapshot,self.policy,now=DAY)["tasks"]
                  if t["target_key"]=="SPEC_ENRICH:byd.atto_3:safety")
        self.store.enqueue(task,at=DAY,max_attempts=3)
        key=task["idempotency_key"]
        self.store.bind_job_snapshot(key,snapshot,at=DAY)
        wrong=json.loads((ROOT/"fixtures/recorded_docs/th-spec-complete.json").read_text())
        wrong["model_id"]="honda.city_hatchback"
        digest=hashlib.sha256(wrong["content"].encode()).hexdigest()
        with self.store._tx():
            self.store.db.execute("UPDATE jobs SET status='COMPLETED',attempt_count=1,result_json=? WHERE idempotency_key=?",
                (json.dumps({"source_document":wrong,"source_hash":digest},sort_keys=True),key))
            self.store.db.execute("INSERT INTO evidence_cache(target_key,content_sha256,result_json,recorded_at) VALUES(?,?,?,?)",
                (task["target_key"],digest,json.dumps({"source_document":wrong},sort_keys=True),DAY))
        self.store.close()
        self.store=SQLiteJobStore(self.db_path)
        runner=OfflineRunner(self.store,self.policy,self.clock,OfflineFakeProvider(clock=self.clock))
        replanned=runner.enqueue_plan(snapshot)
        self.assertTrue(any(t["target_key"]==task["target_key"] for t in replanned["tasks"]))
        recovered=next(j for j in self.store.list_jobs() if j["idempotency_key"]==key)
        self.assertEqual((recovered["status"],recovered["attempt_count"]),("QUEUED",1))
        self.assertEqual(self.store.cached_evidence(),[])

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
