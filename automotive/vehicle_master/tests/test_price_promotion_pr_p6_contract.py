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


def test_pricebot_pull_requests_are_guarded_again_in_github_ci() -> None:
    repo_root = Path(__file__).parents[3]
    workflow = (repo_root / ".github" / "workflows" / "test-consolidated.yml").read_text(
        encoding="utf-8"
    )

    assert "startsWith(github.head_ref, 'pricebot/')" in workflow
    assert "Fetch base tree for automated price PR" in workflow
    assert "Guard automated price PR" in workflow
    assert "python tools/pricefeed_guard.py --base" in workflow
