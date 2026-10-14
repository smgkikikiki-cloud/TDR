"""Historical policy baselines: run the reference evaluator under a PREVIOUS draft revision's policy, without touching the live policy file.

Why this exists. The accepted rev 4 evidence (the pair-level relation export, the calibration outputs and owner review sheet, the lexical-pass results and the Owner Decision Pack)
was produced under the rev 4 policy. Rev 5 (owner decision `od_related_brand_auto_eligible`, 2026-10-12) lets a RELATED brand reach AUTO and types JETOUR / Chery as RELATED. That evidence is
kept byte for byte as a VERSIONED BASELINE and is never silently rewritten: `calibration/baselines/rev4/` holds the exact rev 4 `policy.yaml` and `ref_eval_core.py` (their sha256s are the
ones the export's MANIFEST pins), and `rev4_baseline()` re-creates the rev 4 behaviour on demand so that the baseline artifacts can still be verified and compared with rev 5.

    with rev4_baseline():
        ...evaluate exactly as the rev 4 contract did...

The context swaps the CONTENT of the evaluator's policy dict in place (every module shares that one object), rebuilds the evaluator's brand-class tables, and makes `loader.load_policy()`
return the rev 4 policy; on exit everything is restored. `EXPECTED_DELTA` pins what differs between the rev 4 baseline and the live policy, so any unexpected drift is an error rather than a
silent change of baseline.
"""
from __future__ import annotations

import contextlib
import copy
from pathlib import Path

from identity_resolution.contract import loader

from . import ref_eval_core as P

BASELINES = Path(__file__).resolve().parent / "baselines"
REV4_POLICY = BASELINES / "rev4" / "policy.yaml"
REV4_EVALUATOR = BASELINES / "rev4" / "ref_eval_core.py"
#: The only policy keys that differ between the rev 4 baseline and the rev 5 draft.
EXPECTED_DELTA = frozenset({"policy.revision", "candidates.brand_relations_auto_eligible", "aliases.brand", "alias_provenance"})


def _load(path: Path) -> dict:
    import yaml
    with path.open(encoding="utf-8") as handle:
        return yaml.load(handle, Loader=loader._StrictLoader)


def rev4_policy() -> dict:
    return _load(REV4_POLICY)


def flatten(node, prefix="") -> dict:
    out = {}
    if isinstance(node, dict):
        for k, v in node.items():
            out.update(flatten(v, f"{prefix}.{k}" if prefix else str(k)))
        return out
    out[prefix] = node
    return out


def delta(live: dict, base: dict) -> set[str]:
    """Policy keys (at depth 2, or the whole block for the alias lists) whose values differ."""
    keys = set()
    a, b = flatten(live), flatten(base)
    for k in set(a) | set(b):
        if a.get(k) != b.get(k):
            keys.add(k)
    collapsed = set()
    for k in keys:
        collapsed.add("aliases.brand" if k.startswith("aliases.brand") else "alias_provenance" if k.startswith("alias_provenance") else k)
    return collapsed


def _rebuild_brand_tables(pol: dict) -> None:
    """The evaluator builds its brand tables from `aliases.brand` at import; rebuild them in place (the same dict / list objects) for another alias list."""
    P.BRAND_CLASS.clear()
    P.RELATED[:] = []
    for a in pol["aliases"]["brand"]:
        if a["relation"] in ("SAME", "RELABEL"):
            for m in a["members"]:
                k = P.compact(m)
                assert k not in P.BRAND_CLASS, k
                P.BRAND_CLASS[k] = (a["id"], a["relation"])
    for a in pol["aliases"]["brand"]:
        if a["relation"] == "RELATED":
            P.RELATED.append((a["id"], {P._cls(P.compact(m)) for m in a["members"]}))


@contextlib.contextmanager
def rev4_baseline():
    base = rev4_policy()
    live_snapshot = copy.deepcopy(P.POL)
    drift = delta(live_snapshot, base) - EXPECTED_DELTA
    if drift:
        raise RuntimeError(f"the live policy differs from the rev 4 baseline in unexpected keys: {sorted(drift)}")
    original_loader = loader.load_policy
    try:
        P.POL.clear()
        P.POL.update(copy.deepcopy(base))
        _rebuild_brand_tables(P.POL)
        loader.load_policy = lambda version="v1": copy.deepcopy(base)
        yield base
    finally:
        loader.load_policy = original_loader
        P.POL.clear()
        P.POL.update(live_snapshot)
        _rebuild_brand_tables(P.POL)
