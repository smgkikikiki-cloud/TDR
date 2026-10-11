"""Reference arithmetic for Identity Resolution contract v1 — NOT the resolver.

This module implements only the parts of the SPEC that are pure arithmetic with a single correct answer:
period maths, the common-window/series statistics of SPEC §6 (including the missing-row semantics gap of §6.2a),
adapter densification under a capability declaration (§3.2), the claim-conflict rules of §7.0, quantization and
banding, the canonical-JSON fingerprints and link-set ids of §11, and the write-matrix lookup of SPEC §10. It exists so the golden corpus can be
checked against the written rules *before* an engine exists, and so the future engine can be differentially
tested against an independent implementation. It deliberately has no brand/name logic and no decision
logic: those are specified by the corpus itself and arrive with the engine.
"""
from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Any

# ----------------------------------------------------------------------------------------------- periods


def pidx(period: str) -> int:
    year, month = period.split("-")
    return int(year) * 12 + int(month) - 1


def pstr(index: int) -> str:
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


# ----------------------------------------------------------------------------------------------- quantize


def quantize(value: float | None, places: int = 6) -> float | None:
    """Round half-even on the shortest-repr decimal expansion (SPEC §6.7 / §11.1). `places` is policy.quantization.places."""
    if value is None:
        return None
    return float(Decimal(repr(float(value))).quantize(Decimal(1).scaleb(-places), ROUND_HALF_EVEN))


def quantize_str(value: float, places: int = 6) -> str:
    return format(Decimal(repr(float(value))).quantize(Decimal(1).scaleb(-places), ROUND_HALF_EVEN), "f")


def band(dimension: str, value: float, policy: dict) -> str:
    """Lower-inclusive bands over the edges in policy.fingerprint.bands (SPEC §11.2)."""
    edges = policy["fingerprint"]["bands"][dimension]
    v = value if dimension == "common_months" else quantize(value, policy["quantization"]["places"])
    labels = [f"<{edges[0]}"] + [f"[{a},{b})" for a, b in zip(edges, edges[1:])] + [f">={edges[-1]}"]
    return labels[sum(1 for edge in edges if v >= edge)]


# ----------------------------------------------------------------------------------------------- attributes


def body_relation(provider_body: str | None, tdr_body_type: str | None, policy: dict) -> str:
    """SPEC §6.9.1: MISMATCH only when both sides are known and incompatible."""
    body = policy["attributes"]["body"]
    if not provider_body or not tdr_body_type or tdr_body_type == "OTHER":
        return "UNKNOWN"
    allowed = body["compatibility"].get(provider_body)
    if allowed is None:
        return "UNKNOWN"
    return "MATCH" if tdr_body_type in allowed else "MISMATCH"


def lifecycle_relation(subject: dict | None, generations: list[dict], as_of: str, policy: dict) -> tuple[str, float | None]:
    """SPEC §6.9.2: the share of the subject's units that fall inside the target's lifetime (+/- grace)."""
    if not generations or subject is None:
        return "UNKNOWN", None
    cfg = policy["attributes"]["lifecycle"]
    grace = cfg["grace_months"]
    intervals = []
    for generation in generations:
        low = pidx(generation["launched"]) - grace if generation.get("launched") else None
        high = pidx(generation["ended"]) + grace if generation.get("ended") else None
        intervals.append((low, high))
    start = pidx(subject["start"])
    total = inside = 0.0
    for offset, count in enumerate(subject["counts"]):
        if count is None:
            continue
        total += count
        month = start + offset
        if any((low is None or month >= low) and (high is None or month <= high) for low, high in intervals):
            inside += count
    if total == 0:
        return "UNKNOWN", None
    share = quantize(inside / total, policy["quantization"]["places"])
    if share >= cfg["within_min_share"]:
        return "WITHIN", share
    if share < cfg["disjoint_max_share"]:
        return "DISJOINT", share
    return "PARTIAL", share


