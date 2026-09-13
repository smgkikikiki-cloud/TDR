#!/usr/bin/env python3
"""Apply the owner-provided 321-nameplate sub-model directory to canonical MarketTrim slots.

Conservative rules:
- Match a source nameplate to exactly one canonical model.
- Attach only to an unambiguous generation.
- Create/update a MarketTrim only when an exact canonical powertrain can be resolved.
- Never invent prices/specs, never alter analytical Variant rows, and never mark lifecycle CURRENT.
- Anything ambiguous is left untouched and written to apply_report.json.
"""

from __future__ import annotations

import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = ROOT / "vehreg" / "data" / "2026" / "models"
SOURCE_DIR = (
    ROOT
    / "vehreg"
    / "data"
    / "2026"
    / "market"
    / "trims"
    / "research"
    / "owner_directory_2026-09-13"
)
REPORT_PATH = SOURCE_DIR / "apply_report.json"

POWERTRAINS = {"ICE", "HEV", "PHEV", "REEV", "BEV", "FCEV"}


def norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = value.replace("&", " and ")
    value = re.sub(r"[^A-Za-z0-9]+", " ", value).lower()
    return " ".join(value.split())


def strip_prefix(text: str, prefix: str) -> str:
    t = norm(text)
    p = norm(prefix)
    if p and t == p:
        return ""
    if p and t.startswith(p + " "):
        words = text.strip().split()
        pwords = prefix.strip().split()
        if len(words) > len(pwords):
            return " ".join(words[len(pwords) :]).strip(" -–—:/")
    return text.strip()


def model_keys(brand: dict[str, Any], model: dict[str, Any]) -> set[str]:
    values = {
        model.get("name_en", ""),
        model.get("id", "").replace("_", " "),
        model.get("nameplate", ""),
        *model.get("aliases", []),
    }
    brand_values = {
        brand.get("name_en", ""),
        brand.get("id", "").replace("_", " "),
        *brand.get("aliases", []),
    }
    out: set[str] = set()
    for value in values:
        n = norm(value)
        if not n:
            continue
        out.add(n)
        for b in brand_values:
            bn = norm(b)
            if bn and n.startswith(bn + " "):
                out.add(n[len(bn) + 1 :])
    return out


def infer_powertrains(text: str) -> set[str]:
    """Return only powertrains explicitly supported by the text.

    MHEV is ICE in the canonical taxonomy. Plug-in/REEV markers suppress the
    generic Hybrid/EV substrings they contain. This parser is deliberately
    conservative because an unresolved trim is safer than a wrong identity.
    """
    raw = text or ""
    n = norm(raw)
    out: set[str] = set()

    if re.search(r"\b(fcev|fuel cell|hydrogen)\b", n):
        out.add("FCEV")
    if re.search(r"\b(reev|erev)\b", n) or "range extender" in n:
        out.add("REEV")
    if (
        re.search(r"\bphev\b", n)
        or "plug in hybrid" in n
        or re.search(r"\btfsi e\b", n)
        or re.search(r"\bxdrive\d+e\b", n)
        or re.search(r"\b\d{2,3}e\b", n)
        or re.search(r"\bdm i\b", n)
        or re.search(r"\bcsh\b", n)
    ):
        out.add("PHEV")
    if re.search(r"\bbev\b", n) or re.search(r"\belectric\b", n):
        out.add("BEV")

    # Standalone EV is useful, but do not let EREV/PHEV text manufacture BEV.
    if not ({"PHEV", "REEV"} & out) and re.search(r"\bev\b", n):
        out.add("BEV")

    if "mhev" in n or "mild hybrid" in n:
        out.add("ICE")
    elif not ({"PHEV", "REEV"} & out) and (
        re.search(r"\bhev\b", n)
        or "e hev" in n
        or "e power" in n
        or re.search(r"\bhybrid\b", n)
    ):
        out.add("HEV")

    if re.search(r"\b(diesel|petrol|gasoline|tdi|tsi|tfsi|ecoboost|turbo diesel)\b", n):
        out.add("ICE")

    if not (out & {"HEV", "PHEV", "REEV", "BEV", "FCEV"}) and re.search(
        r"\b\d(?:\.\d+)?\s*l\b", raw.lower()
    ):
        out.add("ICE")

    return out & POWERTRAINS


