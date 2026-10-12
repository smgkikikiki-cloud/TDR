from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from automotive.vehicle_master.catalog_maintainer.ai_extraction import (
    MODEL_ID, ExtractionError, _request, _response_claims, run_mock_extraction,
)
from automotive.vehicle_master.catalog_maintainer.replay import SUPPORTED, replay

ROOT = Path(__file__).parents[2] / "catalog_maintainer"
SNAPSHOT = ROOT / "fixtures/sample_snapshot.json"
DOCUMENT = ROOT / "fixtures/ai_mock_document.json"
CASSETTE = ROOT / "fixtures/ai_mock_responses.json"


class MockAIExtractionTests(unittest.TestCase):
    def run_fixture(self, cache: Path, out: Path) -> dict:
        return run_mock_extraction(SNAPSHOT, [DOCUMENT], CASSETTE, cache, out,
                                   confirm_mock_only=True, root=REPOSITORY_ROOT)

    def run_full_path_claims(self, root: Path, doc: dict, claims: list[dict], snapshot_path: Path = SNAPSHOT):
        document_path = root / "document.json"
        document_path.write_text(json.dumps(doc))
        with tempfile.TemporaryDirectory() as baseline_dir:
            replay(snapshot_path, [document_path], baseline_dir, root=REPOSITORY_ROOT)
            dispositions = json.loads((Path(baseline_dir) / "gap_diff.json").read_text())["dispositions"]
            existing = {(json.loads(line)["trim_id"], json.loads(line)["field_key"])
                        for line in (Path(baseline_dir) / "field_candidates.jsonl").read_text().splitlines()}
        pairs = sorted({(row["trim_id"], row["field_key"]) for row in dispositions
                        if row["trim_id"] in doc["trim_ids"] and row["state"] in {
                            "MISSING", "UNKNOWN", "NEEDS_SOURCE_TRACE", "SOURCE_EXHAUSTED", "NOT_AVAILABLE"}
                        and row["field_key"] in SUPPORTED
                        and (row["trim_id"], row["field_key"]) not in existing})
        request = _request(doc, pairs)
        response = {"schema_version": "1.0", "mode": "MOCK", "model_id": MODEL_ID,
                    "request_key": request.request_key, "claims": [
                        {**claim, "qualifiers": {}, "quote": doc["content"], "locator": "line:1"}
                        for claim in claims]}
        tape_path = root / "tape.json"
        tape_path.write_text(json.dumps({"schema_version": "1.0", "mode": "MOCK",
                                         "model_id": MODEL_ID,
                                         "responses": {request.request_key: response}}))
        output = root / "output"
        summary = run_mock_extraction(snapshot_path, [document_path], tape_path, root / "cache", output,
                                      confirm_mock_only=True, root=REPOSITORY_ROOT)
        candidates = [json.loads(line) for line in (output / "field_candidates.jsonl").read_text().splitlines()]
        gap_diff = json.loads((output / "gap_diff.json").read_text())
        return summary, candidates, gap_diff, set(pairs)

    def test_recorded_response_is_scope_checked_by_canonical_replay_and_cached(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary = self.run_fixture(root / "cache", root / "out1")
            self.assertEqual(summary["accepted_ai_mock_candidates"], 1)
            self.assertEqual(summary["cache_misses"], 1)
            self.assertEqual(summary["paid_model_calls"], 0)
            self.assertEqual(summary["paid_tokens"], 0)
            self.assertEqual(summary["paid_spend_thb"], 0)
            self.assertEqual(summary["production_writes"], 0)
            self.assertFalse(summary["live_provider_enabled"])
            candidate = json.loads((root / "out1/field_candidates.jsonl").read_text().splitlines()[0])
            self.assertEqual(candidate["value"], 4455)
            self.assertEqual(candidate["unit"], "mm")
            self.assertEqual(candidate["document_sha256"], json.loads(DOCUMENT.read_text())["content_sha256"])
            self.assertEqual(candidate["quote"], json.loads(DOCUMENT.read_text())["content"])
            self.assertEqual(candidate["candidate_status"], "ACCEPTED_CANDIDATE")
            repeated = self.run_fixture(root / "cache", root / "out2")
            self.assertEqual(repeated["cache_hits"], 1)
            self.assertEqual(repeated["recorded_response_reads"], 0)
            self.assertEqual((root / "out1/field_candidates.jsonl").read_bytes(),
                             (root / "out2/field_candidates.jsonl").read_bytes())
            for name in ("gap_diff.json", "replay_evidence.jsonl"):
                self.assertEqual((root / "out1" / name).read_bytes(), (root / "out2" / name).read_bytes())

    def test_forged_value_is_held_even_when_cassette_schema_is_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = json.loads(DOCUMENT.read_text())
            request = _request(doc, [("atto.standard", "vehicle.length_mm")])
            response = json.loads(CASSETTE.read_text())["responses"][request.request_key]
            response["claims"][0]["value_text"] = "9999 mm"
            tape = {"schema_version": "1.0", "mode": "MOCK", "model_id": MODEL_ID,
                    "responses": {request.request_key: response}}
            tape_path = root / "tape.json"
            tape_path.write_text(json.dumps(tape))
            result = run_mock_extraction(SNAPSHOT, [DOCUMENT], tape_path, root / "cache", root / "out",
                                         confirm_mock_only=True, root=REPOSITORY_ROOT)
            self.assertEqual(result["accepted_ai_mock_candidates"], 0)
            held = result["adapter_held"][0]
            self.assertEqual(held["reason_code"], "VALUE_NOT_QUOTED")
            self.assertEqual((root / "out/field_candidates.jsonl").read_text(), "")

    def test_source_line_must_bind_claimed_trim_and_field(self):
        content = "Standard vehicle length is 4455 mm.\nPremium vehicle length is 4600 mm."
        doc = json.loads(DOCUMENT.read_text())
        doc.update(content=content, trim_ids=["atto.standard", "atto.premium"])
        pairs = [("atto.standard", "vehicle.length_mm"),
                 ("atto.premium", "vehicle.length_mm"),
                 ("atto.standard", "vehicle.width_mm"),
                 ("atto.premium", "vehicle.width_mm")]
        request = _request(doc, pairs)
        registry = {"fields": {key: {"comparison_qualifiers": []}
                               for key in ("vehicle.length_mm", "vehicle.width_mm")}}

        def check(trim_id, field_key, quote):
            response = {"schema_version": "1.0", "mode": "MOCK", "model_id": MODEL_ID,
                        "request_key": request.request_key,
                        "claims": [{"trim_id": trim_id, "field_key": field_key,
                                    "value_text": "4600 mm" if quote.startswith("Premium") else "4455 mm",
                                    "qualifiers": {}, "quote": quote,
                                    "locator": "line:2" if quote.startswith("Premium") else "line:1"}]}
            return _response_claims(response, request, doc, registry)

        accepted, held = check("atto.premium", "vehicle.length_mm", "Standard vehicle length is 4455 mm.")
        self.assertFalse(accepted)
        self.assertEqual(held[0]["reason_code"], "SOURCE_TRIM_NOT_BOUND")
        accepted, held = check("atto.standard", "vehicle.width_mm", "Standard vehicle length is 4455 mm.")
        self.assertFalse(accepted)
        self.assertEqual(held[0]["reason_code"], "SOURCE_FIELD_NOT_BOUND")
        accepted, held = check("atto.standard", "vehicle.length_mm", "Standard vehicle length is 4455 mm.")
        self.assertEqual(len(accepted), 1)
        self.assertFalse(held)
        accepted, held = check("atto.premium", "vehicle.length_mm", "Premium vehicle length is 4600 mm.")
        self.assertEqual(len(accepted), 1)
        self.assertFalse(held)

    def test_full_path_holds_value_assigned_to_sibling_trim_on_same_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = json.loads(DOCUMENT.read_text())
            content = "Standard vehicle length is 4455 mm; Extended vehicle length is 4600 mm."
            doc.update(document_id="doc-ai-sibling-attribution", local_source_id="fixture://sibling-attribution",
                       content=content, content_sha256=hashlib.sha256(content.encode()).hexdigest(),
                       trim_ids=["atto.standard", "atto.extended"])
            claim = {"trim_id": "atto.extended", "field_key": "vehicle.length_mm", "value_text": "4455 mm"}
            summary, candidates, gap_diff, pairs = self.run_full_path_claims(root, doc, [claim])
            self.assertIn((claim["trim_id"], claim["field_key"]), pairs)
            self.assertEqual(summary["adapter_held"][0]["reason_code"], "SOURCE_VALUE_ATTRIBUTION_AMBIGUOUS")
            self.assertFalse(any(row["trim_id"] == "atto.extended" and row["field_key"] == "vehicle.length_mm"
                                 and row["candidate_status"] == "ACCEPTED_CANDIDATE" for row in candidates))
            disposition = next(row for row in gap_diff["dispositions"]
                               if row["trim_id"] == "atto.extended" and row["field_key"] == "vehicle.length_mm")
            self.assertNotEqual(disposition["state"], "CANDIDATE_PROPOSED")

    def test_full_path_holds_value_assigned_to_other_field_on_same_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = json.loads(SNAPSHOT.read_text())
            snapshot["field_registry"].append({"key": "vehicle.width_mm", "group": "dimensions",
                                               "tier": "P1", "applicable_powertrains": []})
            snapshot_path = root / "snapshot.json"
            snapshot_path.write_text(json.dumps(snapshot))
            doc = json.loads(DOCUMENT.read_text())
            content = "Standard vehicle length is 4455 mm; vehicle width is 1800 mm."
            doc.update(document_id="doc-ai-field-attribution", local_source_id="fixture://field-attribution",
                       content=content, content_sha256=hashlib.sha256(content.encode()).hexdigest(),
                       trim_ids=["atto.standard"])
            claim = {"trim_id": "atto.standard", "field_key": "vehicle.width_mm", "value_text": "4455 mm"}
            summary, candidates, gap_diff, pairs = self.run_full_path_claims(root, doc, [claim], snapshot_path)
            self.assertIn((claim["trim_id"], claim["field_key"]), pairs)
            self.assertEqual(summary["adapter_held"][0]["reason_code"], "SOURCE_VALUE_ATTRIBUTION_AMBIGUOUS")
            self.assertFalse(any(row["trim_id"] == "atto.standard" and row["field_key"] == "vehicle.width_mm"
                                 and row["candidate_status"] == "ACCEPTED_CANDIDATE" for row in candidates))
            disposition = next(row for row in gap_diff["dispositions"]
                               if row["trim_id"] == "atto.standard" and row["field_key"] == "vehicle.width_mm")
            self.assertNotEqual(disposition["state"], "CANDIDATE_PROPOSED")

    def test_full_path_accepts_distinct_explicit_multi_trim_and_field_facts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = json.loads(SNAPSHOT.read_text())
            snapshot["field_registry"].append({"key": "vehicle.width_mm", "group": "dimensions",
                                               "tier": "P1", "applicable_powertrains": []})
            snapshot_path = root / "snapshot.json"
            snapshot_path.write_text(json.dumps(snapshot))
            doc = json.loads(DOCUMENT.read_text())
            content = "Standard vehicle width is 1800 mm; Extended vehicle length is 4600 mm."
            doc.update(document_id="doc-ai-positive-multi-fact", local_source_id="fixture://positive-multi-fact",
                       content=content, content_sha256=hashlib.sha256(content.encode()).hexdigest(),
                       trim_ids=["atto.standard", "atto.extended"])
            claims = [{"trim_id": "atto.standard", "field_key": "vehicle.width_mm", "value_text": "1800 mm"},
                      {"trim_id": "atto.extended", "field_key": "vehicle.length_mm", "value_text": "4600 mm"}]
            summary, candidates, _, pairs = self.run_full_path_claims(root, doc, claims, snapshot_path)
            for claim in claims:
                self.assertIn((claim["trim_id"], claim["field_key"]), pairs)
                candidate = next(row for row in candidates if row["trim_id"] == claim["trim_id"]
                                 and row["field_key"] == claim["field_key"])
                self.assertEqual(candidate["candidate_status"], "ACCEPTED_CANDIDATE")
            self.assertEqual(summary["accepted_ai_mock_candidates"], 2)
            self.assertFalse(summary["adapter_held"])

    def test_rejected_cached_response_recovers_from_corrected_cassette(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = json.loads(DOCUMENT.read_text())
            request = _request(doc, [("atto.standard", "vehicle.length_mm")])
            forged = json.loads(CASSETTE.read_text())["responses"][request.request_key]
            forged["claims"][0]["value_text"] = "9999 mm"
            bad_tape = {"schema_version": "1.0", "mode": "MOCK", "model_id": MODEL_ID,
                        "responses": {request.request_key: forged}}
            tape_path = root / "tape.json"
            tape_path.write_text(json.dumps(bad_tape))
            cache = root / "cache"
            first = run_mock_extraction(SNAPSHOT, [DOCUMENT], tape_path, cache, root / "out1",
                                        confirm_mock_only=True, root=REPOSITORY_ROOT)
            self.assertEqual(first["accepted_ai_mock_candidates"], 0)
            self.assertEqual(first["adapter_held"][0]["reason_code"], "VALUE_NOT_QUOTED")
            self.assertEqual(list(cache.glob("*.json")), [])

            # A prior release may have persisted this rejected row before the
            # validation-before-cache rule. The current run must re-evaluate it.
            cache.mkdir(parents=True, exist_ok=True)
            rejected_cache = {"request_key": request.request_key, "response": forged,
                              "response_sha256": hashlib.sha256(json.dumps(
                                  forged, ensure_ascii=False, sort_keys=True,
                                  separators=(",", ":")).encode()).hexdigest()}
            (cache / f"{request.request_key}.json").write_text(json.dumps(rejected_cache))
            corrected = json.loads(CASSETTE.read_text())
            tape_path.write_text(json.dumps(corrected))
            second = run_mock_extraction(SNAPSHOT, [DOCUMENT], tape_path, cache, root / "out2",
                                         confirm_mock_only=True, root=REPOSITORY_ROOT)
            self.assertEqual(second["accepted_ai_mock_candidates"], 1)
            self.assertEqual(second["cache_misses"], 1)
            self.assertEqual(second["recorded_response_reads"], 1)
            self.assertEqual(second["cache_hits"], 0)

    def test_invalid_provider_mode_and_missing_acknowledgement_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tape = json.loads(CASSETTE.read_text())
            tape["mode"] = "LIVE_LIMITED"
            tape_path = root / "tape.json"
            tape_path.write_text(json.dumps(tape))
            with self.assertRaisesRegex(ExtractionError, "MOCK_TAPE_MODE_OR_MODEL_INVALID"):
                run_mock_extraction(SNAPSHOT, [DOCUMENT], tape_path, root / "cache", root / "out",
                                    confirm_mock_only=True, root=REPOSITORY_ROOT)
            with self.assertRaisesRegex(ExtractionError, "MOCK_ONLY_ACKNOWLEDGEMENT_REQUIRED"):
                run_mock_extraction(SNAPSHOT, [DOCUMENT], CASSETTE, root / "cache", root / "out",
                                    confirm_mock_only=False, root=REPOSITORY_ROOT)

    def test_cache_corruption_stops_without_provider_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            self.run_fixture(cache, root / "out1")
            cache_file = next(cache.glob("*.json"))
            cache_file.write_text("{}\n")
            with self.assertRaisesRegex(ExtractionError, "CACHE_INTEGRITY_FAILURE_STOP"):
                self.run_fixture(cache, root / "out2")

    def test_deterministic_candidate_suppresses_provider_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = json.loads(DOCUMENT.read_text())
            doc["content"] = "claim|vehicle.length_mm|atto.standard|4455 mm"
            doc["content_sha256"] = hashlib.sha256(doc["content"].encode()).hexdigest()
            document_path = root / "deterministic.json"
            document_path.write_text(json.dumps(doc))
            tape_path = root / "empty-tape.json"
            tape_path.write_text(json.dumps({"schema_version": "1.0", "mode": "MOCK",
                                             "model_id": MODEL_ID, "responses": {}}))
            result = run_mock_extraction(SNAPSHOT, [document_path], tape_path, root / "cache", root / "out",
                                         confirm_mock_only=True, root=REPOSITORY_ROOT)
            self.assertEqual(result["recorded_response_reads"], 0)
            self.assertEqual(result["cache_misses"], 0)
            self.assertEqual(result["skipped_no_open_gap"], 1)
            self.assertEqual(result["paid_model_calls"], 0)

    def test_mock_provider_has_a_hard_three_miss_run_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs, responses = [], {}
            base = json.loads(DOCUMENT.read_text())
            pair = [("atto.standard", "vehicle.length_mm")]
            for index in range(4):
                doc = dict(base)
                doc["document_id"] = f"doc-ai-cap-{index}"
                doc["local_source_id"] = f"fixture://doc-ai-cap-{index}"
                doc["content"] = f"BYD ATTO 3 Standard overall vehicle length is 4455 mm. Copy {index}."
                doc["content_sha256"] = hashlib.sha256(doc["content"].encode()).hexdigest()
                path = root / f"doc-{index}.json"
                path.write_text(json.dumps(doc))
                docs.append(path)
                request = _request(doc, pair)
                responses[request.request_key] = {
                    "schema_version": "1.0", "mode": "MOCK", "model_id": MODEL_ID,
                    "request_key": request.request_key,
                    "claims": [{"field_key": pair[0][1], "trim_id": pair[0][0], "value_text": "4455 mm",
                                "qualifiers": {}, "quote": doc["content"], "locator": "line:1"}],
                }
            tape = {"schema_version": "1.0", "mode": "MOCK", "model_id": MODEL_ID, "responses": responses}
            tape_path = root / "tape.json"
            tape_path.write_text(json.dumps(tape))
            result = run_mock_extraction(SNAPSHOT, docs, tape_path, root / "cache", root / "out",
                                         confirm_mock_only=True, root=REPOSITORY_ROOT)
            self.assertEqual(result["recorded_response_reads"], 3)
            self.assertTrue(result["mock_request_cap_reached"])
            self.assertIn("MOCK_REQUEST_CAP_REACHED_STOP", {row["reason_code"] for row in result["adapter_held"]})
            self.assertEqual(result["paid_model_calls"], 0)

    def test_claim_response_contract_is_pinned_to_checked_in_tape(self):
        doc = json.loads(DOCUMENT.read_text())
        req = _request(doc, [("atto.standard", "vehicle.length_mm")])
        self.assertEqual(req.request_key, "2227ba49e0977bd4fc883ce2e9a2fbecf97261c56834e4ed6128c0255fc69d5d")
        tape = json.loads(CASSETTE.read_text())
        self.assertEqual(set(tape["responses"]), {req.request_key})
        self.assertEqual(hashlib.sha256(doc["content"].encode()).hexdigest(), doc["content_sha256"])


if __name__ == "__main__":
    unittest.main()
