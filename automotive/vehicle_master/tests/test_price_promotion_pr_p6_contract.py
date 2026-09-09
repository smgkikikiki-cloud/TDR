from pathlib import Path


def test_price_pr_wrapper_keeps_human_merge_and_local_gates() -> None:
    source = (Path(__file__).parents[1] / "tools" / "price_promotion_pr.py").read_text(
        encoding="utf-8"
    )

    assert "working tree must be clean" in source
    assert "pricefeed_guard.py" in source
    assert '"-m", "pytest", "-q"' in source
    assert '"-m", "vehreg", "market", "validate"' in source
    assert "publish_serving_projection.py" in source
    assert '"gh", "pr", "create"' in source
    assert "auto-merge" not in source.lower()
