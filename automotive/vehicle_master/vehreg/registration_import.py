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


class MalformedSnapshotError(Exception):
    """A row inside an otherwise-recognised file cannot be trusted as a fact.

    An official monthly export is a complete snapshot, and the replace RPC
    (tdr_replace_registration_period) deletes the whole month before
    re-inserting it. Writing only the rows that parsed and quietly
    dropping the rest would silently delete units the malformed rows
    represented -- the month goes from N to (N minus whatever was
    unreadable), and nothing says so. This is raised BEFORE any write is
    attempted, so the month is left exactly as it was and the file can be
    fixed and re-uploaded.

    An unknown brand or model is not this: the row is well-formed, it is
    just not yet resolvable, and it is written as a fact with the
    resolution left open (see resolve_registrations/exception_rows). Only
    a row that cannot be trusted as a registration fact at all -- a
    missing period/brand/model, non-numeric units, a mixed period across
    the file -- raises this.
    """

    def __init__(self, rejected: list[dict]):
        self.rejected = rejected
        reasons = "; ".join(f"row {item.get('row')}: {item.get('reason')}" for item in rejected[:10])
        more = f" (+{len(rejected) - 10} more)" if len(rejected) > 10 else ""
        super().__init__(f"{len(rejected)} row(s) cannot be trusted as registration facts: {reasons}{more}")


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


def _cell(record: dict[str, Any], key: str) -> str:
    """A raw field, blank meaning blank -- including a pandas NaN.

    ``pandas.read_csv``/``read_excel`` turn an empty cell into a float
    ``NaN``, and ``NaN`` is truthy in Python (``bool(float("nan"))`` is
    True), so ``record.get(key) or ""`` never falls through to the
    default and an empty brand or model cell silently became the four
    literal characters ``"nan"`` -- a value that passed the "brand and
    model are required" check it was supposed to fail. NaN is the one
    float that is never equal to itself; that is the only test used here,
    so this module still never has to import pandas to know about it.
    """
    value = record.get(key)
    if isinstance(value, float) and value != value:
        return ""
    return str(value if value is not None else "").strip()


def parse_units_cell(raw: object) -> tuple[Optional[int], Optional[str]]:
    """The one rule for what a registration count means, shared by every
    reader of a DLT-shaped export -- this browser importer and
    ``dlt.py``'s own CKAN fetcher alike.

    Returns ``(units, None)`` when the cell is a valid non-negative count,
    or ``(None, reason)`` when it is not. A count that cannot be trusted
    is never silently coerced to 0 or dropped by its caller without that
    caller knowing it happened -- two readers of the same source shape
    that disagreed here (one rejecting an unparsable count, the other
    quietly writing 0 for it) is exactly the kind of drift that lets the
    same bad row look like two different facts depending which path read
    it.
    """
    text = str(raw if raw is not None else "").strip().replace(",", "")
    if not text:
        return None, "units is required"
    try:
        units = int(float(text))
    except ValueError:
        return None, f"units is not a number: {text!r}"
    if units < 0:
        return None, "units cannot be negative"
    return units, None


def parse_registration_rows(records: list[dict[str, Any]]) -> tuple[list[RegistrationRow], list[dict]]:
    """Read an export into rows. Raises when the file is not one at all."""
    if not records:
        raise UnsupportedRegistrationSchema("registration file has no rows")
    mapping = _column_map(records[0].keys())

    rows: list[RegistrationRow] = []
    rejected: list[dict] = []
    for index, record in enumerate(records, start=1):
        period = _cell(record, mapping["period"])
        brand = _cell(record, mapping["brand"])
        model = _cell(record, mapping["model"])
        raw_units = _cell(record, mapping["units"])
        registration_type = _cell(record, mapping["registration_type"]) or "*"
        if not (period and brand and model):
            rejected.append({"row": index, "reason": "period, brand and model are all required"})
            continue
        units, reason = parse_units_cell(raw_units)
        if reason is not None:
            rejected.append({"row": index, "reason": reason})
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
    """Match each row to a legacy model id through the saved crosswalk.

    ``brand_aliases`` maps a normalised raw brand label to one token --
    the legacy ``brand_id`` (uuid) when the brand has one, else its
    ``canonical_brand_id``, whichever the caller's own query preferred.
    Either kind resolves the same way here: a model alias is a candidate
    for a brand when ITS OWN ``brand_id`` or ``canonical_brand_id``
    equals that same token, so a brand new enough to have no legacy row
    at all -- and therefore no ``brand_id`` anywhere -- still matches
    through the canonical id alone.
    """
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
            alias_brand = str(alias.get("brand_id") or alias.get("canonical_brand_id") or "")
            if alias_brand != brand_id:
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


def exception_rows(resolved: Iterable[ResolvedRegistration],
                   *, trim_detail_brands: Iterable[str] = ()) -> list[dict]:
    """The mapping work an import leaves behind, one row per unknown label.

    ``trim_detail_brands`` holds the normalised labels of the marques whose
    files print the grade inside the model field. It is the source's
    behaviour, passed in by the caller that knows the catalogue, and it is
    the only thing that can make an exception trim-grained: a label from a
    marque that files model names only must never be handed a trim picker,
    because the number behind it was never counted per trim.
    """
    detailed = frozenset(trim_detail_brands)
    return [{
        "kind": "REGISTRATION_IDENTITY",
        "reason": item.reason,
        "source_identity": {
            "period": item.row.period,
            "registration_type": item.row.registration_type,
            "brand": item.row.brand_raw,
            "model": item.row.model_raw,
            "units": item.row.units,
            "grain": ("TRIM" if normalize_token(item.row.brand_raw) in detailed
                      else "MODEL"),
        },
    } for item in resolved if item.status != MATCHED]
