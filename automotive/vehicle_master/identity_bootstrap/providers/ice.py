"""Ice Full Package -> Identity Bootstrap input snapshot. Pure: takes parsed rows, returns a snapshot; no file or database access.

Everything Ice-specific lives here and nowhere else: Buddhist -> Gregorian periods, what `__provisional` and `BRAND|MODEL` ids mean,
the `id_changes.csv` type words, the evidence reference format, which dims columns are offered as UNVERIFIED hints.
Resolution results, brand resolution and subject relations come from the Identity Resolution layer (or, in the shadow run, its stand-in).
"""
from __future__ import annotations

from collections.abc import Callable, Iterable

PROVIDER = "ice"
PROVISIONAL_SUFFIX = "__provisional"
RAW_SEPARATOR = "|"
LINEAGE_TYPES = {"เปลี่ยนรหัส": "RENAME", "รวม": "MERGE", "แยก": "SPLIT"}
HINT_COLUMNS = {"body": "body", "segment": "segment"}      # dims columns offered to enrichment as UNVERIFIED provider claims


def to_gregorian(period_be: str) -> str:
    """'2569-09' (Buddhist era) -> '2026-09'."""
    year, month = period_be.split("-")
    return f"{int(year) - 543:04d}-{month}"


def identity_status(model_group_id: str) -> str:
    """Ice marks an identity it has not settled with a suffix (provisional) or with a raw 'BRAND|NAME' registration id (an unmapped name)."""
    if model_group_id.endswith(PROVISIONAL_SUFFIX):
        return "provisional"
    if RAW_SEPARATOR in model_group_id:
        return "unmapped_name"
    return "settled"


def lineage_events(id_changes: Iterable[dict]) -> list[dict]:
    events = []
    for row in id_changes:
        kind = LINEAGE_TYPES.get(row["type"].strip())
        if kind is None:
            raise ValueError(f"unknown id_changes type {row['type']!r}")     # never guess a lineage meaning
        events.append({"event_type": kind, "old_id": row["old_model_group_id"], "new_id": row["new_model_group_id"]})
    return events


def evidence_ref(source_label: str, model_group_id: str) -> str:
    return f"{source_label}#model_group/{model_group_id}"


def build_snapshot(*, source_label: str, policy_version: int, as_of_period_be: str, dims: list[dict], first_seen_be: dict[str, str],
                   id_changes: list[dict], identities: list[dict], bindings: list[dict] | None = None,
                   brand_for: Callable[[str], dict], resolution_for: Callable[[dict], dict],
                   relations_for: Callable[[dict], list[dict]]) -> dict:
    """`dims` are dims/model_group.csv rows. `first_seen_be` maps model_group_id -> first Buddhist period seen in reg_trend."""
    subjects = []
    for row in dims:
        gid = row["model_group_id"]
        hints = {out: row[col].strip() for out, col in HINT_COLUMNS.items() if row.get(col, "").strip() and row[col].strip() != "ไม่ระบุ"}
        subject = {
            "provider": PROVIDER, "entity_id": gid, "display_name": row["model_name"], "brand": brand_for(row["brand"]),
            "identity_status": identity_status(gid), "first_seen_period": to_gregorian(first_seen_be[gid]),
            "units": float(row["reg_total_all"]),                       # routing/priority only (SPEC invariant I3)
            "evidence": [{"kind": "PROVIDER_IDENTITY", "ref": evidence_ref(source_label, gid)}],
            "resolution": resolution_for(row), "relations": relations_for(row),
        }
        if hints:
            subject["provider_hints"] = hints
        subjects.append(subject)
    return {
        "contract_version": 1, "policy_version": policy_version, "provider": PROVIDER, "source_version": {"label": source_label},
        "as_of_period": to_gregorian(as_of_period_be), "subjects": subjects, "identities": identities, "bindings": bindings or [],
        "lineage": {"declared_identity_change": bool(id_changes), "source_present": True, "events": lineage_events(id_changes)},
    }
