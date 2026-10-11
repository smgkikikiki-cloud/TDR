"""Generic, evidence-driven review signals. No brand, model or alias is named in code or policy."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

POLICY_FILE = Path(__file__).with_name("policy.yaml")
CROSS_BRAND = "POSSIBLE_EXISTING_IDENTITY_CROSS_BRAND"
R6_HINT = "LEGACY_R6_STRONG_PROPOSAL"


def load_policy(path: Path = POLICY_FILE) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _toks(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", text.casefold()) if t]


def _comp(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.casefold())


def _identity_tokens(catalog: dict) -> dict[str, list[tuple[str, set[str]]]]:
    out: dict[str, list[tuple[str, set[str]]]] = {}
    for i in catalog["identities"]:
        ts = set(_toks(i["name_en"]))
        for alias in catalog["aliases"].get(i["canonical_id"], []):
            ts |= set(_toks(alias))
        out.setdefault(i["brand_id"], []).append((i["canonical_id"], ts))
    return out


def provider_id_label_evidence(subjects: list[dict], catalog: dict, pol: dict) -> dict[str, list[dict]]:
    """For each settled subject: the leading token of the provider's own id, when it is not one of the Ice brand's spellings but IS a whole token of an existing identity
    under the resolved brand. (E.g. a provider that files a relabelled model under its parent marque.)"""
    idn = _identity_tokens(catalog)
    out: dict[str, list[dict]] = {}
    for s in subjects:
        b, bid = s["brand"], s["brand"].get("brand_id")
        if s["identity_status"] != "settled" or not bid:
            continue
        own = {_comp(x) for x in (*b.get("spellings", ()), bid, catalog["brands"][bid]["name_en"])} | {_comp(b.get("raw", ""))}
        own |= {t for x in (*b.get("spellings", ()), catalog["brands"][bid]["name_en"]) for t in _toks(x)}
        lead = (_toks(s["entity_id"]) or [""])[0]
        if len(lead) < pol["cross_brand"]["min_slug_token_length"] or lead in own:
            continue
        hits = sorted(cid for cid, ts in idn.get(bid, ()) if lead in ts)
        if hits:
            out[s["entity_id"]] = [{"kind": "PROVIDER_ID_LABEL_IN_EXISTING_IDENTITY", "label": lead, "ice_brand": b.get("raw"), "resolved_brand_id": bid, "existing_identities": hits}]
    return out


def sibling_mapped_evidence(subjects: list[dict]) -> dict[str, list[dict]]:
    """A subject whose Ice sibling (a relation IR kept) is itself a lexical duplicate of an existing TDR identity: the family is already in TDR."""
    by = {s["entity_id"]: s for s in subjects}
    dup = ("EQUAL", "EQUAL_VIA_MODEL_ALIAS", "EQUAL_VIA_TOKEN_EQUIV", "FUZZY")
    out: dict[str, list[dict]] = {}
    for g, s in by.items():
        for r in s["relations"]:
            if r["peer_kind"] != "SUBJECT" or r["name_relation"] not in ("SIBLING", "FUZZY", "EQUAL_VIA_MODEL_ALIAS", "EQUAL"):
                continue
            peer = by.get(r["peer_id"])
            for x in (peer["relations"] if peer else ()):
                if x["peer_kind"] == "TARGET" and x["name_relation"] in dup:
                    out.setdefault(g, []).append({"kind": "SIBLING_MAPPED_TO_EXISTING_IDENTITY", "sibling": r["peer_id"], "sibling_relation": r["name_relation"], "existing_identity": x["peer_id"], "relation": x["name_relation"]})
            # the stored direction is smaller id -> larger id; mirror it so both ends see the evidence
            if peer:
                for x in s["relations"]:
                    if x["peer_kind"] == "TARGET" and x["name_relation"] in dup:
                        out.setdefault(r["peer_id"], []).append({"kind": "SIBLING_MAPPED_TO_EXISTING_IDENTITY", "sibling": g, "sibling_relation": r["name_relation"], "existing_identity": x["peer_id"], "relation": x["name_relation"]})
    return out


def r6_hints(ids: list[str], r6: dict, pol: dict) -> dict[str, list[dict]]:
    floor = pol["advisory"]["legacy_r6_min_score"]
    return {g: [{"kind": R6_HINT, "target": t, "status": st, "method": m, "score": sc} for t, st, m, sc in r6.get(g, []) if sc >= floor] for g in ids if any(x[3] >= floor for x in r6.get(g, []))}


def review_flags(subjects: list[dict], catalog: dict, r6: dict, ids: list[str], pol: dict | None = None) -> dict[str, dict]:
    """gid -> {flags, mandatory_owner_review, evidence}. A mandatory flag keeps a CREATE out of any automatic current-activation lane until the owner resolves it."""
    pol = pol or load_policy()
    label, sib, hints = provider_id_label_evidence(subjects, catalog, pol), sibling_mapped_evidence(subjects), r6_hints(ids, r6, pol)
    out: dict[str, dict] = {}
    for g in ids:
        flags, ev = [], []
        if g in label:
            flags.append(CROSS_BRAND)
            ev += label[g] + sib.get(g, [])
        if g in hints:
            flags.append(R6_HINT)
            ev += hints[g]
        out[g] = {"flags": flags, "mandatory_owner_review": CROSS_BRAND in flags and pol["cross_brand"]["mandatory_owner_review"], "evidence": ev}
    return out
