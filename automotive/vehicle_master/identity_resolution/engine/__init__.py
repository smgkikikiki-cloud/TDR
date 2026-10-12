"""Read-only executable boundary for Identity Resolution v1.

This is an offline integration milestone. The evaluator is still the
contract's calibration reference until an independently verified replacement
is developed. No persistence, approvals or production imports live here.
"""
from .runner import run_snapshot

__all__ = ["run_snapshot"]