# ----------------------------------------------------------------------------------------------- series


def series_gate(stats: dict, policy: dict) -> tuple[str, list[str]]:
    """SPEC §6.7: classify an already-computed statistics tuple. Returns (state, codes)."""
    series = policy["series"]
    propose, auto, strong = series["minimums"]["propose"], series["minimums"]["auto"], series["strong"]
    months, joint = stats["common_months"], stats["joint_nonzero_months"]
    subject_units, target_units = stats["subject_units"], stats["target_units"]
    if months < propose["common_months"] or joint < propose["joint_nonzero_months"]:
        return "UNAVAILABLE", ["SER_OVERLAP_BELOW_PROPOSE_MIN"]
    if min(subject_units, target_units) < propose["units_each_side"]:
        return "UNAVAILABLE", ["SER_VOLUME_BELOW_PROPOSE_MIN"]
    codes: list[str] = []
    places = policy["quantization"]["places"]
    corr, ratio, fit = quantize(stats["correlation"], places), quantize(stats["ratio"], places), quantize(stats["monthly_fit_share"], places)
    corr_ok = corr >= strong["correlation_min"]
    ratio_ok = strong["ratio_min"] <= ratio <= strong["ratio_max"]
    fit_ok = fit >= series["monthly_fit"]["min_share_of_months"]
    if not corr_ok:
        codes.append("SER_CORRELATION_BELOW_STRONG")
    if not ratio_ok:
        codes.append("SER_RATIO_OUT_OF_BAND")
    if corr_ok and ratio_ok and not fit_ok:
        codes.append("SER_MONTHLY_FIT_FAIL")
    state = "STRONG" if (corr_ok and ratio_ok and fit_ok) else "WEAK"
    if state == "STRONG":
        codes.append("SER_STRONG")
    if months < auto["common_months"] or joint < auto["joint_nonzero_months"]:
        codes.append("SER_OVERLAP_BELOW_AUTO_MIN")
    if min(subject_units, target_units) < auto["units_each_side"]:
        codes.append("SER_VOLUME_BELOW_AUTO_MIN")
    return state, codes


def sum_series(parts: list[dict | None]) -> dict | None:
    """SPEC §6.8: the series of a bundle — the sum over months every member observes (a null in any member makes the month unobserved)."""
    if any(part is None for part in parts):
        return None
    if not all(part.get("coverage_declared", True) for part in parts):
        return {"start": parts[0]["start"], "counts": [None], "coverage_declared": False}
    low = max(pidx(part["start"]) for part in parts)
    high = min(pidx(part["start"]) + len(part["counts"]) - 1 for part in parts)
    if high < low:
        return None
    counts = []
    for index in range(low, high + 1):
        values = [part["counts"][index - pidx(part["start"])] for part in parts]
        counts.append(None if any(v is None for v in values) else sum(values))
    partial = sorted({p for part in parts for p in part.get("partial_periods", [])})
    summed = {"start": pstr(low), "counts": counts, "partial_periods": partial, "coverage_declared": True}
    blocks = [part["absent_rows"] for part in parts if part.get("absent_rows")]
    if blocks:
        summed["absent_rows"] = {"source": blocks[0]["source"], "semantics": blocks[0]["semantics"],
                                 "confirmed": all(block["confirmed"] for block in blocks),
                                 "months": sorted({m for block in blocks for m in block["months"]})}
    return summed


def load_capabilities() -> dict:
    """provider_capabilities.yaml as {source: {"value", "status"}} (only what the engine needs)."""
    from identity_resolution.contract import loader
    return {name: {"value": spec["series.absent_row"]["value"], "status": spec["series.absent_row"]["status"]}
            for name, spec in loader.load_capabilities()["sources"].items()}