def select_generation(model: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    generations = model.get("generations", [])
    if len(generations) == 1:
        return generations[0], None
    active = [g for g in generations if not g.get("ended")]
    if len(active) == 1:
        return active[0], None
    return None, "AMBIGUOUS_GENERATION"


def canonical_trim_name(raw_trim: str, source_nameplate: str, model_name: str) -> tuple[str, list[str]]:
    candidate = strip_prefix(raw_trim, source_nameplate)
    if candidate == raw_trim:
        candidate = strip_prefix(raw_trim, model_name)
    candidate = candidate.strip()
    if not candidate or len(norm(candidate)) < 2:
        candidate = raw_trim.strip()
    aliases = [] if norm(candidate) == norm(raw_trim) else [raw_trim.strip()]
    return candidate, aliases


def classify_model_match(
    source: dict[str, Any],
    canonical: list[dict[str, Any]],
    key_index: dict[str, list[int]],
    aligned_idx: int | None,
) -> tuple[int | None, str, float]:
    source_key = norm(source.get("nameplate", ""))
    direct = key_index.get(source_key, [])
    if len(direct) == 1:
        return direct[0], "EXACT_NAME", 1.0

    suffix_candidates: set[int] = set()
    for key, indexes in key_index.items():
        if key and (source_key.endswith(" " + key) or key.endswith(" " + source_key)):
            if min(len(key), len(source_key)) >= 4:
                suffix_candidates.update(indexes)
    if len(suffix_candidates) == 1:
        idx = next(iter(suffix_candidates))
        return idx, "UNIQUE_SUFFIX", 0.95

    # Order is only a fallback. It is accepted only with strong name similarity,
    # so one missing/extra source row cannot shift every subsequent attachment.
    if aligned_idx is not None and 0 <= aligned_idx < len(canonical):
        item = canonical[aligned_idx]
        best = max(
            (SequenceMatcher(None, source_key, key).ratio() for key in item["keys"] if key),
            default=0.0,
        )
        if best >= 0.78:
            return aligned_idx, "INDEX_PLUS_NAME", round(best, 4)

    return None, "UNMATCHED_MODEL", 0.0


def resolve_trim_powertrain(
    raw_trim: str,
    source_powertrain_text: str,
    generation: dict[str, Any],
) -> tuple[str | None, str | None]:
    allowed = {
        str(v.get("powertrain", "")).upper()
        for v in generation.get("variants", [])
        if str(v.get("powertrain", "")).upper() in POWERTRAINS
    }
    trim_pts = infer_powertrains(raw_trim)
    source_pts = infer_powertrains(source_powertrain_text)

    # Per-trim evidence wins. More than one explicit powertrain in the same trim
    # string is not collapsed by the canonical variant set.
    if len(trim_pts) == 1:
        pt = next(iter(trim_pts))
        if allowed and pt not in allowed:
            return None, "POWERTRAIN_CONFLICT"
        return pt, None
    if len(trim_pts) > 1:
        return None, "AMBIGUOUS_POWERTRAIN"

    # A source row describing a single powertrain is safe for all its trims.
    if len(source_pts) == 1:
        pt = next(iter(source_pts))
        if allowed and pt not in allowed:
            return None, "POWERTRAIN_CONFLICT"
        return pt, None

    # Mixed source rows stay mixed unless the trim itself disambiguates them.
    if len(source_pts) > 1:
        return None, "AMBIGUOUS_POWERTRAIN"

    # If the directory omitted powertrain wording entirely, one exact canonical
    # analytical powertrain can supply the identity without guessing.
    if len(allowed) == 1:
        return next(iter(allowed)), None
    return None, "AMBIGUOUS_POWERTRAIN"


def is_non_market_trim(raw_trim: str) -> bool:
    n = norm(raw_trim)
    blocked = (
        "concept",
        "future production",
        "prototype",
        "pre production",
        "coming soon",
    )
    return any(token in n for token in blocked)


def main() -> int:
    source_records: list[dict[str, Any]] = []
    for path in sorted(SOURCE_DIR.glob("records_*.json")):
        source_records.extend(json.loads(path.read_text(encoding="utf-8"))["records"])
    source_records.sort(key=lambda row: int(row["source_index"]))

    files: list[tuple[Path, dict[str, Any]]] = []
    canonical: list[dict[str, Any]] = []
    for path in sorted(MODELS_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        files.append((path, payload))
        brand = payload["brand"]
        for model in payload.get("models", []):
            model_id = f"{brand.get('id', path.stem)}.{model.get('id', model.get('name_en', ''))}"
            canonical.append(
                {
                    "file": path,
                    "payload": payload,
                    "brand": brand,
                    "model": model,
                    "model_id": model_id,
                    "keys": model_keys(brand, model),
                }
            )
    canonical.sort(key=lambda row: row["model_id"])

    key_index: dict[str, list[int]] = {}
    for i, item in enumerate(canonical):
        for key in item["keys"]:
            key_index.setdefault(key, []).append(i)

    changed_paths: set[Path] = set()
    report: dict[str, Any] = {
        "source": "owner_directory_2026_09_13",
        "source_record_count": len(source_records),
        "canonical_model_count": len(canonical),
        "matched_models": 0,
        "changed_models": 0,
        "changed_files": 0,
        "trims_added": 0,
        "existing_trim_refs_added": 0,
        "existing_trim_matches_unchanged": 0,
        "skipped_trims": 0,
        "unmatched_models": [],
        "skipped_models": [],
        "skipped_trim_rows": [],
        "model_matches": [],
    }

    changed_model_ids: set[str] = set()

    for pos, source in enumerate(source_records):
        aligned_idx = pos if len(source_records) == len(canonical) else None
        idx, method, confidence = classify_model_match(source, canonical, key_index, aligned_idx)
        if idx is None:
            report["unmatched_models"].append(
                {
                    "source_index": source["source_index"],
                    "nameplate": source["nameplate"],
                    "brand_make": source.get("brand_make", ""),
                    "reason": method,
                }
            )
            continue

        item = canonical[idx]
        model = item["model"]
        report["matched_models"] += 1
        report["model_matches"].append(
            {
                "source_index": source["source_index"],
                "source_nameplate": source["nameplate"],
                "canonical_model_id": item["model_id"],
                "canonical_name": model.get("name_en", ""),
                "method": method,
                "confidence": confidence,
            }
        )

        generation, generation_error = select_generation(model)
        if generation is None:
            report["skipped_models"].append(
                {
                    "source_index": source["source_index"],
                    "nameplate": source["nameplate"],
                    "canonical_model_id": item["model_id"],
                    "reason": generation_error,
                }
            )
            continue

        trims = generation.setdefault("trims", [])
        existing_names: dict[str, dict[str, Any]] = {}
        for trim in trims:
            for value in [trim.get("name", ""), *trim.get("aliases", [])]:
                n = norm(value)
                if n:
                    existing_names[n] = trim

        for raw_trim in source.get("submodels_trims", []):
            if is_non_market_trim(raw_trim):
                report["skipped_trims"] += 1
                report["skipped_trim_rows"].append(
                    {
                        "source_index": source["source_index"],
                        "canonical_model_id": item["model_id"],
                        "trim": raw_trim,
                        "reason": "NON_MARKET_FUTURE_OR_CONCEPT",
                    }
                )
                continue

            powertrain, pt_error = resolve_trim_powertrain(
                raw_trim,
                source.get("segment_powertrain", ""),
                generation,
            )
            if powertrain is None:
                report["skipped_trims"] += 1
                report["skipped_trim_rows"].append(
                    {
                        "source_index": source["source_index"],
                        "canonical_model_id": item["model_id"],
                        "trim": raw_trim,
                        "reason": pt_error,
                        "source_powertrain_text": source.get("segment_powertrain", ""),
                    }
                )
                continue

            name, aliases = canonical_trim_name(
                raw_trim,
                source["nameplate"],
                model.get("name_en", ""),
            )
            match = existing_names.get(norm(name)) or existing_names.get(norm(raw_trim))
            source_ref = source["source_ref"]
            if match is not None:
                existing_pt = str(match.get("powertrain", "")).upper()
                if existing_pt and existing_pt != powertrain:
                    report["skipped_trims"] += 1
                    report["skipped_trim_rows"].append(
                        {
                            "source_index": source["source_index"],
                            "canonical_model_id": item["model_id"],
                            "trim": raw_trim,
                            "reason": "EXISTING_TRIM_POWERTRAIN_CONFLICT",
                            "existing_powertrain": existing_pt,
                            "resolved_powertrain": powertrain,
                        }
                    )
                    continue
                refs = match.setdefault("source_refs", {})
                bucket = refs.setdefault("owner_directory", [])
                if source_ref not in bucket:
                    bucket.append(source_ref)
                    changed_paths.add(item["file"])
                    changed_model_ids.add(item["model_id"])
                    report["existing_trim_refs_added"] += 1
                else:
                    report["existing_trim_matches_unchanged"] += 1
                continue

            new_trim: dict[str, Any] = {
                "name": name,
                "powertrain": powertrain,
                "source_refs": {"owner_directory": [source_ref]},
            }
            if aliases:
                new_trim["aliases"] = aliases
            trims.append(new_trim)
            existing_names[norm(name)] = new_trim
            existing_names[norm(raw_trim)] = new_trim
            changed_paths.add(item["file"])
            changed_model_ids.add(item["model_id"])
            report["trims_added"] += 1

    report["changed_models"] = len(changed_model_ids)
    report["changed_files"] = len(changed_paths)

    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )

    for path, payload in files:
        if path in changed_paths:
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

    print(json.dumps({k: report[k] for k in (
        "source_record_count",
        "canonical_model_count",
        "matched_models",
        "changed_models",
        "changed_files",
        "trims_added",
        "existing_trim_refs_added",
        "existing_trim_matches_unchanged",
        "skipped_trims",
    )}, indent=2))
    print(f"unmatched_models={len(report['unmatched_models'])}")
    print(f"skipped_models={len(report['skipped_models'])}")
    print(f"report={REPORT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
