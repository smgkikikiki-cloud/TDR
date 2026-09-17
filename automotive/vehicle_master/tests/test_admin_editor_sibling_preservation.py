"""Data-integrity gate for the Canonical Vehicle Editor's MarketTrim edit path.

The editor (app/admin/vehicle-editor-actions.ts#prepareTrimEdit) builds one
batch per trim via lib/canonical-command-builder.ts's buildTrimEditBatch():
an UPSERT_MODEL_BUNDLE carrying only the ONE MarketTrim being edited (plus an
empty `variants: []`), followed by one APPEND_SPEC per comparable-spec fact
touched in the same pass. Both halves have to be proven against the REAL
Python canonical writer, not just asserted by reading
vehreg/canonical_write.py's code: that the partial trim payload is
non-destructive to siblings, and that a batch mixing both command types
applies cleanly.

These tests do not hand-write the command JSON. They shell out to
scripts/print-market-trim-edit-command.ts, which imports and calls the exact
same buildTrimEditBatch() the editor's server action calls, so what is under
test is byte-for-byte what production would send.

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
from vehreg.comparable_specs import SpecLedger, SpecRegistry, ValueState
from vehreg.input_pipeline import CanonicalInputPipeline

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
    command = dict(batch_payload["commands"][0])
    command["command_id"] = "test-market-trim-edit-001"
    command["actor"] = "sibling-preservation-test"
    command["year"] = YEAR
    command["submitted_at"] = args["submittedAt"]
    command["reason"] = batch_payload["reason"]
    return command


def _edit_trim_a_args(**overrides) -> dict:
    """The editor's submission for "open Trim A, change its transmission".

    `submissions` carries only what the admin actually touched -- one entry
    per UI field, in editor terms. What that fans out to (a MarketTrim column,
    a comparable-spec fact, or both) is the builder's job, and proving that
    fan-out is safe against real siblings is this file's job.
    """
    args = {
        "batchId": "admin-vehicle-trim-sibling-test",
        "year": YEAR,
        "submittedAt": "2026-01-01T00:00:00Z",
        "reason": "Sibling preservation regression test",
        "evidence": {"sourceKind": "OEM", "sourceRef": "https://example.test/trim-a-update", "reviewedAt": "2026-01-01"},
        "canonicalModelId": MODEL_ID,
        "brand": {"id": "acme", "nameEn": "Acme Motors"},
        "generationCode": "gen1",
        "generationId": GEN_ID,
        "existingTrimId": TRIM_A_ID,
        "identity": {"name": "Trim A Updated", "powertrain": "ICE"},
        # Only one field is "touched" -- everything else on Trim A must
        # survive unchanged via the writer's field-level merge, not just
        # Trim B and the Variant surviving at the collection level.
        "submissions": [
            {"key": "transmission", "valueState": "KNOWN", "value": "AUTOMATIC", "qualifiers": {}},
        ],
    }
    args.update(overrides)
    return args


def test_market_trim_edit_preserves_siblings_and_unrelated_collections(tmp_path: Path):
    data = _seed(tmp_path)

    command = _build_market_trim_edit_command(_edit_trim_a_args())
    assert command["operation"] == "UPSERT_MODEL_BUNDLE"
    assert command["canonical_id"] == MODEL_ID
    # The editor never sends a full sibling list -- this is the exact partial
    # payload shape the task asked to verify is safe.
    assert command["payload"]["trims"] == [{
        "canonical_id": TRIM_A_ID, "name": "Trim A Updated", "powertrain": "ICE",
        "transmission": "AUTOMATIC",
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
    assert trim_a.transmission == "AUTOMATIC"
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
    command = _build_market_trim_edit_command(_edit_trim_a_args(
        existingTrimId=MODEL_ID + ".other_generation.trim.trim_a"))

    with pytest.raises(Exception):
        CanonicalWritePipeline(data).apply(command)

    # Nothing should have been written.
    catalog = Catalog.load(data, YEAR)
    assert catalog.trims[TRIM_A_ID].name == "Trim A"
    assert len(catalog.trims_of(MODEL_ID)) == 2


# ---------------------------------------------------------------------------
# The unified editor: one form, one batch, and a round trip that comes back.
# ---------------------------------------------------------------------------

REAL_REGISTRY = (Path(__file__).resolve().parents[1] / "vehreg" / "data" / "2026"
                 / "product" / "comparable_specs" / "registry.json")


def _seed_registry(data: Path) -> None:
    """Copy the REAL comparable-spec registry into the temp tree.

    The editor, the builder and the writer all validate against this one file,
    so a hand-written stand-in would let a unit mismatch or a powertrain-scope
    mistake pass here and fail in production.
    """
    target = data / str(YEAR) / "product" / "comparable_specs" / "registry.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(REAL_REGISTRY, target)


def _batch(args: dict, batch_id: str) -> dict:
    """The whole batch the editor produces, normalized the way
    lib/canonical-input-queue.ts's enqueueCanonicalInputBatch normalizes it
    (actor + submitted_at stamped onto the batch) before the worker pulls it."""
    if shutil.which("node") is None:
        pytest.skip("node is not available to run the real TypeScript command builder")
    result = subprocess.run(
        ["node", "--experimental-strip-types", str(BUILDER_SCRIPT)],
        input=json.dumps(args), capture_output=True, text=True, cwd=REPO_ROOT, timeout=60,
    )
    assert result.returncode == 0, f"buildTrimEditBatch bridge failed: {result.stderr}"
    payload = json.loads(result.stdout)
    payload["batch_id"] = batch_id
    payload["actor"] = "trim-editor-test"
    return payload


def _submission(key: str, value, qualifiers: dict | None = None,
                state: str = "KNOWN") -> dict:
    return {"key": key, "valueState": state, "value": value,
            "qualifiers": qualifiers or {}}


def _resolved(data: Path, trim_id: str) -> dict:
    """What the admin would see on re-opening the trim: the resolved
    comparable specs, keyed by field, exactly as ProductMaster.detail() would
    project them into current_market_trims.payload.comparable_specs."""
    from vehreg.product import ProductMaster
    master = ProductMaster.load(data, YEAR)
    detail = master.detail(trim_id)
    return {fact["field_key"]: fact for fact in detail["comparable_specs"]}


def test_one_trim_edit_carries_marketrim_fields_and_spec_facts_in_one_batch(tmp_path: Path):
    """The editor's core promise: an admin opens one trim, changes its own
    fields AND its comparable-spec facts, and that lands as ONE canonical
    batch. Proven through the real CanonicalInputPipeline, which is what the
    worker actually runs -- mixing UPSERT_MODEL_BUNDLE and APPEND_SPEC in a
    single batch has to work for the unified editor to be honest."""
    data = _seed(tmp_path)
    _seed_registry(data)

    batch = _batch(_edit_trim_a_args(
        identity={"name": "Trim A", "powertrain": "ICE"},
        submissions=[
            _submission("seats", 7),
            _submission("max_power_kw", 150),
            _submission("safety_aeb", True),
        ],
    ), "admin-vehicle-trim-combined-001")
    operations = [command["operation"] for command in batch["commands"]]
    assert operations == ["UPSERT_MODEL_BUNDLE", "APPEND_SPEC", "APPEND_SPEC", "APPEND_SPEC"]

    result = CanonicalInputPipeline(data).apply(batch)
    assert result.status == "APPLIED"

    catalog = Catalog.load(data, YEAR)
    assert catalog.validate() == []

    # -- the MarketTrim field landed --
    assert catalog.trims[TRIM_A_ID].seats == 7
    # -- its untouched fields and its sibling trim are still intact --
    assert catalog.trims[TRIM_A_ID].tire_front == TRIM_A_SEED["tire_front"]
    assert catalog.trims[TRIM_B_ID].name == TRIM_B_SEED["name"]
    assert len(catalog.trims_of(MODEL_ID)) == 2

    # -- and all three facts landed against that same trim --
    registry = SpecRegistry.load(data, YEAR)
    ledger = SpecLedger.load(data, YEAR, registry=registry, catalog=catalog)
    facts = {fact.field_key: fact for fact in ledger.facts if fact.trim_id == TRIM_A_ID}
    assert facts["powertrain.max_power_kw"].value == 150
    assert facts["powertrain.max_power_kw"].unit == "kW"
    assert facts["safety.aeb"].value is True
    assert facts["powertrain.max_power_kw"].value_state is ValueState.KNOWN
    # Seats is the fan-out case: one box, both backends, same number.
    assert facts["vehicle.seats"].value == 7
    assert catalog.trims[TRIM_A_ID].seats == facts["vehicle.seats"].value


def test_one_ui_field_keeps_both_backends_in_step(tmp_path: Path):
    """Requirement 1, proven at the far end of the pipeline: the admin sees
    one Seats box, one Drivetrain box, one Battery capacity box, and after a
    real write BOTH representations of each carry the same value. This is what
    makes the duplication a storage detail rather than the admin's problem."""
    data = _seed(tmp_path)
    _seed_registry(data)

    CanonicalInputPipeline(data).apply(_batch(_edit_trim_a_args(
        identity={"name": "Trim A", "powertrain": "ICE"},
        submissions=[
            _submission("seats", 7),
            _submission("drivetrain", "AWD"),
            _submission("length_mm", 4600),
            _submission("wheelbase_mm", 2750),
            _submission("tire_front", "225/45 R18"),
        ],
    ), "admin-vehicle-trim-fanout-001"))

    catalog = Catalog.load(data, YEAR)
    trim = catalog.trims[TRIM_A_ID]
    facts = _resolved(data, TRIM_A_ID)

    for column, field_key, expected in [
        ("seats", "vehicle.seats", 7),
        ("length_mm", "vehicle.length_mm", 4600),
        ("wheelbase_mm", "vehicle.wheelbase_mm", 2750),
        ("tire_front", "fitment.tyre_front", "225/45 R18"),
    ]:
        assert getattr(trim, column) == expected, column
        assert facts[field_key]["value"] == expected, field_key
    assert trim.drivetrain.value == "AWD"
    assert facts["powertrain.drivetrain"]["value"] == "AWD"


