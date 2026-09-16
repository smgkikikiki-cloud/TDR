"""Data-integrity gate for the Canonical Vehicle Editor's MarketTrim edit path.

The editor (app/admin/vehicle-editor-actions.ts#prepareMarketTrimEdit) builds
an UPSERT_MODEL_BUNDLE command via lib/canonical-command-builder.ts's
buildMarketTrimBatch(), sending only the ONE MarketTrim being edited plus an
empty `variants: []`. Before this branch can merge, that has to be proven
non-destructive against the REAL Python canonical writer, not just asserted
by reading vehreg/canonical_write.py's code.

This test does not hand-write the command JSON. It shells out to
scripts/print-market-trim-edit-command.ts, which imports and calls the exact
same buildMarketTrimBatch() the editor's server action calls, so the command
under test is byte-for-byte what production would send.

Writer semantics this proves (see also CanonicalWritePipeline._upsert_model_bundle
in vehreg/canonical_write.py):
  - Model/Generation's own scalar fields: dict.update() partial patch. Only
    keys present in the incoming patch are overwritten; the model/generation
    dict object itself is found by identity and mutated in place, so sibling
    models/generations in the same brand file are never touched.
  - trims[] / variants[]: merge/upsert-by-identity into the EXISTING on-disk
    array (loaded from the brand file, never reset/replaced). Each incoming
    entry is matched against existing entries by a stable identity key
    (slug(id) for trims/variants) and merged in place if found, appended if
    new. An existing entry with no matching incoming entry -- i.e. every
    sibling MarketTrim/Variant the command's payload omits -- is left
    completely untouched. There is no "replace whole collection" step
    anywhere in this path.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from vehreg.canonical_write import CanonicalWritePipeline
from vehreg.catalog import Catalog

YEAR = 2026
MODEL_ID = "acme.testmodel"
GEN_ID = MODEL_ID + ".gen1"
TRIM_A_ID = GEN_ID + ".trim.trim_a"
TRIM_B_ID = GEN_ID + ".trim.trim_b"
REPO_ROOT = Path(__file__).resolve().parents[3]
BUILDER_SCRIPT = REPO_ROOT / "scripts" / "print-market-trim-edit-command.ts"

TRIM_A_SEED = {
    "id": "trim_a",
    "name": "Trim A",
    "variant": "Test Variant 2.0L ICE",
    "powertrain": "ICE",
    "drivetrain": "FWD",
    "engine_code": "ABC123",
    "engine_cc": 2000,
    "transmission": "6AT",
    "seats": 5,
    "length_mm": 4500,
    "width_mm": 1800,
    "height_mm": 1500,
    "wheelbase_mm": 2700,
    "tire_front": "215/55 R17",
    "tire_rear": "215/55 R17",
    "wheel_front": "17 in",
    "wheel_rear": "17 in",
    "aliases": [],
    "source_refs": {"oem": ["https://example.test/trim-a"]},
    "notes": "seed trim A",
}

TRIM_B_SEED = {
    "id": "trim_b",
    "name": "Trim B",
    "variant": "Test Variant 2.0L ICE",
    "powertrain": "ICE",
    "drivetrain": "FWD",
    "engine_code": "ABC123",
    "engine_cc": 2000,
    "transmission": "6MT",
    "seats": 5,
    "length_mm": 4500,
    "width_mm": 1800,
    "height_mm": 1500,
    "wheelbase_mm": 2700,
    "tire_front": "205/55 R16",
    "tire_rear": "205/55 R16",
    "wheel_front": "16 in",
    "wheel_rear": "16 in",
    "aliases": [],
    "source_refs": {"oem": ["https://example.test/trim-b"]},
    "notes": "seed trim B — must never be touched by an edit scoped to trim A",
}

VARIANT_SEED = {
    "id": "variant_1",
    "name": "Test Variant 2.0L ICE",
    "powertrain": "ICE",
    "drivetrain": "FWD",
    "engine_cc": 2000,
    "battery_kwh": None,
    "price_thb": None,
    "price_min_thb": None,
    "price_max_thb": None,
    "import_type": "CBU",
    "origin_country": "TH",
    "price_note": "unrelated sibling collection — must survive a trims-only edit",
    "aliases": [],
}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _seed(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    _write_json(data / str(YEAR) / "models" / "acme.json", {
        "brand": {
            "id": "acme", "name_en": "Acme Motors", "name_th": "",
            "brand_segment": "MASS", "oem_group": "UNKNOWN", "brand_origin": "TH",
            "trim_detail": False, "aliases": [],
        },
        "models": [{
            "id": "testmodel", "name_en": "Test Model", "name_th": "",
            "nameplate": "", "body_type": "SEDAN", "cab_type": "NOT_APPLICABLE",
            "registration_type": "", "market_scope": "CORE", "aliases": [],
            "generations": [{
                "code": "gen1", "segment": "B", "seats": 5,
                "launched": "2025-01-01", "ended": None,
                "variants": [dict(VARIANT_SEED)],
                "trims": [dict(TRIM_A_SEED), dict(TRIM_B_SEED)],
            }],
        }],
    })
    return data


def _build_market_trim_edit_command(args: dict) -> dict:
    """Invoke the REAL admin editor command builder (TypeScript) and return
    the single UPSERT_MODEL_BUNDLE command it produced, with command_id/actor
    added the same way lib/canonical-input-queue.ts's enqueueCanonicalInputBatch
    and vehreg/input_pipeline.py's CanonicalInputBatch.from_dict add them
    before a command ever reaches CanonicalWritePipeline in production."""
    if shutil.which("node") is None:
        pytest.skip("node is not available to run the real TypeScript command builder")
    result = subprocess.run(
        ["node", "--experimental-strip-types", str(BUILDER_SCRIPT)],
        input=json.dumps(args), capture_output=True, text=True, cwd=REPO_ROOT, timeout=60,
    )
    assert result.returncode == 0, f"buildMarketTrimBatch bridge failed: {result.stderr}"
    batch_payload = json.loads(result.stdout)
    assert batch_payload["schema_version"] == 1
    commands = batch_payload["commands"]
    assert len(commands) == 1, "expected exactly one UPSERT_MODEL_BUNDLE command"
    command = dict(commands[0])
    command["command_id"] = "test-market-trim-edit-001"
    command["actor"] = "sibling-preservation-test"
    command["year"] = YEAR
    command["submitted_at"] = args["submittedAt"]
    command["reason"] = batch_payload["reason"]
    return command


def _edit_trim_a_args() -> dict:
    return {
        "batchId": "admin-vehicle-trim-sibling-test",
        "year": YEAR,
        "submittedAt": "2026-01-01T00:00:00Z",
        "reason": "Sibling preservation regression test",
        "evidence": {"sourceKind": "OEM", "sourceRef": "https://example.test/trim-a-update", "reviewedAt": "2026-01-01"},
        "canonicalModelId": MODEL_ID,
        "brand": {"id": "acme", "nameEn": "Acme Motors"},
        "generationCode": "gen1",
        "existingTrimId": TRIM_A_ID,
        # Only two fields are "touched" -- everything else on Trim A must
        # survive unchanged via the writer's field-level merge, not just
        # Trim B and the Variant surviving at the collection level.
        "trim": {"name": "Trim A Updated", "powertrain": "ICE", "transmission": "8AT"},
    }


def test_market_trim_edit_preserves_siblings_and_unrelated_collections(tmp_path: Path):
    data = _seed(tmp_path)

    command = _build_market_trim_edit_command(_edit_trim_a_args())
    assert command["operation"] == "UPSERT_MODEL_BUNDLE"
    assert command["canonical_id"] == MODEL_ID
    # The editor never sends a full sibling list -- this is the exact partial
    # payload shape the task asked to verify is safe.
    assert command["payload"]["trims"] == [{
        "canonical_id": TRIM_A_ID, "name": "Trim A Updated", "powertrain": "ICE", "transmission": "8AT",
    }]
    assert command["payload"]["variants"] == []

    result = CanonicalWritePipeline(data).apply(command)
    assert result.topic == "catalog"
    assert not result.idempotent_replay

    catalog = Catalog.load(data, YEAR)
    assert catalog.validate() == [], "catalog must remain structurally valid after the edit"

    # -- Trim A: the requested edit applied, stable canonical_id kept --
    assert TRIM_A_ID in catalog.trims
    trim_a = catalog.trims[TRIM_A_ID]
    assert trim_a.id == TRIM_A_ID
    assert trim_a.name == "Trim A Updated"
    assert trim_a.transmission == "8AT"
    # -- Trim A: fields NOT in the edit patch survive (field-level merge, not
    # a whole-entity replace) --
    assert trim_a.engine_code == TRIM_A_SEED["engine_code"]
    assert trim_a.engine_cc == TRIM_A_SEED["engine_cc"]
    assert trim_a.length_mm == TRIM_A_SEED["length_mm"]
    assert trim_a.tire_front == TRIM_A_SEED["tire_front"]
    assert trim_a.wheel_front == TRIM_A_SEED["wheel_front"]
    assert dict(trim_a.source_refs) == {"oem": ("https://example.test/trim-a",)}
    assert trim_a.notes == TRIM_A_SEED["notes"]

    # -- Trim B: sibling omitted from the command's payload, must be fully
    # untouched -- not deleted, not merged with Trim A's edit, not duplicated --
    assert TRIM_B_ID in catalog.trims
    trim_b = catalog.trims[TRIM_B_ID]
    assert trim_b.name == TRIM_B_SEED["name"]
    assert trim_b.transmission == TRIM_B_SEED["transmission"]
    assert trim_b.tire_front == TRIM_B_SEED["tire_front"]
    assert trim_b.notes == TRIM_B_SEED["notes"]
    assert dict(trim_b.source_refs) == {"oem": ("https://example.test/trim-b",)}

    # -- No duplicate identity was created for Trim A, and the trim count
    # under this generation is exactly what it was before the edit (2) --
    trims_in_generation = catalog.trims_of(MODEL_ID)
    assert len(trims_in_generation) == 2
    assert sorted(t.id for t in trims_in_generation) == sorted([TRIM_A_ID, TRIM_B_ID])

    # -- Unrelated sibling collection (Variant) is untouched even though the
    # command's payload explicitly sent variants: [] --
    variants = catalog.variants_of(MODEL_ID)
    assert len(variants) == 1
    variant = variants[0]
    assert variant.name == VARIANT_SEED["name"]
    assert variant.engine_cc == VARIANT_SEED["engine_cc"]
    assert variant.import_type.value == VARIANT_SEED["import_type"]
    assert variant.origin_country == VARIANT_SEED["origin_country"]

    # -- Model/Generation-level sibling fields the command never patched --
    model = catalog.models[MODEL_ID]
    assert model.body_type.value == "SEDAN"
    generation = catalog.generations_of(MODEL_ID)[0]
    assert generation.segment.value == "B"
    assert generation.seats == 5
    assert generation.launched == "2025-01-01"

    # -- Belt-and-suspenders: inspect the raw file on disk directly, not just
    # the Catalog's in-memory view, to rule out a duplicate raw trim row that
    # Catalog happens to dedupe/mask on load --
    raw = json.loads((data / str(YEAR) / "models" / "acme.json").read_text(encoding="utf-8"))
    raw_trims = raw["models"][0]["generations"][0]["trims"]
    assert len(raw_trims) == 2
    raw_ids = sorted(t["id"] for t in raw_trims)
    assert raw_ids == ["trim_a", "trim_b"]
    raw_variants = raw["models"][0]["generations"][0]["variants"]
    assert len(raw_variants) == 1
    assert raw_variants[0]["name"] == VARIANT_SEED["name"]

    # -- Revision audit trail recorded exactly one write --
    state = data / str(YEAR) / "canonical_state"
    revisions = [json.loads(line) for line in (state / "revisions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(revisions) == 1
    assert revisions[0]["operation"] == "UPSERT_MODEL_BUNDLE"
    assert revisions[0]["entity_id"] == MODEL_ID


def test_market_trim_edit_command_cannot_attach_to_a_different_generation(tmp_path: Path):
    """A command whose existingTrimId names a generation other than the one
    named by generationCode must be rejected by the writer itself, not merely
    by the admin action's own pre-check -- defence in depth for the "cannot
    attach MarketTrim to the wrong model/generation" requirement."""
    data = _seed(tmp_path)
    args = _edit_trim_a_args()
    args["existingTrimId"] = MODEL_ID + ".other_generation.trim.trim_a"
    command = _build_market_trim_edit_command(args)

    with pytest.raises(Exception):
        CanonicalWritePipeline(data).apply(command)

    # Nothing should have been written.
    catalog = Catalog.load(data, YEAR)
    assert catalog.trims[TRIM_A_ID].name == "Trim A"
    assert len(catalog.trims_of(MODEL_ID)) == 2
