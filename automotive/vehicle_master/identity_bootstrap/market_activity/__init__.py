"""Market-activity classification: a separate ROUTING step that runs beside Identity Bootstrap, never inside it.

It answers "does this identity belong in the current discovery lane?", not "does it exist?". Nothing in `engine/` imports it (a test enforces this)
and registration counts remain forbidden as identity evidence (SPEC invariant I3)."""
from .classify import STATES, classify, load_policy, resolve_series  # noqa: F401
