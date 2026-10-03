from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_admin_surface_is_separate_and_level_zero():
    page = read("app/admin/(secure)/retail-lineup-bootstrap/page.tsx")
    nav = read("components/admin/AdminNav.tsx")
    assert "Retail Lineup Bootstrap" in page
    assert "LEVEL 0" in page
    assert 'href="/admin/retail-lineup-bootstrap"' in nav
    assert "TARGET_LINEUP" in page
    assert "immutable plan" in page


def test_upload_is_xlsx_only_and_does_not_compile_in_vercel_request():
    actions = read("app/admin/retail-lineup-actions.ts")
    assert "4 * 1024 * 1024" in actions
    assert 'endsWith(".xlsx")' in actions
    assert 'source_kind: "RETAIL_LINEUP_BOOTSTRAP"' in actions
    assert 'dispatchWorker("source-import")' in actions
    assert "compile_retail_lineup_workbook" not in actions
    assert "apply_retail_lineup_plan_to_staged_tree" not in actions
    assert "subprocess" not in actions


def test_apply_is_closed_and_never_reaches_the_legacy_apply_rpc():
    # Vehicle DB v3 Phase 0 step 5: applying a plan used to submit the exact
    # reviewed identity (plan_hash/baseline_hash) to tdr_begin_retail_lineup_plan_apply
    # and dispatch the apply worker. That write path is now closed -- the action
    # must refuse before any of that, not recompile or resubmit anything.
    actions = read("app/admin/retail-lineup-actions.ts")
    detail = read("app/admin/(secure)/retail-lineup-bootstrap/[planId]/page.tsx")
    assert "Legacy Vehicle DB write path is closed (Phase 0 step 5)" in actions
    assert 'db.rpc("tdr_begin_retail_lineup_plan_apply"' not in actions
    assert 'dispatchWorker("retail-lineup-bootstrap-apply"' not in actions
    assert 'name="plan_hash"' in detail
    assert 'name="baseline_hash"' in detail
    assert "stored compiled_plan" in detail


def test_preview_page_renders_every_destructive_classification_before_apply():
    detail = read("app/admin/(secure)/retail-lineup-bootstrap/[planId]/page.tsx")
    for action in ("KEEP", "CREATE", "REACTIVATE", "ARCHIVE"):
        assert action in detail
    assert "explicit reopen" in detail
    assert "canonicalTrimId" in detail
    assert "identityResolution" in detail


def test_workbook_generation_uses_canonical_python_generator_not_browser_reimplementation():
    actions = read("app/admin/retail-lineup-actions.ts")
    worker = read("automotive/vehicle_master/tools/retail_lineup_workbook_export_worker.py")
    flow = read(".github/workflows/retail-lineup-workbook-export.yml")
    assert 'db.from("retail_lineup_workbook_exports").insert' in actions
    assert 'dispatchWorker("retail-lineup-workbook-export")' in actions
    assert "generate_retail_lineup_workbook" in worker
    assert "ref: main" in flow
    assert "contents: read" in flow
    assert "git push" not in flow


def test_chunk_six_does_not_smuggle_in_chunk_seven_worker_handler():
    # Chunk 6 may enqueue the dedicated source kind, but it must not add the
    # source-import compiler/apply handler yet. That integration boundary is
    # intentionally Chunk 7 so ordinary ECO/DLT/Vehicle-Specs paths stay
    # untouched while the Admin contract is reviewed.
    worker = read("automotive/vehicle_master/tools/import_worker.py")
    assert '"RETAIL_LINEUP_BOOTSTRAP"' not in worker
