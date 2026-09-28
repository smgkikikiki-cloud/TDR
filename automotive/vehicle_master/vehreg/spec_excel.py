"""Deterministic Excel-row compiler for direct canonical MarketTrim specification edits.

The workbook is an editing surface, not an evidence source. Identity comes from
``canonical_trim_id`` and every other machine header resolves either to a
registered comparable-spec key or to one of the few MarketTrim-only core fields.
No fuzzy matching and no free-text field guessing occur here.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Any, Iterable

from .catalog import Catalog
from .comparable_specs import SpecRegistry, ValueState, ValueType


class SpecExcelError(ValueError):
    pass


IDENTITY_COLUMN = "canonical_trim_id"

# MarketTrim fields that have no comparable-spec registry key of their own.
CORE_ONLY_HEADERS: dict[str, str] = {
    "core.engine_code": "engine_code",
    "core.wheel_front": "wheel_front",
    "core.wheel_rear": "wheel_rear",
}

# Registry fields whose current canonical value is also represented directly on
# MarketTrim. These are dual-written so both the compact trim payload and the
# comparable-spec surface agree.
REGISTRY_TO_CORE: dict[str, str] = {
    "vehicle.seats": "seats",
    "vehicle.length_mm": "length_mm",
    "vehicle.width_mm": "width_mm",
    "vehicle.height_mm": "height_mm",
    "vehicle.wheelbase_mm": "wheelbase_mm",
    "engine.displacement_cc": "engine_cc",
    "battery.catalog_capacity_kwh": "battery_kwh",
    "powertrain.drivetrain": "drivetrain",
    "powertrain.transmission": "transmission",
    "fitment.tyre_front": "tire_front",
    "fitment.tyre_rear": "tire_rear",
}

_INT_CORE_FIELDS = frozenset({
    "seats", "length_mm", "width_mm", "height_mm", "wheelbase_mm", "engine_cc",
})
_NUMBER_CORE_FIELDS = frozenset({"battery_kwh"})

# Human-friendly fixed columns for qualifier cases that occur frequently in
# vehicle research. The generic ``field__qualifier=value`` syntax below covers
# every other registry qualifier without adding code.
HEADER_ALIASES: dict[str, tuple[str, dict[str, str]]] = {
    "range_nedc_km": ("ev.rated_range_km", {"measurement_basis": "NEDC", "range_scope": "FULL"}),
    "range_cltc_km": ("ev.rated_range_km", {"measurement_basis": "CLTC", "range_scope": "FULL"}),
    "range_wltp_km": ("ev.rated_range_km", {"measurement_basis": "WLTP", "range_scope": "FULL"}),
    "range_wltc_km": ("ev.rated_range_km", {"measurement_basis": "WLTC", "range_scope": "FULL"}),
    "range_epa_km": ("ev.rated_range_km", {"measurement_basis": "EPA", "range_scope": "FULL"}),
    "electric_range_nedc_km": ("ev.rated_range_km", {"measurement_basis": "NEDC", "range_scope": "ELECTRIC_ONLY"}),
    "electric_range_cltc_km": ("ev.rated_range_km", {"measurement_basis": "CLTC", "range_scope": "ELECTRIC_ONLY"}),
    "electric_range_wltp_km": ("ev.rated_range_km", {"measurement_basis": "WLTP", "range_scope": "ELECTRIC_ONLY"}),
    "electric_range_wltc_km": ("ev.rated_range_km", {"measurement_basis": "WLTC", "range_scope": "ELECTRIC_ONLY"}),
    "electric_range_epa_km": ("ev.rated_range_km", {"measurement_basis": "EPA", "range_scope": "ELECTRIC_ONLY"}),
    "ground_clearance_unladen_mm": ("vehicle.ground_clearance_mm", {"load_state": "UNLADEN"}),
    "ground_clearance_laden_mm": ("vehicle.ground_clearance_mm", {"load_state": "LADEN"}),
    "dc_charge_10_80_min": ("charging.dc_time_min", {"soc_from": "10", "soc_to": "80"}),
    "dc_charge_20_80_min": ("charging.dc_time_min", {"soc_from": "20", "soc_to": "80"}),
    "dc_charge_30_80_min": ("charging.dc_time_min", {"soc_from": "30", "soc_to": "80"}),
    "dc_charge_10_100_min": ("charging.dc_time_min", {"soc_from": "10", "soc_to": "100"}),
}

_TRUE = frozenset({"1", "true", "yes", "y"})
_FALSE = frozenset({"0", "false", "no", "n"})
_STATE_TOKENS = {
    "UNKNOWN": ValueState.UNKNOWN,
    "NOT_AVAILABLE": ValueState.NOT_AVAILABLE,
    "NOT_APPLICABLE": ValueState.NOT_APPLICABLE,
}


@dataclass(frozen=True, slots=True)
class ColumnTarget:
    header: str
    field_key: str | None = None
    core_field: str | None = None
    qualifiers: dict[str, str] | None = None


@dataclass(frozen=True, slots=True)
class CompiledWorkbook:
    commands: tuple[dict[str, Any], ...]
    rows_read: int
    rows_changed: int
    values_written: int
    values_unchanged: int


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return isinstance(value, str) and not value.strip()


def _text(value: Any) -> str:
    return str(value).strip()


def _parse_qualified_header(header: str) -> tuple[str, dict[str, str]]:
    if "__" not in header:
        return header, {}
    key, *parts = header.split("__")
    qualifiers: dict[str, str] = {}
    for part in parts:
        name, sep, raw = part.partition("=")
        name, raw = name.strip(), raw.strip()
        if not sep or not name or not raw:
            raise SpecExcelError(
                f"invalid qualified header {header!r}; use field__qualifier=value")
        if name in qualifiers:
            raise SpecExcelError(f"duplicate qualifier {name!r} in header {header!r}")
        qualifiers[name] = raw
    return key, qualifiers


def build_column_targets(headers: Iterable[object], registry: SpecRegistry) -> dict[str, ColumnTarget]:
    targets: dict[str, ColumnTarget] = {}
    for raw in headers:
        header = _text(raw)
        if not header or header == IDENTITY_COLUMN:
            continue
        if header in CORE_ONLY_HEADERS:
            targets[header] = ColumnTarget(header=header, core_field=CORE_ONLY_HEADERS[header])
            continue
        if header in HEADER_ALIASES:
            key, qualifiers = HEADER_ALIASES[header]
        else:
            key, qualifiers = _parse_qualified_header(header)
        definition = registry.fields.get(key)
        if definition is None:
            raise SpecExcelError(f"unknown vehicle spec column {header!r}")
        unknown = set(qualifiers) - set(definition.comparison_qualifiers)
        if unknown:
            raise SpecExcelError(
                f"{header!r} carries unsupported qualifier(s) {sorted(unknown)}")
        if definition.comparison_qualifiers and not qualifiers:
            expected = ", ".join(definition.comparison_qualifiers)
            raise SpecExcelError(
                f"{header!r} requires qualifier context ({expected}); use a fixed alias "
                "or field__qualifier=value")
        targets[header] = ColumnTarget(
            header=header,
            field_key=key,
            core_field=REGISTRY_TO_CORE.get(key),
            qualifiers=dict(qualifiers),
        )
    return targets


def _coerce_number(value: Any, *, field_key: str) -> int | float:
    if type(value) in (int, float) and not isinstance(value, bool):
        number = float(value)
    else:
        text = _text(value).replace(",", "")
        try:
            number = float(text)
        except ValueError as exc:
            raise SpecExcelError(f"{field_key} requires a number, got {value!r}") from exc
    if not math.isfinite(number) or number < 0:
        raise SpecExcelError(f"{field_key} requires a non-negative finite number")
    return int(number) if number.is_integer() else number


def _coerce_known(value: Any, definition) -> Any:
    if definition.value_type is ValueType.NUMBER:
        return _coerce_number(value, field_key=definition.key)
    if definition.value_type is ValueType.BOOLEAN:
        if type(value) is bool:
            return value
        token = _text(value).casefold()
        if token in _TRUE:
            return True
        if token in _FALSE:
            return False
        raise SpecExcelError(
            f"{definition.key} requires YES/NO, TRUE/FALSE or 1/0, got {value!r}")
    if definition.value_type in (ValueType.TEXT, ValueType.ENUM):
        text = _text(value)
        if not text:
            raise SpecExcelError(f"{definition.key} requires non-empty text")
        return text
    if definition.value_type is ValueType.SET:
        if isinstance(value, (list, tuple, set)):
            values = [_text(item) for item in value if _text(item)]
        else:
            values = [_text(item) for item in re.split(r"[;,|]", _text(value)) if _text(item)]
        if not values:
            raise SpecExcelError(f"{definition.key} requires at least one value")
        return values
    raise SpecExcelError(f"unsupported value type for {definition.key}: {definition.value_type}")


def _coerce_spec(value: Any, definition) -> tuple[ValueState, Any]:
    if isinstance(value, str):
        token = value.strip().upper()
        if token in _STATE_TOKENS:
            return _STATE_TOKENS[token], None
        if token == "-":
            raise SpecExcelError(
                f"{definition.key}: '-' is ambiguous; use NOT_AVAILABLE, NOT_APPLICABLE or UNKNOWN")
    return ValueState.KNOWN, _coerce_known(value, definition)


def _coerce_core(field_name: str, value: Any) -> Any:
    if field_name in _INT_CORE_FIELDS:
        number = _coerce_number(value, field_key=field_name)
        if type(number) is not int or number <= 0:
            raise SpecExcelError(f"{field_name} requires a positive integer")
        return number
    if field_name in _NUMBER_CORE_FIELDS:
        number = _coerce_number(value, field_key=field_name)
        if number <= 0:
            raise SpecExcelError(f"{field_name} requires a positive number")
        return number
    text = _text(value)
    if not text:
        raise SpecExcelError(f"{field_name} requires non-empty text")
    return text


def _same(left: Any, right: Any) -> bool:
    if isinstance(left, (int, float)) and isinstance(right, (int, float)) \
            and not isinstance(left, bool) and not isinstance(right, bool):
        return float(left) == float(right)
    if hasattr(left, "value"):
        left = left.value
    if hasattr(right, "value"):
        right = right.value
    return left == right


def _fact_id(trim_id: str, field_key: str, qualifiers: dict[str, str]) -> str:
    if not qualifiers:
        return f"admin:{trim_id}:{field_key}"
    semantic = json.dumps(qualifiers, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    suffix = hashlib.sha256(semantic.encode()).hexdigest()[:12]
    return f"admin:{trim_id}:{field_key}:{suffix}"


def _existing_facts_by_id(existing_facts: Iterable[Any]) -> dict[str, Any]:
    return {str(fact.fact_id): fact for fact in existing_facts}


def compile_rows(
    rows: Iterable[dict[str, Any]],
    *,
    catalog: Catalog,
    registry: SpecRegistry,
    existing_facts: Iterable[Any] = (),
    observed_at: str,
    audit_ref: str = "direct-canonical-excel",
) -> CompiledWorkbook:
    """Compile spreadsheet rows into canonical writer commands.

    ``observed_at`` is generated by infrastructure, never read from workbook
    cells. It gives direct canonical facts a deterministic effective ordering;
    the generated spec facts themselves carry no source/evidence metadata.

    ``audit_ref`` remains accepted for call-site compatibility but is not written
    into vehicle facts.
    """
    _ = audit_ref
    raw_rows = list(rows)
    if not raw_rows:
        raise SpecExcelError("workbook has no data rows")
    if not any(IDENTITY_COLUMN in row for row in raw_rows):
        raise SpecExcelError(f"workbook requires {IDENTITY_COLUMN!r}")

    headers: list[str] = []
    seen_headers: set[str] = set()
    for row in raw_rows:
        for key in row:
            header = _text(key)
            if header and header not in seen_headers:
                seen_headers.add(header)
                headers.append(header)
    targets = build_column_targets(headers, registry)
    facts_by_id = _existing_facts_by_id(existing_facts)

    commands: list[dict[str, Any]] = []
    rows_changed = 0
    values_written = 0
    values_unchanged = 0

    for row_number, row in enumerate(raw_rows, start=2):
        trim_id = _text(row.get(IDENTITY_COLUMN, ""))
        if not trim_id:
            if all(_is_blank(value) for value in row.values()):
                continue
            raise SpecExcelError(f"row {row_number}: canonical_trim_id is required")
        trim = catalog.trims.get(trim_id)
        if trim is None:
            raise SpecExcelError(f"row {row_number}: unknown canonical_trim_id {trim_id!r}")
        generation = catalog.generations[trim.generation_id]
        model = catalog.models[generation.model_id]

        core_patch: dict[str, Any] = {}
        spec_commands: list[dict[str, Any]] = []

        for header, target in targets.items():
            value = row.get(header)
            if _is_blank(value):
                continue

            if target.field_key is None:
                assert target.core_field is not None
                incoming = _coerce_core(target.core_field, value)
                current = getattr(trim, target.core_field)
                if _same(current, incoming):
                    values_unchanged += 1
                else:
                    core_patch[target.core_field] = incoming
                    values_written += 1
                continue

            definition = registry.fields[target.field_key]
            state, incoming = _coerce_spec(value, definition)
            qualifiers = dict(target.qualifiers or {})

            if target.field_key == "identity.powertrain" and state is ValueState.KNOWN:
                if str(incoming).upper() != trim.powertrain.value:
                    raise SpecExcelError(
                        f"row {row_number}: identity.powertrain {incoming!r} contradicts "
                        f"canonical trim powertrain {trim.powertrain.value!r}")

            if (definition.applicable_powertrains
                    and trim.powertrain.value not in definition.applicable_powertrains):
                # Registry applicability already says the field does not exist
                # for this powertrain. The legacy SpecLedger rejects even a
                # stored NOT_APPLICABLE fact, so the explicit token is the same
                # deterministic no-op as leaving the cell blank.
                if state is ValueState.NOT_APPLICABLE:
                    values_unchanged += 1
                    continue
                raise SpecExcelError(
                    f"row {row_number}: {target.field_key} does not apply to {trim.powertrain.value}; "
                    "use NOT_APPLICABLE or leave blank")

            validation = definition.validate_value(
                state, incoming, definition.canonical_unit if state is ValueState.KNOWN else "")
            if validation:
                raise SpecExcelError(
                    f"row {row_number}: {target.field_key}: " + "; ".join(validation))

            fact_id = _fact_id(trim_id, target.field_key, qualifiers)
            existing = facts_by_id.get(fact_id)
            same_fact = bool(
                existing is not None
                and existing.trim_id == trim_id
                and existing.field_key == target.field_key
                and existing.value_state is state
                and existing.value == incoming
                and existing.unit == (definition.canonical_unit if state is ValueState.KNOWN else "")
                and dict(existing.qualifiers) == qualifiers
            )
            if same_fact:
                values_unchanged += 1
            else:
                payload = {
                    "fact_id": fact_id,
                    "trim_id": trim_id,
                    "field_key": target.field_key,
                    "value_state": state.value,
                    "value": incoming,
                    "unit": definition.canonical_unit if state is ValueState.KNOWN else "",
                    "qualifiers": qualifiers,
                    "observed_at": observed_at,
                    "verification_status": "VERIFIED",
                }
                spec_commands.append({
                    "operation": "APPEND_SPEC",
                    "canonical_id": trim_id,
                    "payload": payload,
                })
                values_written += 1

            if target.core_field is not None and state is ValueState.KNOWN:
                core_value = _coerce_core(target.core_field, incoming)
                current_core = getattr(trim, target.core_field)
                if not _same(current_core, core_value):
                    core_patch[target.core_field] = core_value

        row_commands: list[dict[str, Any]] = []
        if core_patch:
            row_commands.append({
                "operation": "UPSERT_MODEL_BUNDLE",
                "canonical_id": model.id,
                "payload": {
                    "brand": {"id": model.brand_id},
                    "model": {},
                    "generation": {"code": generation.code},
                    "variants": [],
                    "trims": [{
                        "canonical_id": trim.id,
                        "name": trim.name,
                        "powertrain": trim.powertrain.value,
                        **core_patch,
                    }],
                },
            })
        row_commands.extend(spec_commands)
        if row_commands:
            rows_changed += 1
            commands.extend(row_commands)

    return CompiledWorkbook(
        commands=tuple(commands),
        rows_read=len(raw_rows),
        rows_changed=rows_changed,
        values_written=values_written,
        values_unchanged=values_unchanged,
    )


__all__ = [
    "CompiledWorkbook", "ColumnTarget", "CORE_ONLY_HEADERS", "HEADER_ALIASES",
    "IDENTITY_COLUMN", "REGISTRY_TO_CORE", "SpecExcelError",
    "build_column_targets", "compile_rows",
]
