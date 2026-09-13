#!/usr/bin/env python3
"""Source-first refinement for applying the owner-provided trim directory.

This wrapper keeps the structural/model matching from apply_owner_trim_directory
but tightens two identity details before writing canonical MarketTrim rows:
- '+' is significant in trim identity (for example D vs D+ and MAX vs MAX+);
- mixed-powertrain source rows are only resolved when the individual trim or the
  source text actually identifies one exact canonical powertrain.

Ambiguous rows stay unmodified and are reported by the base applier.
"""

from __future__ import annotations

import re
import unicodedata

import apply_owner_trim_directory as base

PTS = {"ICE", "HEV", "PHEV", "REEV", "BEV", "FCEV"}


def norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = value.replace("&", " and ").replace("+", " plus ")
    value = re.sub(r"[^A-Za-z0-9]+", " ", value).lower()
    return " ".join(value.split())


def infer_source(text: str) -> set[str]:
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
        or re.search(r"\be hybrid\b", n)
        or re.search(r"\bdm i\b", n)
        or re.search(r"\bcsh\b", n)
        or re.search(r"\btfsi e\b", n)
    ):
        out.add("PHEV")
    if (
        re.search(r"\bbev\b", n)
        or re.search(r"\bpure electric\b", n)
        or (re.search(r"\belectric\b", n) and "electrified" not in n)
    ):
        out.add("BEV")
    if (
        re.search(r"\bhev\b", n)
        or re.search(r"\be hev\b", n)
        or re.search(r"\be power\b", n)
    ):
        out.add("HEV")
    if re.search(r"\bhybrid\b", n) and not ({"PHEV", "REEV"} & out):
        out.add("HEV")
    if "mhev" in n or "mild hybrid" in n:
        out.add("ICE")

    clean = re.sub(r"\btfsi e\b", " ", n)
    if re.search(r"\b(diesel|petrol|gasoline|tdi|tsi|tfsi|ecoboost)\b", clean):
        out.add("ICE")

    # Source rows often describe alternatives with '/'. Resolve each fragment
    # independently so `2.5 Hybrid / 2.5 PHEV` remains {HEV, PHEV} rather than
    # letting the plug-in marker erase the HEV member.
    for fragment in re.split(r"\s*/\s*|;", raw):
        fn = norm(fragment)
        frag_plugin = bool(
            re.search(r"\b(phev|reev|erev)\b", fn)
            or "plug in" in fn
            or re.search(r"\be hybrid\b", fn)
            or re.search(r"\bdm i\b", fn)
            or re.search(r"\bcsh\b", fn)
        )
        if "mhev" in fn or "mild hybrid" in fn:
            out.add("ICE")
        elif re.search(r"\bhybrid\b", fn) and not frag_plugin:
            out.add("HEV")

        electrified = bool(
            re.search(
                r"\b(hev|phev|bev|reev|erev|fcev|hybrid|electric|e power|dm i|csh)\b",
                fn,
            )
            or "plug in" in fn
            or re.search(r"\be hybrid\b", fn)
        )
        if not electrified and re.search(r"\b\d(?:\.\d+)?\s*l\b", fragment.lower()):
            out.add("ICE")

    return out & PTS


def infer_trim(text: str, source_pts: set[str]) -> tuple[set[str], bool]:
    raw = text or ""
    n = norm(raw)
    out: set[str] = set()
    generic_hybrid = False

    if re.search(r"\b(fcev|fuel cell|hydrogen)\b", n):
        out.add("FCEV")
    if re.search(r"\b(reev|erev)\b", n) or "range extender" in n:
        out.add("REEV")
    if (
        re.search(r"\bphev\b", n)
        or "plug in hybrid" in n
        or re.search(r"\be hybrid\b", n)
        or re.search(r"\bdm i\b", n)
        or re.search(r"\bcsh\b", n)
        or re.search(r"\btfsi e\b", n)
        or re.search(r"\b\d{3}h plus\b", n)
    ):
        out.add("PHEV")
    if (
        re.search(r"\bbev\b", n)
        or re.search(r"\bpure electric\b", n)
        or re.search(r"\belectric\b", n)
    ):
        out.add("BEV")
    if not ({"PHEV", "REEV"} & out) and re.search(r"\bev\b", n):
        out.add("BEV")
    if (
        re.search(r"\bhev\b", n)
        or re.search(r"\be hev\b", n)
        or re.search(r"\be power\b", n)
        or re.search(r"\b\d{3}h\b", n)
    ):
        out.add("HEV")
    if re.search(r"\bhybrid\b", n) and not out:
        generic_hybrid = True

    if "mhev" in n or "mild hybrid" in n:
        out.add("ICE")
    clean = re.sub(r"\btfsi e\b", " ", n)
    if re.search(r"\b(diesel|petrol|gasoline|tdi|tsi|tfsi|ecoboost)\b", clean):
        out.add("ICE")
    if (
        re.search(r"\b(?:xdrive|sdrive)\d{2,3}[di]\b", n)
        or re.search(r"\b\d{3}(?:li|d|i)\b", n)
        or re.search(r"\bm\d{2,3}i\b", n)
    ):
        out.add("ICE")
    if (
        not out
        and not generic_hybrid
        and re.search(r"\b\d(?:\.\d+)?\s*l\b", raw.lower())
    ):
        out.add("ICE")

    # BMW-style 330e/530e is interpreted as plug-in only when the supplied
    # source row itself says PHEV and not BEV. This avoids false positives such
    # as Lexus RZ 450e.
    if (
        not out
        and re.search(r"\b\d{3}e\b", n)
        and "PHEV" in source_pts
        and "BEV" not in source_pts
    ):
        out.add("PHEV")

    return out & PTS, generic_hybrid


def resolve_trim_powertrain(raw_trim: str, source_text: str, generation: dict):
    allowed = {
        str(v.get("powertrain", "")).upper()
        for v in generation.get("variants", [])
        if str(v.get("powertrain", "")).upper() in PTS
    }
    source_pts = infer_source(source_text)
    trim_pts, generic_hybrid = infer_trim(raw_trim, source_pts)

    if len(trim_pts) == 1:
        pt = next(iter(trim_pts))
        if source_pts and pt not in source_pts:
            return None, "POWERTRAIN_SOURCE_CONFLICT"
        return pt, None
    if len(trim_pts) > 1:
        return None, "AMBIGUOUS_POWERTRAIN"

    if generic_hybrid:
        electrified = source_pts & {"HEV", "PHEV", "REEV"}
        if len(electrified) == 1:
            return next(iter(electrified)), None
        # MHEV is canonical ICE. If the source offers no traction-hybrid member,
        # a grade marketed simply as Hybrid can resolve to that ICE/MHEV member.
        if not electrified and source_pts == {"ICE"}:
            return "ICE", None
        return None, "AMBIGUOUS_POWERTRAIN"

    if len(source_pts) == 1:
        return next(iter(source_pts)), None
    if len(source_pts) > 1:
        return None, "AMBIGUOUS_POWERTRAIN"
    if len(allowed) == 1:
        return next(iter(allowed)), None
    return None, "AMBIGUOUS_POWERTRAIN"


base.norm = norm
base.resolve_trim_powertrain = resolve_trim_powertrain

if __name__ == "__main__":
    raise SystemExit(base.main())
