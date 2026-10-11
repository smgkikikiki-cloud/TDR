"""STAND-IN for the Identity Resolution layer, for the shadow run only (PR #200 has no engine).

Supplies what Bootstrap's input needs but Bootstrap does not compute: the brand resolution, subject->target and subject->subject name relations
(IR draft section 5.3 semantics, simplified), and the resolution outcome. Simplifications are listed in README_SHADOW and in the report: no series
evidence, no model-alias table beyond the TDR catalog's own aliases, a tiny token-equivalence list, edit-distance-1 fuzzy matching.
"""
from __future__ import annotations

import unicodedata

from identity_bootstrap.engine.lexical import Lexicon

TOKEN_EQUIVALENCE = [["ev", "electric"], ["hatch", "hatchback"], ["hev", "hybrid"]]       # assumption, shared with the IR draft's open list
FUZZY_MIN_TOKEN = 4
STRENGTH = ["EQUAL", "EQUAL_VIA_MODEL_ALIAS", "EQUAL_VIA_TOKEN_EQUIV", "FUZZY", "SUBJECT_FINER", "SUBJECT_COARSER", "SIBLING", "CONTRADICTION"]
BRAND_CLASSES = [["changan", "deepal"]]        # Ice files Deepal models under CHANGAN (IR README section 3); one marque family for pooling
#: What Bootstrap's duplicate defence is told about related marques (input brand.family). Names of the family are compared, never stripped from the subject's own.
FAMILIES = {"changan": [("deepal", "ALIAS_RELABEL", ["Deepal"])], "deepal": [("changan", "ALIAS_RELABEL", ["Changan"])]}
CURATED_BRAND_ALIASES = {"mercedes": "mercedes_benz", "benz": "mercedes_benz", "mercedesbenz": "mercedes_benz", "vw": "volkswagen"}
#: Extra spellings a model name may lead with. Catalog aliases that are SUB-BRANDS (gwm: haval/ora/tank, chery: omoda/jetour) are NOT spellings of the brand:
#: stripping them turned "Ora 5" into the canonical name "5" in the first shadow pass.
CURATED_SPELLINGS = {"mercedes_benz": ["Mercedes", "Benz"], "volkswagen": ["VW"], "gwm": ["Great Wall", "Great Wall Motor"], "mg": ["Morris Garages"]}
DUPLICATE_RELATIONS = {"EQUAL", "EQUAL_VIA_MODEL_ALIAS", "EQUAL_VIA_TOKEN_EQUIV", "FUZZY"}


