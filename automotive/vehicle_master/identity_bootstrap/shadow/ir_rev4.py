"""PR #200 rev 4 relation data, consumed (never re-derived) by the shadow stand-in.

Identity Resolution owns the lexical-relation rules. Its pinned commit published, for the same M7.0 package, every name pair whose relation is FUZZY, SIBLING or
EQUAL_VIA_MODEL_ALIAS under the corrected rules (`calibration/lexical_pass/after_rev4.json`). This module vendors the parts of that export the shadow needs,
together with the commit and the sha256 of each source blob, and exposes them read-only. Nothing here implements, approximates or forks an IR lexical rule."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).parent
VENDORED = HERE / "universe" / "ir_rev4" / "relations.json"
PR200_COMMIT = "1f73aee1834697cbd439291d0074293c30446e5b"
SOURCE_DIR = "automotive/vehicle_master/identity_resolution/calibration/lexical_pass"
SOURCES = ("after_rev4.json", "before_rev3.json", "comparison.json")
#: Relations the correction can change. Everything else (EQUAL, EQUAL_VIA_TOKEN_EQUIV, SUBJECT_COARSER/FINER) is outside the export by construction.
EXPORTED_RELATIONS = ("FUZZY", "SIBLING", "EQUAL_VIA_MODEL_ALIAS")


def pairs_digest(data: dict) -> str:
    """sha256 over the canonical JSON of the vendored pair maps and relation counts, so the committed data can be checked without the PR #200 git objects."""
    body = {k: data[k] for k in ("ice_ice_relation_pairs", "ice_tdr_relation_pairs", "relation_counts")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def _git_show(repo: Path, commit: str, path: str) -> bytes:
    return subprocess.run(["git", "-C", str(repo), "show", f"{commit}:{path}"], check=True, capture_output=True).stdout


def vendor(repo: Path, commit: str = PR200_COMMIT, out: Path = VENDORED) -> dict:
    """Read the export from an object in the repository (no checkout, no working-tree access to PR #200) and write the vendored subset."""
    blobs = {n: _git_show(repo, commit, f"{SOURCE_DIR}/{n}") for n in SOURCES}
    after, comp = json.loads(blobs["after_rev4.json"]), json.loads(blobs["comparison.json"])
    data = {
        "provenance": {"pr": 200, "commit": commit, "source_dir": SOURCE_DIR, "label": after["label"], "policy": after["policy"],
                       "sources_sha256": {n: hashlib.sha256(b).hexdigest() for n, b in blobs.items()}},
        "ice_ice_relation_pairs": after["ice_ice_relation_pairs"], "ice_tdr_relation_pairs": after["ice_tdr_relation_pairs"],
        "relation_counts": {"ice_ice": after["ice_ice"]["relations"], "ice_tdr": after["ice_tdr"]["relations"],
                            "before_ice_ice": json.loads(blobs["before_rev3.json"])["ice_ice"]["relations"], "before_ice_tdr": json.loads(blobs["before_rev3.json"])["ice_tdr"]["relations"]},
        "batch_conflict_groups_after": after["batch_conflicts_ice_ice"]["groups"], "batch_conflict_summary_after": {k: after["batch_conflicts_ice_ice"][k] for k in ("all_groups", "settled_groups", "by_class")},
        "engine_outcomes": {g: v[0] for g, v in after["decisions"].items()},
        "engine_outcomes_summary": after["decision_summary"]["outcomes"],
        "released_no_candidate": {k: comp["create_eligible_released"][k] for k in ("count", "units", "by_cause", "groups")},
        "named_in_pr201": comp["named_in_pr201"], "changed_decisions": comp["changed_decisions"],
    }
    data["provenance"]["pairs_and_counts_sha256"] = pairs_digest(data)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return data


def load(path: Path = VENDORED) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def adjudicate(base: str, pair_relation: str | None) -> str:
    """Combine the stand-in's pair relation `base` with IR rev 4's verdict `pair_relation` (None = the pair is not in the export).

    The stand-in supplies only the pair POPULATION and the relations rev 4 did not touch (EQUAL, EQUAL_VIA_TOKEN_EQUIV, SUBJECT_COARSER/FINER). Its population is a superset
    of IR's (a 4-char FUZZY floor, any-shared-token SIBLING), so: a pair IR lists takes IR's relation, always (IR is the authority); a pair the stand-in called FUZZY or SIBLING
    that IR does not list is a CONTRADICTION under the corrected rules; everything else keeps the stand-in's relation."""
    if pair_relation is not None:
        return pair_relation
    if base in ("FUZZY", "SIBLING"):
        return "CONTRADICTION"
    return base