def test_a_new_trim_and_its_specs_are_created_in_one_save(tmp_path: Path):
    """Requirement 4. The trim does not exist yet, so its canonical_id does
    not exist yet either -- and it is not computable outside Python, because
    the identity rule folds Thai marks and strips corporate words. The name
    here is chosen to prove exactly that: vehreg/normalize.py's folder drops
    "Motor", so a TypeScript reimplementation would attach these facts to
    `...trim.ultra_dual_motor_bev`, a trim that never exists.

    The batch instead names the trim by reference and lets the writer resolve
    it with the one rule, in the same batch that creates it.
    """
    data = _seed(tmp_path)
    _seed_registry(data)

    batch = _batch(_edit_trim_a_args(
        existingTrimId=None,
        identity={"name": "Ultra Dual Motor", "powertrain": "BEV"},
        submissions=[
            _submission("seats", 5),
            _submission("battery_kwh", 77.0),
            _submission("max_power_kw", 180),
            _submission("battery_supplier", "CATL"),
        ],
    ), "admin-vehicle-trim-create-001")
    assert [c["operation"] for c in batch["commands"]] == [
        "UPSERT_MODEL_BUNDLE", "APPEND_SPEC", "APPEND_SPEC", "APPEND_SPEC", "APPEND_SPEC"]
    assert "canonical_id" not in batch["commands"][0]["payload"]["trims"][0]
    assert batch["commands"][1]["payload"]["trim_ref"] == {
        "generation_id": GEN_ID, "name": "Ultra Dual Motor", "powertrain": "BEV",
    }

    assert CanonicalInputPipeline(data).apply(batch).status == "APPLIED"

    catalog = Catalog.load(data, YEAR)
    assert catalog.validate() == []
    # The writer's own rule: "Motor" is corporate noise and is folded away.
    new_id = GEN_ID + ".trim.ultra_dual_bev"
    assert new_id in catalog.trims, sorted(catalog.trims)
    assert catalog.trims[new_id].seats == 5
    assert catalog.trims[new_id].battery_kwh == 77.0
    # And the facts attached to that same resolved trim, not to a phantom.
    facts = _resolved(data, new_id)
    assert facts["powertrain.max_power_kw"]["value"] == 180
    assert facts["battery.supplier"]["value"] == "CATL"
    assert facts["vehicle.seats"]["value"] == 5
    # The siblings are all still there.
    assert len(catalog.trims_of(MODEL_ID)) == 3


