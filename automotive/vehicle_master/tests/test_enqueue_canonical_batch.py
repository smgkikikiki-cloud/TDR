"""tools/enqueue_canonical_batch.py -- the thin GitHub Actions bridge that
lets a session with no Supabase credentials still hand a prepared batch to
canonical_input_batches. These tests cover the pure validation/
normalization/hash logic and the duplicate-status branching (network calls
mocked), not a live Supabase round trip.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import tools.enqueue_canonical_batch as bridge
from tools.enqueue_canonical_batch import (
    EnqueueError,
    _canonical,
    _js_number,
    build_row,
    enqueue,
    normalize_and_validate,
)


def _minimal_payload(**overrides):
    payload = {
        "schema_version": 1,
        "batch_id": "ev-retail-repair-lot-02-2026-09-27",
        "year": 2026,
        "source": {"kind": "ADMIN"},
        "commands": [
            {"operation": "REPLACE_CURRENT_RETAIL_SET",
             "payload": {"model_id": "volvo.ec40", "trim_ids": ["x"]}},
        ],
    }
    payload.update(overrides)
    return payload


# --- normalization / actor provenance ---

def test_valid_payload_normalizes_batch_key_and_authenticated_actor():
    normalized, batch_key, kind, actor = normalize_and_validate(
        _minimal_payload(), authenticated_actor="octocat")
    assert batch_key == "ev-retail-repair-lot-02-2026-09-27"
    assert kind == "ADMIN"
    assert actor == "octocat"
    assert normalized["actor"] == "octocat"
    assert normalized["commands"][0]["actor"] == "octocat"
    assert normalized["commands"][0]["submitted_at"]
    assert normalized["source"] == {"kind": "ADMIN"}


def test_authenticated_actor_overwrites_payload_actor_spoof_attempt():
    """The payload cannot claim to be "Owner" -- only the GitHub user who
    actually dispatched this workflow is trusted, exactly like the admin
    server action overwrites actor from the authenticated session rather
    than trusting the submitted form/JSON."""
    normalized, _, _, actor = normalize_and_validate(
        _minimal_payload(actor="Owner",
                         commands=[{"operation": "REPLACE_CURRENT_RETAIL_SET",
                                    "actor": "Owner",
                                    "payload": {"model_id": "volvo.ec40", "trim_ids": ["x"]}}]),
        authenticated_actor="real-github-user",
    )
    assert actor == "real-github-user"
    assert normalized["actor"] == "real-github-user"
    assert normalized["commands"][0]["actor"] == "real-github-user"


def test_missing_authenticated_actor_is_rejected():
    with pytest.raises(EnqueueError, match="authenticated actor"):
        normalize_and_validate(_minimal_payload(), authenticated_actor="")


# --- shallow field checks (fail fast, before the deep validator) ---

def test_rejects_wrong_schema_version():
    with pytest.raises(EnqueueError, match="schema_version"):
        normalize_and_validate(_minimal_payload(schema_version=2), authenticated_actor="x")


def test_rejects_invalid_batch_id():
    with pytest.raises(EnqueueError, match="batch_id"):
        normalize_and_validate(_minimal_payload(batch_id="bad key!"), authenticated_actor="x")


def test_rejects_empty_commands():
    with pytest.raises(EnqueueError, match="commands"):
        normalize_and_validate(_minimal_payload(commands=[]), authenticated_actor="x")


def test_rejects_too_many_commands():
    with pytest.raises(EnqueueError, match="commands"):
        normalize_and_validate(
            _minimal_payload(commands=[{"operation": "X"}] * 501), authenticated_actor="x")


def test_rejects_registration_source_kind():
    with pytest.raises(EnqueueError, match="registration"):
        normalize_and_validate(
            _minimal_payload(source={"kind": "DLT"}), authenticated_actor="x")


def test_rejects_unsupported_source_kind():
    with pytest.raises(EnqueueError, match="source.kind"):
        normalize_and_validate(
            _minimal_payload(source={"kind": "NOT_A_KIND"}), authenticated_actor="x")


def test_rejects_non_object_payload():
    with pytest.raises(EnqueueError, match="JSON object"):
        normalize_and_validate(["not", "an", "object"], authenticated_actor="x")


# --- full canonical-input validation (vehreg.input_pipeline.CanonicalInputBatch) ---

def test_rejects_unknown_operation_via_full_validator():
    with pytest.raises(EnqueueError, match="canonical input validation"):
        normalize_and_validate(
            _minimal_payload(commands=[{"operation": "DELETE_EVERYTHING", "payload": {}}]),
            authenticated_actor="x",
        )


def test_rejects_duplicate_command_id_via_full_validator():
    command = {
        "command_id": "dup-1", "operation": "REPLACE_CURRENT_RETAIL_SET",
        "payload": {"model_id": "volvo.ec40", "trim_ids": ["x"]},
    }
    with pytest.raises(EnqueueError, match="duplicate command_id"):
        normalize_and_validate(
            _minimal_payload(commands=[dict(command), dict(command)]),
            authenticated_actor="x",
        )


def test_rejects_malformed_special_operation_payload_via_full_validator():
    """REPLACE_CURRENT_RETAIL_SET with no trim_ids is a payload the shallow
    top-level checks above cannot see -- only CanonicalInputBatch.from_dict's
    per-operation validator catches it."""
    with pytest.raises(EnqueueError, match="canonical input validation"):
        normalize_and_validate(
            _minimal_payload(commands=[{
                "operation": "REPLACE_CURRENT_RETAIL_SET",
                "payload": {"model_id": "volvo.ec40"},
            }]),
            authenticated_actor="x",
        )


def test_rejects_admin_only_special_operation_from_non_admin_source():
    with pytest.raises(EnqueueError, match="canonical input validation"):
        normalize_and_validate(
            _minimal_payload(source={"kind": "OEM"}),
            authenticated_actor="x",
        )


def test_valid_payload_passes_full_validation_unmutated_semantically():
    # Sanity check that a genuinely valid batch is NOT rejected by the
    # deeper validator -- the previous tests would be meaningless otherwise.
    normalized, *_ = normalize_and_validate(_minimal_payload(), authenticated_actor="x")
    assert normalized["commands"][0]["operation"] == "REPLACE_CURRENT_RETAIL_SET"


# --- build_row ---

def test_build_row_has_exactly_the_expected_columns():
    normalized, batch_key, kind, actor = normalize_and_validate(
        _minimal_payload(source={"kind": "ADMIN", "ref": "owner-note"}),
        authenticated_actor="octocat",
    )
    row = build_row(normalized, batch_key=batch_key, source_kind=kind, actor=actor)
    assert set(row) == {
        "domain", "batch_key", "source_kind", "source_ref", "payload",
        "payload_sha256", "item_count", "actor", "status",
    }
    assert row["domain"] == "VEHICLE_MARKET"
    assert row["batch_key"] == batch_key
    assert row["source_kind"] == "ADMIN"
    assert row["source_ref"] == "owner-note"
    assert row["item_count"] == 1
    assert row["actor"] == "octocat"
    assert row["status"] == "QUEUED"
    assert len(row["payload_sha256"]) == 64
    assert row["payload"]["batch_id"] == batch_key


def test_build_row_source_ref_defaults_to_none():
    normalized, batch_key, kind, actor = normalize_and_validate(
        _minimal_payload(), authenticated_actor="x")
    row = build_row(normalized, batch_key=batch_key, source_kind=kind, actor=actor)
    assert row["source_ref"] is None


def test_same_payload_hashes_identically_regardless_of_key_order():
    p1 = _minimal_payload()
    p2 = {"batch_id": p1["batch_id"], "schema_version": 1, "commands": p1["commands"],
          "source": p1["source"], "year": p1["year"]}
    n1, _, _, _ = normalize_and_validate(p1, authenticated_actor="x")
    n2, _, _, _ = normalize_and_validate(p2, authenticated_actor="x")
    # submitted_at is defaulted to "now" independently for each call, so
    # strip it before comparing the rest of the hash-relevant shape.
    del n1["submitted_at"], n2["submitted_at"]
    del n1["commands"][0]["submitted_at"], n2["commands"][0]["submitted_at"]
    assert _canonical(n1) == _canonical(n2)


# --- number formatting parity with JS's JSON.stringify (ECMA-262 Number::toString) ---

@pytest.mark.parametrize("value,expected", [
    (1, "1"),
    (1.0, "1"),               # JS has one number type: 1.0 and 1 stringify identically
    (0, "0"),
    (0.0, "0"),
    (-0.0, "0"),               # JSON.stringify(-0) === "0" in JS
    (1.5, "1.5"),
    (-1.5, "-1.5"),
    (100, "100"),
    (1699000, "1699000"),      # the shape of every real price in this repo's payloads
    (1e21, "1e+21"),           # >= 1e21 switches to scientific notation in JS
    (1e20, "1" + "0" * 20),    # just below the threshold: stays fixed notation
    (1e-6, "0.000001"),        # boundary: stays fixed notation
    (1e-7, "1e-7"),            # just past the boundary: scientific, no zero-padded exponent
    (123.456, "123.456"),
    (0.1, "0.1"),
    (-0.1, "-0.1"),
    (999999999999999900000.0, "999999999999999900000"),
    (5e-324, "5e-324"),                                   # smallest positive denormal double
    (1.7976931348623157e+308, "1.7976931348623157e+308"),  # largest finite double
])
def test_js_number_matches_ecma262_number_to_string(value, expected):
    """Every (value, expected) pair here was cross-checked against real
    Node.js `JSON.stringify(value)` output, not hand-derived only."""
    assert _js_number(value) == expected


def test_canonical_hash_is_key_order_independent():
    a = {"b": 2, "a": 1, "c": [3, {"y": 2, "x": 1}]}
    b = {"a": 1, "c": [3, {"x": 1, "y": 2}], "b": 2}
    assert _canonical(a) == _canonical(b)
    assert _canonical(a) == '{"a":1,"b":2,"c":[3,{"x":1,"y":2}]}'


def test_canonical_treats_integer_valued_float_like_javascript_would():
    """A payload field written as 1.0 (a Python float) must hash the same
    as one written as 1 (a Python int) -- JS has no such distinction, so
    lib/canonical-input-queue.ts's hash of the "same" batch never would
    either."""
    assert _canonical({"amount_thb": 1.0}) == _canonical({"amount_thb": 1})
    assert _canonical([1.0, -0.0]) == '[1,0]'


def test_canonical_bool_is_not_treated_as_a_number():
    assert _canonical(True) == "true"
    assert _canonical(False) == "false"
    assert _canonical(True) != _canonical(1)


# --- duplicate-status branching (network mocked) ---

def _fake_insert_row_conflict(row):
    return 409, {"code": "23505", "message": "duplicate key"}


@pytest.mark.parametrize("existing_status,expected_wake", [
    ("QUEUED", True),
    ("PROCESSING", False),
    ("STAGED", False),
    ("PUBLISHED", False),
    ("FAILED", False),
    ("REJECTED", False),
    ("NEEDS_REVIEW", False),
])
def test_duplicate_replay_reports_real_status_and_correct_wake_decision(
        monkeypatch, tmp_path: Path, existing_status, expected_wake):
    payload = _minimal_payload()
    payload_file = tmp_path / "payload.json"
    result_file = tmp_path / "result.json"
    import json as _json
    payload_file.write_text(_json.dumps(payload), encoding="utf-8")

    captured_row = {}

    def fake_insert(row):
        captured_row.update(row)
        return _fake_insert_row_conflict(row)

    def fake_existing(batch_key):
        return {
            "id": "existing-row-id",
            "payload_sha256": captured_row["payload_sha256"],
            "status": existing_status,
        }

    monkeypatch.setattr(bridge, "_insert_row", fake_insert)
    monkeypatch.setattr(bridge, "_existing_batch_row", fake_existing)

    enqueue(payload_file, authenticated_actor="octocat", result_file=result_file)
    result = _json.loads(result_file.read_text(encoding="utf-8"))

    assert result["status"] == existing_status  # never coerced to "QUEUED"
    assert result["duplicate"] is True
    assert result["existing_batch_id"] == "existing-row-id"
    assert result["should_wake_worker"] is expected_wake


def test_duplicate_with_different_content_is_rejected_before_any_wake(
        monkeypatch, tmp_path: Path):
    payload = _minimal_payload()
    payload_file = tmp_path / "payload.json"
    result_file = tmp_path / "result.json"
    import json as _json
    payload_file.write_text(_json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(bridge, "_insert_row", lambda row: (409, {"code": "23505"}))
    monkeypatch.setattr(bridge, "_existing_batch_row",
                        lambda batch_key: {"id": "x", "payload_sha256": "different" * 8,
                                            "status": "QUEUED"})

    with pytest.raises(EnqueueError, match="different content"):
        enqueue(payload_file, authenticated_actor="octocat", result_file=result_file)


def test_fresh_insert_always_wakes_worker(monkeypatch, tmp_path: Path):
    payload = _minimal_payload()
    payload_file = tmp_path / "payload.json"
    result_file = tmp_path / "result.json"
    import json as _json
    payload_file.write_text(_json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(bridge, "_insert_row", lambda row: (201, [row]))

    enqueue(payload_file, authenticated_actor="octocat", result_file=result_file)
    result = _json.loads(result_file.read_text(encoding="utf-8"))
    assert result["status"] == "QUEUED"
    assert result["duplicate"] is False
    assert result["should_wake_worker"] is True
