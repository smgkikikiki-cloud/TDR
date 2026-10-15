"""Canonical JSON and SHA-256 fingerprints (SPEC §12.3)."""
from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def policy_digest(policy: dict) -> str:
    return sha({k: v for k, v in policy.items() if k != "provenance"})