def test_range_keeps_its_measurement_basis_through_a_real_write(tmp_path: Path):
    """Requirement 5, at the far end: 442 km must not arrive as a bare 442."""
    data = _seed(tmp_path)
    _seed_registry(data)

    assert CanonicalInputPipeline(data).apply(_batch(_edit_trim_a_args(
        existingTrimId=None,
        identity={"name": "Long Range", "powertrain": "BEV"},
        submissions=[
            _submission("battery_kwh", 55.2),
            _submission("rated_range_km", 442, {"measurement_basis": "NEDC"}),
        ],
    ), "admin-vehicle-trim-range-001")).status == "APPLIED"

    trim_id = GEN_ID + ".trim.long_range_bev"
    facts = _resolved(data, trim_id)
    assert facts["ev.rated_range_km"]["value"] == 442
    assert facts["ev.rated_range_km"]["unit"] == "km"
    assert facts["ev.rated_range_km"]["qualifiers"] == {"measurement_basis": "NEDC"}


def test_full_round_trip_projection_to_editor_to_batch_and_back(tmp_path: Path):
    """Requirement: projection -> normalized editor state -> edit -> batch ->
    canonical writer -> projection, and every field comes back.

    The Python half of the loop runs here; the TypeScript half (normalizing
    the projection into editor state) is exercised against the same shape by
    scripts/check-trim-editor.ts. What this proves is that the projection the
    editor will re-read really does carry everything the save put in --
    including a qualifier, which is the piece most likely to be silently lost.
    """
    data = _seed(tmp_path)
    _seed_registry(data)

    entered = [
        _submission("drivetrain", "FWD"),
        _submission("motor_type", "PMSM"),
        _submission("max_power_kw", 100),
        _submission("max_torque_nm", 225),
        _submission("battery_kwh", 55.2),
        _submission("battery_chemistry", "LFP"),
        _submission("battery_supplier", "CATL"),
        _submission("rated_range_km", 442, {"measurement_basis": "NEDC"}),
        _submission("seats", 5),
        _submission("length_mm", 4810),
        _submission("width_mm", 1880),
        _submission("height_mm", 1545),
        _submission("wheelbase_mm", 2750),
        _submission("tire_front", "215/55 R17"),
        _submission("tire_rear", "215/55 R17"),
    ]
    assert CanonicalInputPipeline(data).apply(_batch(_edit_trim_a_args(
        existingTrimId=None,
        identity={"name": "Comfort Private Use", "powertrain": "BEV"},
        submissions=entered,
    ), "admin-vehicle-trim-roundtrip-001")).status == "APPLIED"

    trim_id = GEN_ID + ".trim.comfort_private_use_bev"
    from vehreg.product import ProductMaster
    detail = ProductMaster.load(data, YEAR).detail(trim_id)

    # -- MarketTrim columns come back under payload.specs, which is the exact
    # nesting lib/trim-editor-state.ts normalizes. --
    specs = detail["specs"]
    assert specs["drivetrain"] == "FWD"
    assert specs["seats"] == 5
    assert specs["battery_kwh"] == 55.2
    assert specs["length_mm"] == 4810
    assert specs["width_mm"] == 1880
    assert specs["height_mm"] == 1545
    assert specs["wheelbase_mm"] == 2750
    assert specs["tire_front"] == "215/55 R17"
    assert specs["tire_rear"] == "215/55 R17"

    # -- and every entered concept comes back as a resolved fact --
    facts = {row["field_key"]: row for row in detail["comparable_specs"]}
    assert facts["powertrain.drivetrain"]["value"] == "FWD"
    assert facts["powertrain.motor_type"]["value"] == "PMSM"
    assert facts["powertrain.max_power_kw"]["value"] == 100
    assert facts["powertrain.max_torque_nm"]["value"] == 225
    assert facts["battery.catalog_capacity_kwh"]["value"] == 55.2
    assert facts["battery.chemistry"]["value"] == "LFP"
    assert facts["battery.supplier"]["value"] == "CATL"
    assert facts["vehicle.seats"]["value"] == 5
    assert facts["fitment.tyre_front"]["value"] == "215/55 R17"
    # The one the mandate calls out by name.
    assert facts["ev.rated_range_km"]["value"] == 442
    assert facts["ev.rated_range_km"]["qualifiers"]["measurement_basis"] == "NEDC"

    # -- re-submitting the identical edit is an idempotent replay, not a
    # duplicate fact and not a ledger conflict --
    assert CanonicalInputPipeline(data).apply(_batch(_edit_trim_a_args(
        existingTrimId=trim_id,
        identity={"name": "Comfort Private Use", "powertrain": "BEV"},
        submissions=entered,
    ), "admin-vehicle-trim-roundtrip-002")).status == "APPLIED"
    again = ProductMaster.load(data, YEAR)
    assert again.validate() == []
    ranges = [row for row in again.detail(trim_id)["comparable_specs"]
              if row["field_key"] == "ev.rated_range_km"]
    assert len(ranges) == 1, "a replay must not fork a second range fact"


