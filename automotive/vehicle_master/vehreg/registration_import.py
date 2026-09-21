"""Parse a DLT registration file and resolve its rows against saved aliases.

Registration is not vehicle data. A DLT file says how many of something
were registered in a month; it never says what that something's engine is,
and nothing in this module may touch a spec, a trim or a canonical model.
Rows it can place are written to ``registrations``; rows carrying an
identity nobody has taught the crosswalk yet come back as unknowns for a
person to resolve once.

Grain is whatever the source published. DLT prints the grade inside the
model field for some marques and not others (``Brand.trim_detail``), so the
raw label is stored exactly as filed and only the *lookup key* is folded.
Nothing here infers a trim from a row that does not name one, and nothing
flattens a row that does.

Idempotency comes from the table's own key,
``(period, registration_type, brand_name_raw, model_name_raw)``: the same
month re-uploaded replaces its rows, a corrected file corrects them, and a
new month appends.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Any, Iterable

#: Column spellings a DLT export has arrived with. Anything else is an
#: unsupported schema, reported rather than guessed at.
_COLUMNS = {
    "period": ("period", "เดือน"),
    "registration_type": ("registration_type", "ประเภท"),
    "brand": ("brand", "brand_name_raw", "ยี่ห้อ"),
    "model": ("model", "model_name_raw", "แบบรถ"),
    "units": ("units", "registrations", "จำนวน"),
}

MATCHED = "MATCHED"
UNKNOWN = "UNKNOWN"


class UnsupportedRegistrationSchema(Exception):
    """The file is not a registration export this importer understands."""


@dataclass(frozen=True)
class RegistrationRow:
    period: str
    registration_type: str
    brand_raw: str
    model_raw: str
    units: int


@dataclass(frozen=True)
class ResolvedRegistration:
    row: RegistrationRow
    status: str
    #: Legacy registration identity (models.id), when the crosswalk has one.
    model_id: str | None = None
    #: Canonical vehicle identity, preferred and usable the day a car is
    #: created -- no legacy row has to exist first.
    canonical_model_id: str | None = None
    #: Only ever set where the source itself published trim detail and a
    #: deterministic mapping exists for it. Never inferred from a
    #: model-level row.
    canonical_trim_id: str | None = None
    reason: str = ""


def normalize_token(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    return re.sub(r"[^\w]+", "", text, flags=re.UNICODE).strip()


def _column_map(fieldnames: Iterable[str]) -> dict[str, str]:
    present = {str(name).strip().lower(): str(name) for name in fieldnames if name}
    mapping: dict[str, str] = {}
    for key, spellings in _COLUMNS.items():
        for spelling in spellings:
            if spelling in present:
                mapping[key] = present[spelling]
                break
    missing = sorted(set(_COLUMNS) - set(mapping))
    if missing:
        raise UnsupportedRegistrationSchema(
            "registration file is missing required column(s): " + ", ".join(missing))
    return mapping


def parse_registration_rows(records: list[dict[str, Any]]) -> tuple[list[RegistrationRow], list[dict]]:
    """Read an export into rows. Raises when the file is not one at all."""
    if not records:
        raise UnsupportedRegistrationSchema("registration file has no rows")
    mapping = _column_map(records[0].keys())

    rows: list[RegistrationRow] = []
    rejected: list[dict] = []
    for index, record in enumerate(records, start=1):
        period = str(record.get(mapping["period"]) or "").strip()
        brand = str(record.get(mapping["brand"]) or "").strip()
        model = str(record.get(mapping["model"]) or "").strip()
        raw_units = str(record.get(mapping["units"]) or "").strip().replace(",", "")
        registration_type = str(record.get(mapping["registration_type"]) or "").strip() or "*"
        if not (period and brand and model):
            rejected.append({"row": index, "reason": "period, brand and model are all required"})
            continue
        try:
            units = int(float(raw_units))
        except ValueError:
            rejected.append({"row": index, "reason": f"units is not a number: {raw_units!r}"})
            continue
        if units < 0:
            rejected.append({"row": index, "reason": "units cannot be negative"})
            continue
        rows.append(RegistrationRow(
            period=period, registration_type=registration_type,
            # Stored exactly as filed: the grade detail some marques print
            # inside this field is part of what the source said.
            brand_raw=brand, model_raw=model, units=units,
        ))
    return rows, rejected


def resolve_registrations(
    rows: Iterable[RegistrationRow],
    brand_aliases: dict[str, str],
    model_aliases: Iterable[dict[str, Any]],
) -> list[ResolvedRegistration]:
    """Match each row to a legacy model id through the saved crosswalk."""
    aliases = list(model_aliases)
    out: list[ResolvedRegistration] = []
    for row in rows:
        brand_norm = normalize_token(row.brand_raw)
        brand_id = brand_aliases.get(brand_norm)
        if not brand_id:
            out.append(ResolvedRegistration(
                row=row, status=UNKNOWN, reason=f"brand {row.brand_raw!r} is not in the crosswalk"))
            continue
        model_norm = normalize_token(row.model_raw)
        without_brand = (model_norm[len(brand_norm):]
                         if brand_norm and model_norm.startswith(brand_norm) else model_norm)
        candidates = []
        for alias in aliases:
            if str(alias.get("brand_id")) != brand_id:
                continue
            if str(alias.get("registration_type")) not in ("*", row.registration_type):
                continue
            token = str(alias.get("alias_norm") or "")
            mode = str(alias.get("match_mode") or "prefix")
            hit = ((model_norm == token or without_brand == token) if mode == "exact"
                   else (token and (model_norm.startswith(token) or without_brand.startswith(token))))
            if hit:
                candidates.append((
                    1 if str(alias.get("registration_type")) == row.registration_type else 0,
                    len(token),
                    str(alias.get("model_id") or ""),
                    str(alias.get("canonical_model_id") or ""),
                    str(alias.get("canonical_trim_id") or ""),
                ))
        if not candidates:
            out.append(ResolvedRegistration(
                row=row, status=UNKNOWN, reason=f"no saved mapping for {row.model_raw!r}"))
            continue
        candidates.sort(reverse=True, key=lambda c: (c[0], c[1]))
        best = [c for c in candidates if (c[0], c[1]) == (candidates[0][0], candidates[0][1])]
        targets = {(c[2], c[3], c[4]) for c in best}
        if len(targets) != 1:
            out.append(ResolvedRegistration(
                row=row, status=UNKNOWN,
                reason=f"{len(targets)} saved mappings match {row.model_raw!r} equally well"))
            continue
        model_id, canonical_model_id, canonical_trim_id = targets.pop()
        out.append(ResolvedRegistration(
            row=row, status=MATCHED, model_id=model_id or None,
            canonical_model_id=canonical_model_id or None,
            canonical_trim_id=canonical_trim_id or None))
    return out


def snapshot_rows(resolved: Iterable[ResolvedRegistration]) -> list[dict]:
    """Every row of the month, matched or not.

    An unmatched row is still a registration fact: the month's total does
    not change because nobody has taught the crosswalk what that label is
    yet. It is written with no canonical mapping and its raw labels intact,
    and the exception beside it is the mapping work, not the number.
    """
    return [registration_payload(item) for item in resolved]


def registration_payload(resolved: ResolvedRegistration) -> dict:
    """One row of the snapshot, matched or not.

    The raw labels go in exactly as the source filed them -- the grade
    detail some marques print inside the model field is part of what was
    published, and folding it away would turn a trim-level row into a
    model-level one.
    """
    row = resolved.row
    matched = resolved.status == MATCHED
    return {
        "period": row.period,
        "registration_type": row.registration_type,
        "brand_name_raw": row.brand_raw,
        "model_name_raw": row.model_raw,
        "registrations": row.units,
        "model_id": resolved.model_id,
        "canonical_model_id": resolved.canonical_model_id,
        "canonical_trim_id": resolved.canonical_trim_id,
        "mapping_method": "import-alias" if matched else "unmapped",
    }


def exception_rows(resolved: Iterable[ResolvedRegistration]) -> list[dict]:
    """The mapping work an import leaves behind, one row per unknown label."""
    return [{
        "kind": "REGISTRATION_IDENTITY",
        "reason": item.reason,
        "source_identity": {
            "period": item.row.period,
            "registration_type": item.row.registration_type,
            "brand": item.row.brand_raw,
            "model": item.row.model_raw,
            "units": item.row.units,
            # Grain is whatever the source published. A label with no trim
            # detail is a model-level exception and must not be handed a
            # trim picker.
            "grain": "MODEL",
        },
    } for item in resolved if item.status != MATCHED]