def comp(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", text).casefold() if c.isalnum() or "฀" <= c <= "๿")


def _edit1(a: str, b: str) -> bool:
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    short, long_ = sorted((a, b), key=len)
    return any(long_[:i] + long_[i + 1:] == short for i in range(len(long_)))


def name_relation(a: list[str], b: list[str], refined: bool = False, non_distinctive: frozenset[str] = frozenset()) -> str:
    """Relation of subject tokens `a` to peer tokens `b`, oriented as IR section 5.3 (SUBJECT_FINER = a contains b).

    refined=False follows the IR draft: FUZZY = every differing token pairs with a one-edit token (length >= 4); SIBLING = any shared token.
    refined=True is a what-if for the shadow report only: FUZZY never applies to a token containing a digit (XC60/XC90, DB11/DB12 are different
    versions, not typos), and SIBLING needs at least one shared token that is distinctive (not a digit, not <= 2 letters, not in `non_distinctive`)."""
    if not a or not b:
        return "UNAVAILABLE"
    if "".join(a) == "".join(b):
        return "EQUAL"
    canon = {t: group[0] for group in TOKEN_EQUIVALENCE for t in group}
    if "".join(canon.get(t, t) for t in a) == "".join(canon.get(t, t) for t in b):
        return "EQUAL_VIA_TOKEN_EQUIV"
    sa, sb = set(a), set(b)
    only_a, only_b = sorted(sa - sb), sorted(sb - sa)
    if only_a and len(only_a) == len(only_b) and all(len(t) >= FUZZY_MIN_TOKEN for t in only_a + only_b) \
            and not (refined and any(ch.isdigit() for tok in only_a + only_b for ch in tok)):
        left = list(only_b)
        for t in only_a:
            hit = next((u for u in left if _edit1(t, u)), None)
            if hit is None:
                break
            left.remove(hit)
        else:
            return "FUZZY"
    if sa < sb:
        return "SUBJECT_COARSER"
    if sa > sb:
        return "SUBJECT_FINER"
    if sa & sb:
        if refined and not any(not tok.isdigit() and len(tok) > 2 and tok not in non_distinctive for tok in sa & sb):
            return "CONTRADICTION"
        return "SIBLING"
    return "CONTRADICTION"


class StandIn:
    def __init__(self, catalog: dict, policy: dict, refined: bool = False, naive_spellings: bool = False, families: bool = True):
        self.lex = Lexicon(policy)
        self.refined = refined
        self.naive_spellings = naive_spellings      # offer every catalog alias (sub-brands included) as a spelling, as the first shadow pass did
        self.families = families
        self.non_distinctive = frozenset(w.casefold() for cls in ("trim", "powertrain", "body", "generation") for w in policy["shape"][cls]["tokens"])
        self.brands = catalog["brands"]
        self.identities = catalog["identities"]
        self.aliases = catalog["aliases"]
        self.by_brand: dict[str, list[dict]] = {}
        for i in self.identities:
            self.by_brand.setdefault(i["brand_id"], []).append(i)
        self.key_to_brand = {}
        self.alias_keys = {}
        for bid, b in self.brands.items():
            for k in (bid, b["name_en"]):
                self.key_to_brand.setdefault(comp(k), bid)
            for k in b.get("aliases", []):
                self.alias_keys.setdefault(comp(k), bid)
        self._brand_cache: dict[str, dict] = {}
        self._peer_cache: dict[tuple, list[dict]] = {}

    # ---- brand ----
    def brand_for(self, ice_brand: str) -> dict:
        if ice_brand in self._brand_cache:
            return self._brand_cache[ice_brand]
        key = comp(ice_brand)
        if not key:
            out = {"raw": ice_brand, "brand_id": None, "relation": "UNKNOWN"}
        elif key in self.key_to_brand:
            out = {"raw": ice_brand, "brand_id": self.key_to_brand[key], "relation": "EXACT"}
        elif key in self.alias_keys or key in CURATED_BRAND_ALIASES:
            out = {"raw": ice_brand, "brand_id": self.alias_keys.get(key) or CURATED_BRAND_ALIASES[key], "relation": "ALIAS_SAME"}
        else:
            out = {"raw": ice_brand, "brand_id": None, "relation": "NOT_IN_TDR"}
        if out["brand_id"]:
            b = self.brands[out["brand_id"]]
            aliases = b.get("aliases", []) if self.naive_spellings else self._own_aliases(out["brand_id"], b)
            out["spellings"] = sorted({b["name_en"], out["brand_id"].replace("_", " "), *aliases, *CURATED_SPELLINGS.get(out["brand_id"], [])})
            if self.families and out["brand_id"] in FAMILIES:
                out["family"] = [{"brand_id": f, "relation": rel, "spellings": sp} for f, rel, sp in FAMILIES[out["brand_id"]]]
        self._brand_cache[ice_brand] = out
        return out

    @staticmethod
    def _own_aliases(brand_id: str, b: dict) -> list[str]:
        """Catalog aliases that really are spellings of THIS brand: Thai-script ones, or ones that contain the brand's own name."""
        own = {comp(brand_id), comp(b["name_en"])}
        return [a for a in b.get("aliases", []) if any(ch >= "\u0e00" and ch <= "\u0e7f" for ch in a) or any(k and k in comp(a) for k in own)]

    def _family(self, brand_id: str) -> list[str]:
        for cls in BRAND_CLASSES:
            if brand_id in cls:
                return cls
        return [brand_id]

    # ---- relations ----
    def target_relations(self, brand: dict, name: str, spellings: tuple) -> list[dict]:
        """Relations of one subject name to the TDR models of its brand family. Both names are tokenised with the UNION of both brands' spellings."""
        if not brand["brand_id"]:
            return []
        out = []
        for bid in self._family(brand["brand_id"]):
            b = self.brands[bid]
            union = spellings + (b["name_en"], bid.replace("_", " "), *self._own_aliases(bid, b), *CURATED_SPELLINGS.get(bid, []))
            mine = self.lex.tokens(name, union)
            for ident in self.by_brand.get(bid, ()):
                best = None
                for peer_name in [ident["name_en"], *self.aliases.get(ident["canonical_id"], [])]:
                    rel = name_relation(mine, self.lex.tokens(peer_name, union), self.refined, self.non_distinctive)
                    if rel in STRENGTH and (best is None or STRENGTH.index(rel) < STRENGTH.index(best)):
                        best = rel
                if best and best not in ("CONTRADICTION", "UNAVAILABLE"):
                    out.append({"peer_kind": "TARGET", "peer_id": ident["canonical_id"], "identity_state": None, "name_relation": best})
        return out

    def subject_relations(self, rows: list[dict], tokens: dict[str, list[str]]) -> dict[str, list[dict]]:
        """Pairwise relations between Ice subjects of the same Ice brand, stated once (from the lexicographically smaller id)."""
        out: dict[str, list[dict]] = {r["model_group_id"]: [] for r in rows}
        by_brand: dict[str, list[str]] = {}
        for r in rows:
            by_brand.setdefault(r["brand"], []).append(r["model_group_id"])
        for ids in by_brand.values():
            ids.sort()
            for i, a in enumerate(ids):
                for b in ids[i + 1:]:
                    rel = name_relation(tokens[a], tokens[b], self.refined, self.non_distinctive)
                    if rel not in ("CONTRADICTION", "UNAVAILABLE"):
                        out[a].append({"peer_kind": "SUBJECT", "peer_id": b, "name_relation": rel})
        return out

    @staticmethod
    def activation(relations: list[dict], mode: str) -> dict:
        """Mode B offers every subject to Bootstrap (worst case). Mode A lets a lexical duplicate of a TDR model stop at the resolver, as IR would."""
        if mode == "A" and any(r["peer_kind"] == "TARGET" and r["name_relation"] in DUPLICATE_RELATIONS for r in relations):
            return {"outcome": "PROPOSE", "reason_codes": ["STAND_IN_LEXICAL_DUPLICATE"]}
        return {"outcome": "NO_CANDIDATE", "reason_codes": []}