def absent_row_refusal(series: dict | None, capabilities: dict) -> str | None:
    """SPEC §3.2: a series may not claim more than the contract grants, and may not zero-fill an unconfirmed gap."""
    block = (series or {}).get("absent_rows")
    if not block:
        return None
    declared = capabilities.get(block["source"])
    if declared is None or declared["value"] != block["semantics"] or (declared["status"] == "confirmed") != block["confirmed"]:
        return "INPUT_CAPABILITY_MISMATCH"
    zero_ok = block["semantics"] == "ABSENT_IS_ZERO" and block["confirmed"]
    start = pidx(series["start"])
    for month in block["months"]:
        offset = pidx(month) - start
        if 0 <= offset < len(series["counts"]) and series["counts"][offset] is not None and not zero_ok:
            return "INPUT_ABSENT_ROW_ZERO_UNCONFIRMED"
    return None


def unconfirmed_absent_months(series: dict | None) -> set[int]:
    """Month indexes that are absent rows of a series whose missing-row meaning is unconfirmed (their value is null)."""
    block = (series or {}).get("absent_rows")
    if not block or block["confirmed"]:
        return set()
    return {pidx(m) for m in block["months"]}


def compare_series(subject: dict | None, target: dict | None, policy: dict, max_months: int | None = None,
                   capabilities: dict | None = None) -> dict:
    """SPEC §6: the common observation window and the statistics computed over it.

    Returns a dict with: common_window ({from,to,months}|None), periods, excluded ([{period,reason}]),
    codes (reason codes raised by the window stage and the gate), state, stats (dict) and refusal (code|None).
    The engine NEVER zero-fills: a null count is unobserved and leaves the comparison."""
    series = policy["series"]
    max_months = max_months or series["window"]["max_months"]
    result: dict[str, Any] = {"common_window": None, "periods": [], "excluded": [], "codes": [], "state": "UNAVAILABLE",
                              "stats": None, "refusal": None, "semantics_gap_months": 0}
    low, high = policy["time"]["valid_year_range"]
    for item in (subject, target):
        if item is None:
            continue
        end = pidx(item["start"]) + len(item["counts"]) - 1
        if not (low <= int(item["start"][:4]) <= high and low <= int(pstr(end)[:4]) <= high):
            result["refusal"] = "INPUT_PERIOD_CALENDAR_INVALID"
            return result
        if any(c is not None and c < 0 for c in item["counts"]):
            result["refusal"] = "INPUT_NEGATIVE_COUNT"
            return result
    caps = capabilities if capabilities is not None else load_capabilities()
    for item in (subject, target):
        refusal = absent_row_refusal(item, caps)
        if refusal:
            result["refusal"] = refusal
            return result
    if subject is None or target is None:
        result["codes"].append("SER_NO_COMMON_WINDOW")
        return result
    if not subject.get("coverage_declared", True) or not target.get("coverage_declared", True):
        result["codes"].append("SER_COVERAGE_UNDECLARED")
        return result

    s0, t0 = pidx(subject["start"]), pidx(target["start"])
    s1, t1 = s0 + len(subject["counts"]) - 1, t0 + len(target["counts"]) - 1
    if (s0, s1) != (t0, t1):
        result["codes"].append("SER_COVERAGE_ASYMMETRIC")
    partial = ({pidx(p) for p in subject.get("partial_periods", [])} | {pidx(p) for p in target.get("partial_periods", [])}
               if series["window"]["exclude_partial_periods"] else set())
    observed_s = {s0 + i: c for i, c in enumerate(subject["counts"]) if c is not None}
    observed_t = {t0 + i: c for i, c in enumerate(target["counts"]) if c is not None}
    both_covered = set(range(max(s0, t0), min(s1, t1) + 1))
    unconfirmed_s, unconfirmed_t = unconfirmed_absent_months(subject), unconfirmed_absent_months(target)
    excluded: list[tuple[int, str]] = []
    saw_unobserved = False
    for i in sorted(set(range(s0, s1 + 1)) | set(range(t0, t1 + 1))):
        if i in partial and (i in observed_s or i in observed_t):
            excluded.append((i, "partial_period"))
        elif i not in both_covered:
            excluded.append((i, "outside_common_coverage"))
        elif i not in observed_s:
            excluded.append((i, "unconfirmed_absent_row_in_subject" if i in unconfirmed_s else "unobserved_in_subject"))
            saw_unobserved = True
        elif i not in observed_t:
            excluded.append((i, "unconfirmed_absent_row_in_target" if i in unconfirmed_t else "unobserved_in_target"))
            saw_unobserved = True
    if any(reason == "partial_period" for _, reason in excluded):
        result["codes"].append("SER_PARTIAL_PERIOD_EXCLUDED")
    if saw_unobserved:
        result["codes"].append("SER_UNOBSERVED_NOT_ZERO")
    # SPEC §6.2a: months lost ONLY because a missing-row meaning is unconfirmed, in the last max_months of the coverage intersection.
    if both_covered:
        window_end = max(both_covered)
        gap = sum(1 for i in both_covered
                  if i > window_end - max_months and i not in partial and (i in unconfirmed_s or i in unconfirmed_t))
        result["semantics_gap_months"] = gap
        if gap > 0:
            result["codes"].append("SER_MISSING_ROW_SEMANTICS_UNCONFIRMED")

    common = sorted(i for i in both_covered if i in observed_s and i in observed_t and i not in partial)
    if not common:
        result["excluded"] = [{"period": pstr(i), "reason": r} for i, r in excluded]
        result["codes"].append("SER_NO_COMMON_WINDOW")
        return result

    lo, hi = 0, len(common)
    if series["window"]["trim_inactive_edges"]:
        while lo < hi and observed_s[common[lo]] == 0 and observed_t[common[lo]] == 0:
            excluded.append((common[lo], "leading_inactive"))
            lo += 1
        while hi > lo and observed_s[common[hi - 1]] == 0 and observed_t[common[hi - 1]] == 0:
            excluded.append((common[hi - 1], "trailing_inactive"))
            hi -= 1
        if lo > 0 or hi < len(common):
            result["codes"].append("SER_WINDOW_TRIMMED_INACTIVE")
    trimmed = common[lo:hi]
    if not trimmed:
        result["excluded"] = [{"period": pstr(i), "reason": r} for i, r in sorted(excluded)]
        result["codes"].append("SER_ZERO_TOTAL")
        return result

    anchor = trimmed[-1]
    kept = [i for i in trimmed if i > anchor - max_months]
    excluded.extend((i, "outside_max_window") for i in trimmed if i not in kept)
    result["periods"] = [pstr(i) for i in kept]
    result["excluded"] = [{"period": pstr(i), "reason": r} for i, r in sorted(excluded)]
    result["common_window"] = {"from": pstr(kept[0]), "to": pstr(kept[-1]), "months": len(kept)}

    xs = [float(observed_s[i]) for i in kept]
    ys = [float(observed_t[i]) for i in kept]
    n = len(kept)
    stats: dict[str, Any] = {
        "common_months": n,
        "joint_nonzero_months": sum(1 for x, y in zip(xs, ys) if x > 0 and y > 0),
        "subject_units": sum(xs), "target_units": sum(ys),
        "correlation": None, "ratio": None, "monthly_fit_share": None, "semantics_gap_months": result["semantics_gap_months"],
    }
    result["stats"] = stats
    if stats["subject_units"] == 0:
        result["codes"].append("SER_ZERO_TOTAL")
        return result
    minimum = series["minimums"]["propose"]
    if n < minimum["common_months"] or stats["joint_nonzero_months"] < minimum["joint_nonzero_months"]:
        result["codes"].append("SER_OVERLAP_BELOW_PROPOSE_MIN")
        return result
    if min(stats["subject_units"], stats["target_units"]) < minimum["units_each_side"]:
        result["codes"].append("SER_VOLUME_BELOW_PROPOSE_MIN")
        return result
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x <= 0 or var_y <= 0:
        result["codes"].append("SER_ZERO_VARIANCE")
        return result
    fit = series["monthly_fit"]
    places = policy["quantization"]["places"]
    stats["correlation"] = quantize(sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / math.sqrt(var_x * var_y), places)
    stats["ratio"] = quantize(sum(ys) / sum(xs), places)
    stats["monthly_fit_share"] = quantize(
        sum(1 for x, y in zip(xs, ys) if abs(y - x) <= max(fit["abs_tolerance_units"], fit["rel_tolerance"] * x)) / n, places)
    state, codes = series_gate(stats, policy)
    result["state"] = state
    result["codes"].extend(codes)
    return result


