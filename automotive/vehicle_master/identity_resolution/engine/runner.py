"""Executable, read-only Identity Resolution contract v1 smoke boundary.

This first integration milestone deliberately executes the already-tested
reference evaluator rather than creating a second, divergent matching
algorithm. It is NOT a production resolver nor independent validation of its
provisional thresholds. Output is evidence for QA only; no write operation is
executed or authorized even when a decision says AUTO.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from typing import Any, Mapping

from identity_resolution.contract import loader
from identity_resolution.providers.base import validate_snapshot
from identity_resolution.calibration.ref_eval_resolve import resolve as evaluate


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def run_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one provider-neutral snapshot and produce an auditable DRY RUN.

    Caller supplies an already assembled snapshot, not production credentials.
    Refuse binding mode unconditionally. Preserve original reason codes,
    comparisons, and mapped target IDs for inspection.
    """
    if loader.load_adoption()["binding"] is not False:
        raise RuntimeError("OFFLINE_ONLY: adopted policy is outside the authority of this runner")
    if not isinstance(snapshot, dict):
        raise ValueError("snapshot must be a JSON object")
    validate_snapshot(snapshot)
    digest = hashlib.sha256(_canonical_bytes(snapshot)).hexdigest()
    output = evaluate(snapshot)
    envelope: dict[str, Any] = {
        "schema_version": "ir-offline-smoke/1",
        "mode": "OFFLINE_READ_ONLY",
        "contract_version": "v1",
        "policy_binding": False,
        "snapshot_sha256": digest,
        "provider": snapshot["provider"],
        "source_version": snapshot["source_version"],
        "as_of_period": snapshot["as_of_period"],
        "evaluation_backend": "contract_calibration_reference",
        "writes_executed": 0,
        "canonical_mutations": 0,
    }
    if "refusal" in output:
        return {**envelope, "status": "REFUSED", "refusal": output["refusal"],
                "summary": {"subjects": len(snapshot["subjects"]), "decisions": 0}}
    decisions = []
    for sid, decision in sorted(output["decisions"].items()):
        if decision.get("policy_binding") is not False:
            raise RuntimeError("OFFLINE_ONLY: evaluation attempted to claim binding authority")
        row = {k: v for k, v in decision.items() if not k.startswith("_") and k != "writes"}
        # A write PLAN is diagnostic information, never an executed write.
        row["advisory_write_plan"] = decision.get("writes", [])
        decisions.append({"subject_id": sid, **row})
    counts = Counter(row["outcome"] for row in decisions)
    return {
        **envelope,
        "status": "EVALUATED",
        "summary": {"subjects": len(snapshot["subjects"]), "decisions": len(decisions),
                    "outcomes": {k: counts[k] for k in sorted(counts)},
                    "structural_operations": len(output["operations"])},
        "decisions": decisions,
        "structural_operations": output["operations"],
    }
