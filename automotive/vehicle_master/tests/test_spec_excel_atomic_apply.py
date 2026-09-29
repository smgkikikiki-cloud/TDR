from pathlib import Path
from types import SimpleNamespace

import pytest

import tools.import_vehicle_specs as importer


class _FakePipeline:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)

    def apply(self, batch):
        relative = Path("2026/product") / f"{batch['batch_id']}.json"
        target = self.data_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(batch["batch_id"], encoding="utf-8")
        if batch.get("fail"):
            raise RuntimeError("later batch rejected")
        return SimpleNamespace(
            batch_id=batch["batch_id"],
            status="APPLIED",
            idempotent_replay=False,
            changed_files=(str(relative),),
        )


def test_later_batch_failure_leaves_live_tree_untouched(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    sentinel = data_dir / "sentinel.txt"
    sentinel.write_text("original", encoding="utf-8")
    monkeypatch.setattr(importer, "CanonicalInputPipeline", _FakePipeline)

    with pytest.raises(RuntimeError, match="later batch rejected"):
        importer._apply_batches_atomically([
            {"batch_id": "first"},
            {"batch_id": "second", "fail": True},
        ], data_dir=data_dir)

    assert sentinel.read_text(encoding="utf-8") == "original"
    assert not (data_dir / "2026/product/first.json").exists()
    assert not (data_dir / "2026/product/second.json").exists()


def test_all_batches_promote_only_after_success(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(importer, "CanonicalInputPipeline", _FakePipeline)

    applied, changed = importer._apply_batches_atomically([
        {"batch_id": "first"},
        {"batch_id": "second"},
    ], data_dir=data_dir)

    assert [row["batch_id"] for row in applied] == ["first", "second"]
    assert changed == ["2026/product/first.json", "2026/product/second.json"]
    assert (data_dir / "2026/product/first.json").read_text(encoding="utf-8") == "first"
    assert (data_dir / "2026/product/second.json").read_text(encoding="utf-8") == "second"