def test_correcting_one_field_twice_in_a_day_revises_it(tmp_path: Path):
    """Ordinary editing: fix a number, notice it is still wrong, fix it again.

    Both facts carry the same start date, so a second file for the same field
    would be an unresolvable SpecLedger conflict -- the editor would work once
    and then refuse forever. The fact file is keyed by the fact, so the second
    save revises the first.
    """
    data = _seed(tmp_path)
    _seed_registry(data)

    def save(power: int, batch_id: str) -> None:
        assert CanonicalInputPipeline(data).apply(_batch(_edit_trim_a_args(
            identity={"name": "Trim A", "powertrain": "ICE"},
            submissions=[_submission("max_power_kw", power)],
        ), batch_id)).status == "APPLIED"

    save(150, "admin-vehicle-trim-fix-001")
    save(165, "admin-vehicle-trim-fix-002")

    from vehreg.product import ProductMaster
    master = ProductMaster.load(data, YEAR)
    assert master.validate() == [], "a same-day correction must not leave a ledger conflict"
    power = [row for row in master.detail(TRIM_A_ID)["comparable_specs"]
             if row["field_key"] == "powertrain.max_power_kw"]
    assert len(power) == 1
    assert power[0]["value"] == 165


def test_not_applicable_spec_is_recorded_as_a_state_not_a_zero(tmp_path: Path):
    """A field marked "ไม่มีในรุ่นนี้" in the editor must reach the ledger as
    NOT_APPLICABLE with no value -- never as 0, false, or a silent omission."""
    data = _seed(tmp_path)
    _seed_registry(data)

    CanonicalInputPipeline(data).apply(_batch(_edit_trim_a_args(
        identity={"name": "Trim A", "powertrain": "ICE"},
        submissions=[_submission("safety_aeb", None, state="NOT_APPLICABLE")],
    ), "admin-vehicle-trim-na-001"))

    catalog = Catalog.load(data, YEAR)
    ledger = SpecLedger.load(data, YEAR, registry=SpecRegistry.load(data, YEAR), catalog=catalog)
    fact = next(f for f in ledger.facts if f.trim_id == TRIM_A_ID and f.field_key == "safety.aeb")
    assert fact.value_state is ValueState.NOT_APPLICABLE
    assert fact.value is None
    assert fact.value is not False
