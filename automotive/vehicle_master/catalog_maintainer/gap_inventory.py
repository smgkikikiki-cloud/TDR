"""Applicable gaps using Vehicle Master value_state, locks, and payload layers."""
from __future__ import annotations

PRICE_KEYS = {"LIST_PRICE", "CAMPAIGN_PRICE", "ECO_STICKER_PRICE", "MSRP", "PRICE"}
VALID_VALUE_STATES = {"KNOWN", "UNKNOWN", "NOT_AVAILABLE", "NOT_APPLICABLE", "ABSENT", None}


def _present(value: object) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def _payload_value(snapshot: dict, trim: dict, key: str) -> tuple[bool, str | None, object]:
    value = trim.get("specs", {}).get(key)
    if _present(value):
        return True, "TRIM_PAYLOAD", value
    variant = next((v for v in snapshot.get("variants", []) if v.get("id") == trim.get("variant_id")), None)
    value = variant.get("specs", {}).get(key) if variant else None
    if _present(value):
        return True, "VARIANT_PAYLOAD", value
    model = next((m for m in snapshot.get("models", []) if m.get("id") == trim.get("model_id")), {})
    generation = next((g for g in snapshot.get("generations", []) if g.get("id") == trim.get("generation_id")), {})
    value = generation.get("specs", {}).get(key)
    if _present(value):
        return True, "GENERATION_PAYLOAD", value
    value = model.get("specs", {}).get(key)
    if _present(value):
        return True, "MODEL_PAYLOAD", value
    return False, None, None


def _active(fact: dict, as_of: str) -> bool:
    start, end = fact.get("effective_from"), fact.get("effective_to")
    return (not start or start <= as_of) and (not end or end >= as_of)


def _facts_for(facts: list[dict], trim_id: str, key: str, as_of: str) -> list[dict]:
    return [f for f in facts if f.get("trim_id") == trim_id and f.get("field_key") == key
            and _active(f, as_of)]


def _conflicting(rows: list[dict]) -> bool:
    if len(rows) < 2:
        return any(f.get("value_state") == "CONFLICT" for f in rows)
    signatures = {(f.get("value_state"), repr(f.get("value"))) for f in rows}
    return len(signatures) > 1 or any(f.get("value_state") == "CONFLICT" for f in rows)


def gaps_for_model(snapshot: dict, trim_ids: tuple[str, ...]) -> dict:
    by_id = {t["id"]: t for t in snapshot.get("trims", [])}
    facts = snapshot.get("facts", [])
    as_of = snapshot.get("as_of", "9999-12-31")
    groups: dict[str, dict] = {}
    dispositions = []
    for trim_id in trim_ids:
        trim = by_id[trim_id]
        for field in snapshot.get("field_registry", []):
            key, tier = field["key"], field["tier"]
            if tier not in {"P1", "P2"} or key.upper() in PRICE_KEYS or field.get("owner") == "PRICE_LEDGER":
                continue
            applicable = field.get("applicable_powertrains", [])
            if applicable and trim.get("powertrain") not in applicable:
                dispositions.append({"trim_id": trim_id, "field_key": key, "state": "NOT_APPLICABLE"})
                continue

            rows = _facts_for(facts, trim_id, key, as_of)
            locked_clears = [f for f in rows if f.get("locked") and f.get("value") is None
                             and f.get("value_state") is None]
            if locked_clears:
                dispositions.append({"trim_id": trim_id, "field_key": key, "state": "TOMBSTONED_LOCKED"})
                continue
            locked_states = [f for f in rows if f.get("locked")
                             and f.get("value_state") in {"ABSENT", "UNKNOWN", "NOT_AVAILABLE"}]
            if locked_states:
                dispositions.append({"trim_id": trim_id, "field_key": key, "state": "TOMBSTONED_LOCKED"})
                continue
            if _conflicting(rows):
                dispositions.append({"trim_id": trim_id, "field_key": key, "state": "CONFLICT"})
                continue
            fact = rows[0] if rows else None
            if fact and fact.get("value_state") == "NOT_APPLICABLE":
                has_payload, _, payload = _payload_value(snapshot, trim, key)
                state = "CONFLICT" if has_payload else "NOT_APPLICABLE"
                dispositions.append({"trim_id": trim_id, "field_key": key, "state": state})
                continue
            if fact and fact.get("value_state") in {"ABSENT", "NOT_AVAILABLE"}:
                has_payload, _, _ = _payload_value(snapshot, trim, key)
                state = "CONFLICT" if has_payload else ("ABSENT" if fact["value_state"] == "ABSENT" else "SOURCE_EXHAUSTED")
                dispositions.append({"trim_id": trim_id, "field_key": key, "state": state})
                continue
            if fact and fact.get("value_state") == "KNOWN" and _present(fact.get("value")):
                has_payload, _, payload = _payload_value(snapshot, trim, key)
                if has_payload and payload != fact.get("value"):
                    dispositions.append({"trim_id": trim_id, "field_key": key, "state": "CONFLICT"})
                    continue
                if fact.get("verification_status") != "VERIFIED" or not fact.get("source_ref"):
                    dispositions.append({"trim_id": trim_id, "field_key": key, "state": "NEEDS_SOURCE_TRACE"})
                else:
                    dispositions.append({"trim_id": trim_id, "field_key": key,
                                         "state": "ALREADY_KNOWN", "layer": "CANONICAL_FACT"})
                continue
            if fact and fact.get("value_state") == "KNOWN" and not _present(fact.get("value")):
                dispositions.append({"trim_id": trim_id, "field_key": key, "state": "CONFLICT"})
                continue
            payload_has_value, payload_layer, _ = _payload_value(snapshot, trim, key)
            if payload_has_value:
                if fact and fact.get("value_state") == "UNKNOWN":
                    dispositions.append({"trim_id": trim_id, "field_key": key, "state": "CONFLICT"})
                    continue
                dispositions.append({"trim_id": trim_id, "field_key": key,
                                     "state": "ALREADY_KNOWN", "layer": payload_layer})
                continue

            # UNKNOWN is a gap even if a separate verification_status says VERIFIED.
            # UNKNOWN != ABSENT and never becomes known through the verification flag.
            if fact and fact.get("value_state") == "UNKNOWN":
                state = "UNKNOWN"
            else:
                state = "MISSING"
            dispositions.append({"trim_id": trim_id, "field_key": key, "state": state})
            bucket = groups.setdefault(field.get("group", "OTHER"),
                                       {"field_keys_by_tier": {}, "trim_ids_by_field": {}})
            bucket["field_keys_by_tier"].setdefault(tier, set()).add(key)
            bucket["trim_ids_by_field"].setdefault(key, []).append(trim_id)

    normalized = {}
    for group, row in sorted(groups.items()):
        fields_by_tier = {tier: sorted(keys) for tier, keys in sorted(row["field_keys_by_tier"].items())}
        normalized[group] = {"tiers": sorted(fields_by_tier), "field_keys_by_tier": fields_by_tier,
                             "field_keys": sorted({k for keys in fields_by_tier.values() for k in keys}),
                             "trim_ids_by_field": {k: sorted(set(v)) for k, v in sorted(row["trim_ids_by_field"].items())}}
    return {"groups": normalized,
            "dispositions": sorted(dispositions, key=lambda x: (x["trim_id"], x["field_key"], x["state"]))}
