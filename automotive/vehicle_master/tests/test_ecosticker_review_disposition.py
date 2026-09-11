import json
from pathlib import Path
import shutil

import pytest

from vehreg.catalog import DATA_DIR
from vehreg.eco_review_write import upsert_review_dispositions
from vehreg.ecosticker_ingest import ECOIngestError, load_normalized_snapshot
from vehreg.input_pipeline import CanonicalInputError, CanonicalInputPipeline


SNAPSHOT_DATE = "2026-09-08"
AGENT_SOURCE = "d744d9f3-d393-4ac3-b441-17a022098fed"


@pytest.fixture
def local_data(tmp_path):
    shutil.copytree(DATA_DIR / "2026", tmp_path / "2026")
    return tmp_path


def another_source(data_dir):
    return next(
        row["source_id"]
        for row in load_normalized_snapshot(data_dir, 2026, snapshot_date=SNAPSHOT_DATE)
        if row["source_id"] != AGENT_SOURCE
    )


def review_payload(data_dir):
    path = Path(data_dir) / "2026/ingest/ecosticker/review/2026-09-08.json"
    return json.loads(path.read_text(encoding="utf-8"))


def by_source(payload):
    return {row["source_id"]: row for row in payload["decisions"]}


def test_review_disposition_preserves_replaces_and_reopens(local_data):
    source_id = another_source(local_data)
    before = by_source(review_payload(local_data))
    assert before[AGENT_SOURCE]["reviewer"] == "agent-proposed"

    result = upsert_review_dispositions(
        data_dir=local_data,
        year=2026,
        snapshot_date=SNAPSHOT_DATE,
        source_ids=[source_id],
        action="reject",
        reviewer="Human Reviewer",
        reviewed_at="2026-09-11",
        notes="Not a retail MarketTrim identity",
        write=True,
    )
    assert result["written"] is True
    after = by_source(review_payload(local_data))
    assert after[AGENT_SOURCE] == before[AGENT_SOURCE]
    assert after[source_id] == {
        "source_id": source_id,
        "action": "reject",
        "trim_id": "",
        "reviewer": "Human Reviewer",
        "origin": "human",
        "reviewed_at": "2026-09-11",
        "notes": "Not a retail MarketTrim identity",
    }

    second = upsert_review_dispositions(
        data_dir=local_data,
        year=2026,
        snapshot_date=SNAPSHOT_DATE,
        source_ids=[source_id],
        action="defer",
        reviewer="Human Reviewer",
        reviewed_at="2026-09-12",
        notes="Need brochure confirmation",
        write=True,
    )
    assert second["written"] is True
    replaced = by_source(review_payload(local_data))
    assert len(replaced) == len(after)
    assert replaced[source_id]["action"] == "defer"
    assert replaced[source_id]["reviewed_at"] == "2026-09-12"

    reopened = upsert_review_dispositions(
        data_dir=local_data,
        year=2026,
        snapshot_date=SNAPSHOT_DATE,
        source_ids=[source_id],
        action="reopen",
        reviewer="Human Reviewer",
        reviewed_at="2026-09-13",
        notes="New brochure evidence arrived",
        write=True,
    )
    assert reopened["written"] is True
    final = by_source(review_payload(local_data))
    assert source_id not in final
    assert final[AGENT_SOURCE] == before[AGENT_SOURCE]


def test_review_disposition_rejects_unknown_source(local_data):
    with pytest.raises(ECOIngestError, match="unknown ECO source IDs"):
        upsert_review_dispositions(
            data_dir=local_data,
            year=2026,
            snapshot_date=SNAPSHOT_DATE,
            source_ids=["00000000-0000-0000-0000-000000000000"],
            action="reject",
            reviewer="Human Reviewer",
            reviewed_at="2026-09-11",
            write=True,
        )


def review_batch(source_id, *, actor="TDR Human", source_kind="ECO", action="defer", batch_id="eco-review-test-1"):
    return {
        "schema_version": 1,
        "batch_id": batch_id,
        "year": 2026,
        "source": {"kind": source_kind, "ref": "ecosticker:snapshot:2026-09-08"},
        "actor": actor,
        "reason": "Reviewed ECO candidate",
        "submitted_at": "2026-09-11T09:30:00+07:00",
        "commands": [{
            "operation": "UPSERT_ECO_REVIEW",
            "payload": {
                "snapshot_date": SNAPSHOT_DATE,
                "action": action,
                "source_ids": [source_id],
                "notes": "Need exact grade confirmation",
            },
        }],
    }


def test_input_pipeline_stages_human_review_without_serving_mutation(local_data):
    source_id = another_source(local_data)
    pipeline = CanonicalInputPipeline(local_data)
    batch = review_batch(source_id)
    result = pipeline.apply(batch)
    assert result.idempotent_replay is False
    assert any(path.endswith("ingest/ecosticker/review/2026-09-08.json") for path in result.changed_files)
    decision = by_source(review_payload(local_data))[source_id]
    assert decision["action"] == "defer"
    assert decision["reviewer"] == "TDR Human"
    assert decision["origin"] == "human"
    assert decision["reviewed_at"] == "2026-09-11"
    assert not any("registr" in path.lower() for path in result.changed_files)

    replay = pipeline.apply(batch)
    assert replay.idempotent_replay is True

    reopened = pipeline.apply(review_batch(
        source_id, action="reopen", batch_id="eco-review-test-reopen",
    ))
    assert reopened.idempotent_replay is False
    assert source_id not in by_source(review_payload(local_data))


def test_input_pipeline_refuses_nonhuman_actor_and_non_eco_source(local_data):
    source_id = another_source(local_data)
    with pytest.raises(CanonicalInputError, match="HUMAN actor"):
        CanonicalInputPipeline(local_data).apply(review_batch(
            source_id, actor="agent-proposed", batch_id="eco-review-agent",
        ))
    with pytest.raises(CanonicalInputError, match="source.kind ECO"):
        CanonicalInputPipeline(local_data).apply(review_batch(
            source_id, source_kind="ADMIN", batch_id="eco-review-admin-source",
        ))
