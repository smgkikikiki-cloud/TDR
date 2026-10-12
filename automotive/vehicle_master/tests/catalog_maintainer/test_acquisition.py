from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from test_simulator import fixture, policy
from automotive.vehicle_master.catalog_maintainer.acquisition import (
    ContentAddressedEvidenceStore, DeterministicFakeHTTPTransport,
    OfflineSourceAcquisitionAdapter, PrerecordedHTTPResponse, load_source_registry,
)
from automotive.vehicle_master.catalog_maintainer.offline_runner import FakeClock, build_offline_plan
from automotive.vehicle_master.catalog_maintainer.retail_reconcile import (
    validate_source_completeness, validate_source_representation,
)


ROOT = Path(__file__).parents[2] / "catalog_maintainer"
DAY = 1791676800
URL = "https://oem-fixture.example/th/byd/atto-3/lineup.json"


def response(body: bytes, *, content_type="application/json", status_code=200, final_url=None,
             retry_after_seconds=0, elapsed_seconds=2, fixture_license="SYNTHETIC", robots_allowed=True):
    headers = {"Content-Type": content_type, "X-Content-SHA256": hashlib.sha256(body).hexdigest()}
    return PrerecordedHTTPResponse(status_code, headers, body, fixture_license, robots_allowed,
                                   retry_after_seconds, elapsed_seconds, final_url)


class SourceAcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ContentAddressedEvidenceStore(Path(self.temp.name) / "cas")
        self.clock = FakeClock(DAY)
        self.policy = policy()
        self.registry = load_source_registry()
        self.snapshot = fixture()
        plan = build_offline_plan(self.snapshot, self.policy, now=DAY)
        self.job = next(t for t in plan["tasks"] if t["queue"] == "RETAIL_AUDIT")
        # Chunk 5 acquisition remains generation scoped, even for source lineups.
        self.assertEqual(len(self.job["payload"]["generation_ids"]), 1)
        self.url = URL
        self.doc = json.loads((ROOT / "fixtures/recorded_docs/complete-lineup.json").read_text())
        self.doc.update(model_id="toyota.yaris_ativ", generation_id="yaris_ativ.g4",
                        trim_ids=["yaris.smart"], document_id="synthetic-yaris-lineup",
                        lineage_id="synthetic-yaris-lineage", edition_id="synthetic-yaris-edition",
                        local_source_id="fixture://source-response")
        scope = ("lineup_attestation|COMPLETE_CURRENT_THAI_RETAIL_LINEUP|model=toyota.yaris_ativ|"
                 "generation=yaris_ativ.g4|model_year=NONE|facelift=NONE")
        self.doc["content"] = "\n".join(("lineup|trim|yaris.smart", scope,
            "capture|edition=synthetic-yaris-edition|capture_id=capture-yaris|captured_at=2026-10-10|method=LOCAL_FIXTURE_CAPTURE"))
        self.doc["content_sha256"] = hashlib.sha256(self.doc["content"].encode()).hexdigest()
        self.doc["capture_manifest"].update(listed_trim_ids=["yaris.smart"], row_count=1)
        self.doc["capture_provenance"].update(capture_id="capture-yaris", captured_at="2026-10-10")
        self.doc["completeness_evidence"].update(quote=scope, locator="line:2")
        self.doc["lineup_rows"] = [{"market_trim_id":"yaris.smart", "model_id":"toyota.yaris_ativ",
            "generation_id":"yaris_ativ.g4", "grade":None, "powertrain":"ICE",
            "model_year":None, "facelift_id":None}]
        self.body = json.dumps(self.doc, sort_keys=True, separators=(",", ":")).encode()

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def adapter(self, responses, store=None, registry=None, policy_obj=None):
        transport=responses if isinstance(responses,DeterministicFakeHTTPTransport) else DeterministicFakeHTTPTransport(responses)
        return OfflineSourceAcquisitionAdapter(registry or self.registry,
            transport, store or self.store,
            policy_obj or self.policy, self.clock)

    def acquire(self, adapter=None, *, job=None, url=None):
        return (adapter or self.adapter({self.url: response(self.body)})).acquire(
            job or self.job, source_id="synthetic-oem-th", url=url or self.url, snapshot=self.snapshot)

    def test_valid_official_thai_document_is_content_addressed_and_generation_scoped(self):
        adapter = self.adapter({self.url: response(self.body)})
        result = self.acquire(adapter)
        self.assertEqual(result["disposition"], "FETCH_OK")
        self.assertEqual(result["source_document"]["market"], "TH")
        self.assertTrue(self.store.read_blob(result["local_source_id"]) == self.body)
        fingerprint = hashlib.sha256(json.dumps(result["source_document"],ensure_ascii=False,
            sort_keys=True,separators=(",",":")).encode()).hexdigest()
        evidence_path = self.store.documents / fingerprint[:2] / fingerprint
        self.assertTrue(evidence_path.is_file())
        self.assertEqual(result["external_http_calls"], 0)
        self.assertEqual(result["production_accesses"], 0)

    def test_host_url_redirect_and_registry_permission_are_fail_closed(self):
        adapter = self.adapter({self.url: response(self.body)})
        for bad_url, reason in (
            ("https://evil.example/th/lineup.json", "HOST_NOT_ALLOWLISTED"),
            ("https://oem-fixture.example:bad/th/lineup.json", "URL_INVALID"),
            ("https://user@oem-fixture.example/th/lineup.json", "URL_INVALID"),
            ("https://oem-fixture.example/th/../private.json", "URL_PATH_INVALID"),
        ):
            with self.subTest(url=bad_url):
                bad_job={**self.job,"idempotency_key":hashlib.sha256(bad_url.encode()).hexdigest()}
                self.assertEqual(self.acquire(adapter, job=bad_job, url=bad_url)["reason"], reason)
        redirected = response(self.body, status_code=302, final_url="https://evil.example/x")
        adapter = self.adapter({self.url: redirected})
        redirect_job={**self.job,"idempotency_key":hashlib.sha256(b"redirect").hexdigest()}
        self.assertEqual(self.acquire(adapter,job=redirect_job)["reason"], "REDIRECTS_DISABLED")
        denied = copy.deepcopy(self.registry)
        denied["sources"][0]["permission_status"] = "NO_PERMISSION"
        with self.assertRaises(ValueError):
            self.adapter({self.url: response(self.body)}, registry=denied)

    def test_malformed_and_stale_hash_documents_never_enter_evidence_cache(self):
        malformed = b"{not-json"
        result = self.acquire(self.adapter({self.url: response(malformed)}))
        self.assertEqual(result["disposition"], "SOURCE_BROKEN")
        self.assertEqual(self.store.evidence_document("0" * 64), None)
        self.clock.advance(2)
        bad_hash = PrerecordedHTTPResponse(200, {"Content-Type": "application/json",
            "X-Content-SHA256": "0" * 64}, self.body, "SYNTHETIC", True)
        result = self.acquire(self.adapter({self.url: bad_hash}), job={**self.job,
            "idempotency_key": hashlib.sha256(b"stale").hexdigest()})
        self.assertEqual(result["reason"], "RESPONSE_BODY_HASH_MISMATCH")
        self.assertEqual(self.store.evidence_document(self.doc["content_sha256"]), None)

    def test_incomplete_lineup_is_partial_and_cannot_cover_another_generation(self):
        incomplete = copy.deepcopy(self.doc)
        incomplete["completeness"] = "PARTIAL_TRIM_LIST"
        incomplete.pop("completeness_evidence")
        body = json.dumps(incomplete, sort_keys=True, separators=(",", ":")).encode()
        result = self.acquire(self.adapter({self.url: response(body)}))
        self.assertIn(result["disposition"], {"PARTIAL", "SOURCE_BROKEN"})
        self.assertEqual(self.store.evidence_document(self.doc["content_sha256"]), None)

    def test_multi_generation_retail_job_is_blocked_before_transport(self):
        transport = DeterministicFakeHTTPTransport({self.url:response(self.body)})
        adapter = OfflineSourceAcquisitionAdapter(self.registry, transport, self.store, self.policy, self.clock)
        multi = copy.deepcopy(self.job)
        multi["idempotency_key"] = hashlib.sha256(b"multi-generation-retail").hexdigest()
        multi["payload"]["generation_ids"] = ["yaris_ativ.g4", "yaris_ativ.g5"]
        result = self.acquire(adapter, job=multi)
        self.assertEqual((result["disposition"],result["reason"]),
                         ("BLOCKED","RETAIL_AUDIT_REQUIRES_ONE_GENERATION"))
        self.assertEqual(transport.calls, [])

    def test_complete_g1_lineup_is_partial_for_generation_g2_job(self):
        task=copy.deepcopy(self.job)
        task["idempotency_key"]=hashlib.sha256(b"g2-only").hexdigest()
        task["target_key"]="RETAIL_AUDIT:toyota.yaris_ativ:yaris_ativ.g5:RETAIL_LINEUP"
        task["payload"]["generation_ids"]=["yaris_ativ.g5"]
        result=self.acquire(self.adapter({self.url:response(self.body)}),job=task)
        self.assertEqual((result["disposition"],result["reason"]),
                         ("PARTIAL","EVIDENCE_GENERATION_MISMATCH"))
        self.assertIsNone(self.store.evidence_document(self.doc["content_sha256"]))

    def test_license_and_robots_denial_are_audited_without_evidence(self):
        for label, robots, reason in (("DENIED", True, "CONTENT_LICENSE_NOT_PERMITTED"),
                                      ("SYNTHETIC", False, "ROBOTS_POLICY_DENIED")):
            denied = PrerecordedHTTPResponse(200, {"Content-Type":"application/json",
                "X-Content-SHA256":hashlib.sha256(self.body).hexdigest()}, self.body, label, robots)
            key = hashlib.sha256(reason.encode()).hexdigest()
            result = self.acquire(self.adapter({self.url:denied}), job={**self.job,"idempotency_key":key})
            self.assertEqual(result["reason"], reason)
            self.clock.advance(2)
            self.assertIsNone(self.store.evidence_document(self.doc["content_sha256"]))

    def test_duplicate_and_restart_replay_are_idempotent_without_second_fake_request(self):
        transport = DeterministicFakeHTTPTransport({self.url: response(self.body)})
        adapter = OfflineSourceAcquisitionAdapter(self.registry, transport, self.store, self.policy, self.clock)
        first = self.acquire(adapter)
        duplicate = self.acquire(adapter)
        self.assertEqual(first["disposition"], "FETCH_OK")
        self.assertEqual(duplicate["disposition"], "UNCHANGED")
        self.assertEqual(len(transport.calls), 1)
        self.store.close()
        self.store = ContentAddressedEvidenceStore(Path(self.temp.name) / "cas")
        restarted = OfflineSourceAcquisitionAdapter(self.registry,
            DeterministicFakeHTTPTransport({}), self.store, self.policy, self.clock)
        result = self.acquire(restarted)
        self.assertEqual(result["disposition"], "UNCHANGED")
        self.assertEqual(result["reason"], "IDEMPOTENT_REPLAY")

    def test_same_normalized_content_with_different_metadata_is_independently_indexed(self):
        first=self.doc.copy(); second=self.doc.copy()
        second["document_id"]="synthetic-yaris-lineup-edition-2"
        second["published_at"]="2026-10-02"
        bodies=[json.dumps(d,sort_keys=True,separators=(",",":")).encode() for d in (first,second)]
        transport=DeterministicFakeHTTPTransport({self.url:[response(bodies[0]),response(bodies[1])]})
        adapter=self.adapter(transport)
        task1={**self.job,"idempotency_key":hashlib.sha256(b"doc-version-1").hexdigest()}
        task2={**self.job,"idempotency_key":hashlib.sha256(b"doc-version-2").hexdigest()}
        one=self.acquire(adapter,job=task1); self.clock.advance(10)
        two=self.acquire(adapter,job=task2)
        self.assertEqual((one["disposition"],two["disposition"]),("FETCH_OK","FETCH_OK"))
        self.assertEqual(one["source_hash"],two["source_hash"])
        self.assertNotEqual(one["source_document"]["document_id"],two["source_document"]["document_id"])
        self.assertIsNone(self.store.evidence_document(one["source_hash"]))
        count=self.store.db.execute("SELECT count(*) FROM evidence_versions WHERE content_sha256=?",
                                    (one["source_hash"],)).fetchone()[0]
        self.assertEqual(count,2)

    def test_exact_document_duplicate_with_new_request_key_remains_idempotent(self):
        transport=DeterministicFakeHTTPTransport({self.url:[response(self.body),response(self.body)]})
        adapter=self.adapter(transport)
        first=self.acquire(adapter,job={**self.job,"idempotency_key":hashlib.sha256(b"same-doc-a").hexdigest()})
        self.clock.advance(10)
        second=self.acquire(adapter,job={**self.job,"idempotency_key":hashlib.sha256(b"same-doc-b").hexdigest()})
        self.assertEqual(first["disposition"],"FETCH_OK")
        self.assertEqual(second["disposition"],"UNCHANGED")
        self.assertEqual(len(transport.calls),2)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM evidence_versions").fetchone()[0],1)

    def _assert_integrity_retry_recovers(self,corrupt):
        transport=DeterministicFakeHTTPTransport({self.url:response(self.body)})
        adapter=self.adapter(transport); first=self.acquire(adapter)
        self.assertEqual(first["disposition"],"FETCH_OK")
        corrupt(first)
        self.store.close()
        self.store=ContentAddressedEvidenceStore(Path(self.temp.name)/"cas")
        self.clock.advance(1000)
        retry_transport=DeterministicFakeHTTPTransport({self.url:response(self.body)})
        restarted=self.adapter(retry_transport)
        recovered=self.acquire(restarted)
        self.assertIn(recovered["disposition"],{"FETCH_OK","UNCHANGED"})
        self.assertEqual(recovered["reason"],"SOURCE_DOCUMENT_VALIDATED")
        self.assertEqual(len(retry_transport.calls),1)
        self.assertEqual(self.store.read_blob(recovered["local_source_id"]),self.body)
        self.assertIsNotNone(self.store.evidence_version(recovered["source_document"]))

    def test_deleted_raw_cas_blob_is_retried_and_recovered_after_sqlite_restart(self):
        def remove_raw(first):
            digest=first["local_source_id"].rsplit("/",1)[1]
            (self.store.blobs/digest[:2]/digest).unlink()
        self._assert_integrity_retry_recovers(remove_raw)

    def test_corrupted_raw_cas_blob_is_retried_and_recovered_after_sqlite_restart(self):
        def corrupt_raw(first):
            digest=first["local_source_id"].rsplit("/",1)[1]
            (self.store.blobs/digest[:2]/digest).write_bytes(b"tampered")
        self._assert_integrity_retry_recovers(corrupt_raw)

    def test_corrupt_normalized_evidence_file_is_retried_and_repaired(self):
        def corrupt_file(first):
            fp=hashlib.sha256(json.dumps(first["source_document"],sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
            (self.store.documents/fp[:2]/fp).write_text("{}",encoding="utf-8")
        self._assert_integrity_retry_recovers(corrupt_file)

    def test_corrupt_sqlite_evidence_index_is_retried_and_repaired(self):
        def corrupt_index(first):
            self.store.db.execute("UPDATE evidence_versions SET document_json='{}' WHERE content_sha256=?",
                                  (first["source_hash"],))
        self._assert_integrity_retry_recovers(corrupt_index)

    def test_deleted_sqlite_evidence_index_is_retried_and_recovered(self):
        def remove_index(first):
            self.store.db.execute("DELETE FROM evidence_versions WHERE content_sha256=?",(first["source_hash"],))
        self._assert_integrity_retry_recovers(remove_index)

    def test_rate_limit_and_bounded_retry_recover_after_cooldown(self):
        limited = PrerecordedHTTPResponse(429, {}, b"", "SYNTHETIC", True, retry_after_seconds=30)
        transport = DeterministicFakeHTTPTransport({self.url:[limited,response(self.body)]})
        adapter = OfflineSourceAcquisitionAdapter(self.registry, transport, self.store, self.policy, self.clock)
        first = self.acquire(adapter)
        self.assertEqual(first["reason"], "RATE_LIMITED")
        self.assertEqual(len(transport.calls), 1)
        self.clock.advance(60)
        second = self.acquire(adapter)
        self.assertEqual(second["disposition"], "FETCH_OK")
        self.assertEqual(len(transport.calls), 2)
        self.assertEqual(self.store.usage("2026-10-11")["requests"], 2)

    def test_structured_html_and_pdf_fixtures_are_parsed_offline(self):
        html_path = ROOT / "fixtures/source_acquisition/complete-lineup.html"
        html_body = html_path.read_bytes()
        html_url = "https://oem-fixture.example/th/yaris/lineup.html"
        html_result = self.adapter({html_url:response(html_body, content_type="text/html")}).acquire(
            self.job, source_id="synthetic-oem-th", url=html_url, snapshot=self.snapshot)
        self.assertEqual(html_result["disposition"], "FETCH_OK")
        self.assertEqual(html_result["source_document"]["generation_id"], "yaris_ativ.g4")
        html_doc=html_result["source_document"]
        self.assertNotIn("quote",html_doc["completeness_evidence"])
        self.assertEqual(html_doc["completeness_evidence"]["assertion_type"],"structured_attribute_assertion")
        self.assertEqual(html_doc["completeness_evidence"]["raw_source_sha256"],hashlib.sha256(html_body).hexdigest())
        self.assertTrue(validate_source_completeness(html_doc)["complete"])
        self.assertTrue(validate_source_representation(html_doc)["valid"])
        self.clock.advance(2)

        spec_task = next(t for t in build_offline_plan(self.snapshot,self.policy,now=DAY)["tasks"]
                         if t["queue"] == "SPEC_ENRICH" and t["payload"]["model_id"] == "byd.atto_3"
                         and t["payload"]["field_group"] == "safety")
        pdf_path = ROOT / "fixtures/source_acquisition/spec-sheet.pdf-fixture.json"
        pdf_body = pdf_path.read_bytes()
        pdf_url = "https://oem-fixture.example/th/atto/spec.pdf"
        pdf_result = self.adapter({pdf_url:response(pdf_body, content_type="application/pdf")}).acquire(
            spec_task, source_id="synthetic-oem-th", url=pdf_url, snapshot=self.snapshot)
        self.assertEqual(pdf_result["disposition"], "FETCH_OK")
        self.assertEqual(pdf_result["source_document"]["source_kind"], "SPEC_SHEET")

    def test_html_missing_explicit_completeness_attribute_stays_partial(self):
        html=(ROOT/"fixtures/source_acquisition/complete-lineup.html").read_bytes()
        html=html.replace(b' data-publisher-declared-complete="true"',b'')
        url="https://oem-fixture.example/th/yaris/incomplete-lineup.html"
        result=self.adapter({url:response(html,content_type="text/html")}).acquire(
            self.job,source_id="synthetic-oem-th",url=url,snapshot=self.snapshot)
        self.assertEqual(result["disposition"],"PARTIAL")
        self.assertEqual(result["source_document"]["completeness"],"PARTIAL_TRIM_LIST")
        self.assertFalse(validate_source_completeness(result["source_document"])["complete"])
        self.assertNotIn("completeness_evidence",result["source_document"])

    def test_html_spec_claims_are_structured_and_must_match_raw_attributes(self):
        from automotive.vehicle_master.catalog_maintainer.acquisition import _document_from_html, _sha
        raw=(b'<source-document data-document-id="spec-1" data-model-id="byd.atto_3" '
             b'data-generation-id="atto_3.g1" data-captured-at="2026-10-10" data-source-kind="SPEC_SHEET"></source-document>\n'
             b'<claim data-field="battery_kwh" data-trim="atto.advanced" data-value="60.48 kWh" data-unit="kWh"></claim>')
        source=self.registry["sources"][0]; local="fixture://cas/sha256/"+hashlib.sha256(raw).hexdigest()
        doc=_document_from_html(raw,source,local)
        self.assertEqual(doc["source_representation"]["kind"],"STRUCTURED_HTML_ATTRIBUTES")
        self.assertTrue(validate_source_representation(doc)["valid"])
        forged=copy.deepcopy(doc)
        forged["source_representation"]["assertions"][1]["normalized_lines"]=["claim|battery_kwh|atto.advanced|999 kWh"]
        self.assertFalse(validate_source_representation(forged)["valid"])


if __name__ == "__main__":
    unittest.main()