# ----------------------------------------------------------------------------------------------- fingerprints


def canonical_json(payload: Any) -> bytes:
    """SPEC §11.1: UTF-8, sorted keys, no whitespace, no floats anywhere in the payload."""
    def reject_floats(node: Any) -> None:
        if isinstance(node, float):
            raise ValueError("float_in_payload")
        if isinstance(node, dict):
            for value in node.values():
                reject_floats(value)
        elif isinstance(node, list):
            for value in node:
                reject_floats(value)
    reject_floats(payload)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def fingerprint(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def densify(rows: list[dict], coverage: dict, capability: dict) -> dict:
    """SPEC §3.2 / A2: sparse source rows -> a dense series under a capability declaration {"value", "status"}.
    An absent month inside coverage is 0 only for ABSENT_IS_ZERO + confirmed; otherwise null. Months outside coverage are never produced."""
    low, high = pidx(coverage["from"]), pidx(coverage["to"])
    by_month = {pidx(r["period"]): r["count"] for r in rows}
    if any(not (low <= m <= high) for m in by_month):
        raise ValueError("a source row lies outside the declared coverage")
    zero_ok = capability["value"] == "ABSENT_IS_ZERO" and capability["status"] == "confirmed"
    counts, absent = [], []
    for m in range(low, high + 1):
        if m in by_month:
            counts.append(by_month[m])
        else:
            absent.append(pstr(m))
            counts.append(0 if zero_ok else None)
    return {"start": coverage["from"], "counts": counts, "absent_months": absent, "semantics": capability["value"],
            "confirmed": capability["status"] == "confirmed"}


def claim_conflict(a: dict, b: dict) -> tuple[bool, str | None]:
    """SPEC §7.0 for two ACTIVE claims: C1 one claim per subject; C2 a whole is claimed once unless both are PART_OF."""
    same = a["subject_id"] == b["subject_id"] and a["link_type"] == b["link_type"] and sorted(a["target_ids"]) == sorted(b["target_ids"])
    if same:
        return False, None
    if a["subject_id"] == b["subject_id"]:
        return True, "C1"
    if set(a["target_ids"]) & set(b["target_ids"]) and not (a["link_type"] == "PART_OF" and b["link_type"] == "PART_OF"):
        return True, "C2"
    return False, None


def link_set_payload(provider: str, subject: str, targets: list[str]) -> dict:
    return {"v": "link-set/1", "contract": "v1", "provider": provider, "subject": subject, "targets": sorted(targets)}


def link_set_id(provider: str, subject: str, targets: list[str]) -> str:
    """SPEC §10.5 / §11.2a."""
    return "ls1-" + fingerprint(link_set_payload(provider, subject, targets))[:24]


def write_action(existing_state: str, decision: str, fingerprint_flag: str, policy: dict) -> str:
    """SPEC §10.2: the write matrix lookup."""
    cell = policy["state"]["write_matrix"][existing_state][decision]
    if isinstance(cell, dict):
        return cell["fingerprint_unchanged" if fingerprint_flag == "unchanged" else "fingerprint_changed"]
    return cell
