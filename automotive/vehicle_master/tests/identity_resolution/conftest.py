"""Historical baselines: the rev 4 evidence is verified against the rev 4 policy, never against whatever the live draft says.

The accepted rev 4 artifacts (the pair-level relation export, the calibration outputs and owner review sheet, the lexical-pass results, the Owner Decision Pack) were produced by the rev 4 policy and
evaluator. Rev 5 (owner decision `od_related_brand_auto_eligible`) changes the live policy, so these test modules run under `policy_baseline.rev4_baseline()`: the evaluator behaves exactly as it did
for rev 4, and the export's source pins for the two files that changed since (`policy.yaml`, `ref_eval_core.py`) are checked against the archived rev 4 copies in `calibration/baselines/rev4/`.
Nothing in the committed rev 4 artifacts is rewritten. The rev 5 behaviour is covered by `test_ir_related_auto.py` and by `calibration/related_auto/`.
"""
from __future__ import annotations

import pytest

BASELINE_MODULES = {"test_ir_calibration", "test_ir_relation_export", "test_ir_lexical_invariants", "test_ir_owner_decision_pack"}


@pytest.fixture(autouse=True, scope="module")
def _historical_rev4_baseline(request):
    name = request.module.__name__.split(".")[-1]
    if name not in BASELINE_MODULES:
        yield
        return
    from identity_resolution.calibration import policy_baseline as PB
    from identity_resolution.calibration import relation_export as E
    mapped = {
        "automotive/vehicle_master/identity_resolution/contract/v1/policy.yaml": PB.REV4_POLICY,
        "automotive/vehicle_master/identity_resolution/calibration/ref_eval_core.py": PB.REV4_EVALUATOR,
    }
    import ir_support as S

    def clear_loader_caches():     # ir_support caches the policy it loads: never let a baseline load leak into another module (or the other way round)
        for fn in vars(S).values():
            if hasattr(fn, "cache_clear"):
                fn.cache_clear()

    original = E.repo_file
    E.repo_file = lambda relative: mapped.get(relative) or original(relative)
    clear_loader_caches()
    try:
        with PB.rev4_baseline():
            yield
    finally:
        E.repo_file = original
        clear_loader_caches()
