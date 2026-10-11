"""Applicable field gaps, resolving values across canonical and payload layers."""
from __future__ import annotations

PRICE_KEYS = {"LIST_PRICE", "CAMPAIGN_PRICE", "ECO_STICKER_PRICE", "MSRP", "PRICE"}
KNOWN_STATES = {"KNOWN", "PRESENT", "VERIFIED", "OBSERVED"}


def _present(value: object) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def _payload_value(snapshot: dict, trim: dict, key: str) -> bool:
    if _present(trim.get("specs", {}).get(key)):
        return True
    variant = next((v for v in snapshot.get("variants", []) if v.get("id") == trim.get("variant_id")), None)
    if variant and _present(variant.get("specs", {}).get(key)):
        return True
    model = next((m for m in snapshot.get("models", []) if m.get("id") == trim.get("model_id")), {})
    generation = next((g for g in snapshot.get("generations", []) if g.get("id") == trim.get("generation_id")), {})
    return _present(model.get("specs", {}).get(key)) or _present(generation.get("specs", {}).get(key))


def gaps_for_model(snapshot: dict, trim_ids: tuple[str, ...]) -> dict:
    by_id = {t["id"]: t for t in snapshot.get("trims", [])}
    facts = snapshot.get("facts", [])
    groups: dict[str, dict] = {}
    dispositions = []
    for trim_id in trim_ids:
        trim = by_id[trim_id]
        for field in snapshot.get("field_registry", []):
            key, tier = field["key"], field["tier"]
            if tier == "P3" or key.upper() in PRICE_KEYS or field.get("owner") == "PRICE_LEDGER":
                continue
            applicable = field.get("applicable_powertrains", [])
            if applicable and trim.get("powertrain") not in applicable:
                dispositions.append({"trim_id": trim_id, "field_key": key, "state": "NOT_APPLICABLE"})
                continue
            relevant = [f for f in facts if f.get("trim_id") == trim_id and f.get("field_key") == key]
            fact = relevant[-1] if relevant else None
            if fact and fact.get("value_state") == "SOURCE_EXHAUSTED":
                dispositions.append({"trim_id": trim_id, "field_key": key, "state": "SOURCE_EXHAUSTED"})
                continue
            if fact and fact.get("locked") and fact.get("value_state") in {"ABSENT", "UNKNOWN", "NO"}:
                dispositions.append({"trim_id": trim_id, "field_key": key, "state": "TOMBSTONED_LOCKED"})
                continue
            if fact and fact.get("value_state") == "CONFLICT":
                dispositions.append({"trim_id": trim_id, "field_key": key, "state": "CONFLICT"})
                continue
            if fact and fact.get("value_state") in KNOWN_STATES and _present(fact.get("value")):
                if not fact.get("source_ref"):
                    dispositions.append({"trim_id": trim_id, "field_key": key, "state": "NEEDS_SOURCE_TRACE"})
                continue
            if _payload_value(snapshot, trim, key):
                dispositions.append({"trim_id": trim_id, "field_key": key, "state": "ALREADY_KNOWN", "layer": "PAYLOAD"})
                continue
            if fact and fact.get("value_state") in {"ABSENT", "NO"}:
                dispositions.append({"trim_id": trim_id, "field_key": key, "state": fact["value_state"]})
                continue
            if fact and fact.get("value_state") == "UNKNOWN":
                dispositions.append({"trim_id": trim_id, "field_key": key, "state": "UNKNOWN"})
            elif not fact:
                dispositions.append({"trim_id": trim_id, "field_key": key, "state": "MISSING"})
            bucket = groups.setdefault(field.get("group", "OTHER"), {"tier": tier, "field_keys": set(), "trim_ids_by_field": {}})
            bucket["field_keys"].add(key)
            bucket["trim_ids_by_field"].setdefault(key, []).append(trim_id)
    normalized = {g: {"tier": x["tier"], "field_keys": sorted(x["field_keys"]),
                      "trim_ids_by_field": {k: sorted(v) for k, v in sorted(x["trim_ids_by_field"].items())}}
                  for g, x in sorted(groups.items())}
    return {"groups": normalized, "dispositions": sorted(dispositions, key=lambda x: (x["trim_id"], x["field_key"], x["state"]))}
