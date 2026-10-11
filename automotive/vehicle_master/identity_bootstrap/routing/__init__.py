"""Review routing and the pre-activation dispatch boundary. A pure, offline projection of (Bootstrap decision, market-activity state, review evidence) onto downstream lanes.

It runs AFTER the engine and cannot change an outcome, an identity or a write plan; nothing in `engine/`, `providers/` or `contract/` may reference it (tested)."""
from .dispatch import CURRENT, LANES, current_dispatch, dispatch_all, project  # noqa: F401
from .signals import review_flags  # noqa: F401
