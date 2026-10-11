"""Evidence reference validation helpers; no retrieval or network code."""
from __future__ import annotations

import re

SHA256 = re.compile(r"^[a-f0-9]{64}$")


def validate_evidence(row: dict) -> list[str]:
    errors = []
    if row.get("market") != "TH": errors.append("MARKET_NOT_TH")
    if not SHA256.fullmatch(str(row.get("document_sha256", ""))): errors.append("INVALID_DOCUMENT_HASH")
    if not row.get("captured_at"): errors.append("CAPTURE_TIME_MISSING")
    if not row.get("locator"): errors.append("LOCATOR_MISSING")
    if row.get("source_authority") not in {"OFFICIAL", "ADMIN", "AI"}: errors.append("SOURCE_AUTHORITY_INVALID")
    if row.get("extraction_actor") not in {"AI", "HUMAN"}: errors.append("EXTRACTION_ACTOR_INVALID")
    if row.get("completeness") not in {"COMPLETE_LINEUP", "PARTIAL_TRIM_LIST", "INDIVIDUAL_TRIM"}: errors.append("COMPLETENESS_INVALID")
    return errors
