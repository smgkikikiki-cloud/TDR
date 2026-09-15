"""The DLT v2 observation layer: one immutable, reproducible row per source fact.

An observation is *what a source said*, before any canonical-identity opinion
is formed about it. It is never mutated once written, and it is never
reinterpreted by a later pass - a resolution result (``resolution_v2.py``) is
a separate, derived thing that references an observation by id, it does not
replace or edit it. This is Invariant 14 (`docs/vehicle-platform/INVARIANTS.md`):
source observation, canonical identity, and accepted fact are distinct
concepts.

Every observation carries a **deterministic** id and key, computed purely
from ``(source_kind, source_ref)`` - never a random UUID. Re-running an
adapter over the same source therefore produces byte-identical observation
ids, which is what makes the backfill/ingest tools idempotent: writing the
same observation twice is a no-op, not a duplicate.

Three adapters exist, one per source shape actually in production:

* ``from_dlt_record`` - one row of a DLT CKAN ``datastore_search`` result
  (see ``vehreg/dlt.py``), keyed by the CKAN resource id and the record's own
  stable ``_id``.
* ``from_mapped_row`` - one row of any column-mapped CSV
  (``vehreg.ingest.ColumnMap`` / ``read_rows``) - the shape the current DLT
  CSV fetcher writes, and also FTI/other registration exports. Keyed by a
  hash of the file's own sha256 plus the row's position, since a CSV has no
  natural stable row id.
* ``from_legacy_registration_row`` - one row of the live Supabase
  ``public.registrations`` table (the current production registration
  fact), for historical backfill. Keyed by the row's own stable ``id`` uuid.
  This adapter does not reinterpret or repair anything: a NULL/blank field
  in the legacy row stays blank here; the legacy ``model_id``/
  ``mapping_method`` are preserved only as ``source_metadata`` (parity
  evidence for the dual-run report), never as resolution input.

This module does no I/O and no canonical resolution. It only shapes rows a
caller already has in hand.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from .ingest import ColumnMap, _number
from .normalize import fold, period_key

#: Source kinds this module knows how to key/adapt. A tool writing v2 shadow
#: rows should never invent a fourth string here without adding an adapter -
#: the point of a closed vocabulary is that ``source_kind`` alone tells a
#: reader which adapter produced a row and what reproducibility guarantee it
#: carries.
DLT_CKAN = "dlt_ckan"
DLT_CSV = "dlt_csv"
LEGACY_REGISTRATIONS_BACKFILL = "legacy_registrations_backfill"

SOURCE_KINDS = frozenset({DLT_CKAN, DLT_CSV, LEGACY_REGISTRATIONS_BACKFILL})


def observation_id(source_kind: str, source_ref: str) -> str:
    """Deterministic id: a pure function of the source's own identity.

    Never random. The same ``(source_kind, source_ref)`` always yields the
    same id, which is the whole idempotency guarantee the backfill/ingest
    tools rely on: writing the same observation twice upserts the same row
    instead of creating a duplicate.
    """
    digest = hashlib.sha256(f"{source_kind}\n{source_ref}".encode("utf-8"))
    return digest.hexdigest()[:32]


def _payload_hash(fields: Mapping[str, Any]) -> str:
    """Reproducibility evidence: a hash of the raw fields, before resolution.

    A re-fetch of the same source that returns the same content reproduces
    this hash exactly; a re-fetch that returns different content (a source
    correction, a transcription fix) changes it, and that drift is visible
    without depending on the observation id itself carrying content.
    """
    canonical = json.dumps(fields, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class RegistrationObservation:
    """One immutable row of source registration data, before resolution.

    ``province`` defaults to ``"ALL"`` for every source that does not
    publish province (every source in production today) - never left blank,
    since "no province in the source" and "province blank in this one row"
    are different facts and only the first is common enough to deserve a
    fixed sentinel.
    """

    observation_id: str
    source_kind: str
    source_ref: str
    period: str                    # 'YYYY-MM'
    registration_type: str
    province: str
    raw_brand: str
    raw_model: str
    raw_variant: str
    raw_label: str
    units: float
    normalized_brand: str
    normalized_model: str
    payload_hash: str
    source_metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, str]:
        return (self.source_kind, self.source_ref)


def _build(*, source_kind: str, source_ref: str, period: str,
           registration_type: str, province: str, raw_brand: str,
           raw_model: str, raw_variant: str, units: float,
           source_metadata: Mapping[str, Any]) -> RegistrationObservation:
    if source_kind not in SOURCE_KINDS:
        raise ValueError(f"unknown source_kind {source_kind!r}")
    raw_label = " ".join(x for x in (raw_brand, raw_model, raw_variant) if x)
    raw_fields = {
        "period": period, "registration_type": registration_type,
        "province": province, "raw_brand": raw_brand, "raw_model": raw_model,
        "raw_variant": raw_variant, "units": units,
    }
    return RegistrationObservation(
        observation_id=observation_id(source_kind, source_ref),
        source_kind=source_kind, source_ref=source_ref, period=period,
        registration_type=registration_type, province=province or "ALL",
        raw_brand=raw_brand, raw_model=raw_model, raw_variant=raw_variant,
        raw_label=raw_label, units=units,
        normalized_brand=fold(raw_brand), normalized_model=fold(raw_model),
        payload_hash=_payload_hash(raw_fields),
        source_metadata=dict(source_metadata),
    )


def from_dlt_record(record: Mapping[str, Any], *, resource_id: str,
                    period: str, registration_type: str) -> RegistrationObservation:
    """One row of a DLT CKAN ``datastore_search`` result.

    ``record`` is the raw CKAN dict (``ยี่ห้อ``/``รุ่น``/``จำนวน``/``_id``/
    ``ประเภทรถ``); ``registration_type`` is the already-classified RY1/RY2/RY3
    value (``vehreg.dlt.REGISTRATION_BY_THAI_TYPE``) - this adapter does not
    reclassify, it only shapes. CKAN's own ``_id`` is a stable per-resource
    sequence, so ``resource_id:_id`` is a real, reproducible source_ref: the
    same record fetched again gets the same id.
    """
    record_id = record.get("_id")
    source_ref = f"{resource_id}:{record_id}"
    units_raw = record.get("จำนวน")
    try:
        units = float(str(units_raw).replace(",", ""))
    except (TypeError, ValueError):
        units = 0.0
    return _build(
        source_kind=DLT_CKAN, source_ref=source_ref, period=period,
        registration_type=registration_type, province="ALL",
        raw_brand=str(record.get("ยี่ห้อ", "")).strip(),
        raw_model=str(record.get("รุ่น", "")).strip(),
        raw_variant="", units=units,
        source_metadata={
            "resource_id": resource_id, "ckan_record_id": record_id,
            "dlt_class_raw": str(record.get("ประเภทรถ", "")).strip(),
        },
    )


def from_mapped_row(row: Mapping[str, Any], colmap: ColumnMap, *,
                    file_sha256: str, row_index: int,
                    default_registration_type: str = "RY1") -> Optional[RegistrationObservation]:
    """One row of a column-mapped CSV (``vehreg.ingest.read_rows``).

    Covers the current DLT CSV fetcher's own output (``vehreg/dlt.py``'s
    ``fetch_month``) and any other file the existing ingest column-sniffer
    can map. There is no stable row id in a CSV, so the source_ref is the
    file's own content hash plus the row's position - reproducible for the
    same file, distinct across files even with identical content elsewhere.
    Returns ``None`` for a row with unreadable units or period, mirroring
    ``vehreg.ingest.ingest_csv``'s own "never guess, queue instead" rule -
    the caller is expected to treat a ``None`` return as a row that could not
    even become an observation and report it separately.
    """
    units = _number(row.get(colmap.units)) if colmap.units else None
    if units is None:
        return None
    try:
        period = period_key(row.get(colmap.period)) if colmap.period else ""
    except (ValueError, TypeError):
        return None
    if not period:
        return None
    reg_raw = (str(row.get(colmap.registration_type) or "").strip()
              if colmap.registration_type else "")
    source_ref = f"{file_sha256}:{row_index}"
    return _build(
        source_kind=DLT_CSV, source_ref=source_ref, period=period,
        registration_type=reg_raw or default_registration_type,
        province=(str(row.get(colmap.province) or "").strip()
                 if colmap.province else "ALL"),
        raw_brand=(str(row.get(colmap.brand) or "").strip()
                  if colmap.brand else ""),
        raw_model=(str(row.get(colmap.model) or "").strip()
                  if colmap.model else ""),
        raw_variant=(str(row.get(colmap.variant) or "").strip()
                    if colmap.variant else ""),
        units=units,
        source_metadata={"file_sha256": file_sha256, "row_index": row_index},
    )


def from_legacy_registration_row(row: Mapping[str, Any]) -> RegistrationObservation:
    """One row of the live Supabase ``public.registrations`` table.

    Used only for historical backfill. The row's own ``id`` (a stable uuid
    primary key, ``supabase/schema.sql``) is the source_ref - reproducible
    across reruns since that id never changes for an existing row. The
    legacy ``model_id``/``mapping_method`` are carried into
    ``source_metadata`` verbatim, as parity evidence for the dual-run
    report - this adapter never treats them as canonical resolution input,
    and never repairs a blank/NULL field. ``public.registrations`` has no
    province column, so province is always ``"ALL"`` here - not a per-row
    judgment, a fact about the source.
    """
    period_raw = str(row["period"])   # 'YYYY-MM-DD' (first of month)
    period = period_raw[:7]
    return _build(
        source_kind=LEGACY_REGISTRATIONS_BACKFILL, source_ref=str(row["id"]),
        period=period,
        registration_type=str(row.get("registration_type") or "*"),
        province="ALL",
        raw_brand=str(row.get("brand_name_raw") or ""),
        raw_model=str(row.get("model_name_raw") or ""),
        raw_variant="",
        units=float(row.get("registrations") or 0),
        source_metadata={
            "legacy_registration_id": str(row["id"]),
            "legacy_model_id": (str(row["model_id"])
                                if row.get("model_id") else None),
            "legacy_mapping_method": row.get("mapping_method"),
            "legacy_source_id": (str(row["source_id"])
                                 if row.get("source_id") else None),
        },
    )


def reconciles(observations: list[RegistrationObservation], *,
              expected_total: float, tolerance: float = 0.001) -> bool:
    """Invariant 8: the sum of every observation's units equals the source
    total it was built from. A caller that fetched N rows summing to X from
    a source must be able to prove the N observations it built also sum to
    X - this is that proof, not a fact-layer computation."""
    return abs(sum(o.units for o in observations) - expected_total) <= tolerance
