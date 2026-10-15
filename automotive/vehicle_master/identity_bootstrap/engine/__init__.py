"""Identity Bootstrap v1 engine -- offline, pure, no I/O.

``decide(snapshot, policy, registry)`` implements contract/v1/SPEC.md. It never writes: a CREATE_IDENTITY carries a write plan, nothing more.
Conformance with the golden corpus (and with the independent test oracle) is enforced by tests/identity_bootstrap/test_ib_engine_conformance.py.
"""
from .decide import Refusal, decide
from .plan import finalize
from .allocate import allocate
from .fingerprint import canonical_json, policy_digest, sha

__all__ = ["Refusal", "decide", "finalize", "allocate", "canonical_json", "policy_digest", "sha"]
