"""tools.publish_canonical.verify_serving(): a release row existing, and
even the serving projection being non-empty, is not proof that the exact
release_id being verified is the one currently serving. A release that
was once ACTIVE and has since been SUPERSEDED by something newer still
has a row, and current_market_trims is still non-empty (from whatever IS
active) -- the original check only asked those two questions, so a retry
of an exact-publish operation for a since-superseded release_id could
report success while a different release actually serves production.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from tools import publish_canonical


def _fake_get(responses: dict[str, list[dict]]):
    def _get(path: str):
        for prefix, rows in responses.items():
            if path.startswith(prefix):
                return rows
        raise AssertionError(f"unexpected path {path}")
    return _get


def test_verify_serving_succeeds_when_the_release_is_the_active_one():
    release_id = "vehicle-2026-aaaaaaaaaaaaaaaa"
    fake = _fake_get({
        "canonical_vehicle_releases": [
            {"release_id": release_id, "status": "ACTIVE", "activated_at": "2026-09-23T00:00:00Z"}
        ],
        "canonical_vehicle_state": [{"active_release_id": release_id}],
        "current_market_trims": [{"canonical_id": "toyota.camry.trim"}],
    })
    with patch("tools.publish_canonical._get", side_effect=fake):
        result = publish_canonical.verify_serving(release_id)
    assert result["release_id"] == release_id
    assert result["status"] == "ACTIVE"


def test_verify_serving_fails_when_the_release_has_been_superseded():
    # The exact regression this fixes: a release_id that really was
    # published, and really does have a row, and current_market_trims is
    # really non-empty -- but of a DIFFERENT, newer release. The original
    # verify_serving() only checked those two things and would have
    # reported this as a successful publish of release_id.
    release_id = "vehicle-2026-aaaaaaaaaaaaaaaa"
    newer_release_id = "vehicle-2026-bbbbbbbbbbbbbbbb"
    fake = _fake_get({
        "canonical_vehicle_releases": [
            {"release_id": release_id, "status": "SUPERSEDED", "activated_at": "2026-09-20T00:00:00Z"}
        ],
        "canonical_vehicle_state": [{"active_release_id": newer_release_id}],
        "current_market_trims": [{"canonical_id": "toyota.camry.trim"}],
    })
    with patch("tools.publish_canonical._get", side_effect=fake):
        with pytest.raises(SystemExit, match="not the active release"):
            publish_canonical.verify_serving(release_id)


def test_verify_serving_fails_when_the_release_row_is_active_but_the_state_pointer_disagrees():
    # Defense in depth: even if a caller (or a bug) left the release row's
    # own status stale at ACTIVE, canonical_vehicle_state.active_release_id
    # is the actual serving pointer activate_vehicle_release/
    # publish_vehicle_release flip atomically -- it is the one that must
    # agree, not just the row's own status column.
    release_id = "vehicle-2026-aaaaaaaaaaaaaaaa"
    fake = _fake_get({
        "canonical_vehicle_releases": [
            {"release_id": release_id, "status": "ACTIVE", "activated_at": "2026-09-20T00:00:00Z"}
        ],
        "canonical_vehicle_state": [{"active_release_id": "vehicle-2026-cccccccccccccccc"}],
        "current_market_trims": [{"canonical_id": "toyota.camry.trim"}],
    })
    with patch("tools.publish_canonical._get", side_effect=fake):
        with pytest.raises(SystemExit, match="not the active release"):
            publish_canonical.verify_serving(release_id)
