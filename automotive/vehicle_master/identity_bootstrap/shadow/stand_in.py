"""STAND-IN for the Identity Resolution layer, for the shadow run only.

Identity Resolution (PR #200) owns every lexical relation. This module supplies only what Bootstrap's input needs but Bootstrap does not compute and PR #200's export does not
carry: the brand resolution (and brand family hints) and the resolver-activation switch for mode A. **It contains no matcher.** Every subject->target and subject->subject name
relation is a direct lookup in the verified PR #200 relation export (`ir_export`); a pair the export does not carry is an error, never a CONTRADICTION.
"""
from __future__ import annotations

import json
import unicodedata

from identity_bootstrap.engine.lexical import Lexicon

from . import ir_export
from .ir_export import RelationExport

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


class StandIn:
    def __init__(self, catalog: dict, policy: dict, export: RelationExport, naive_spellings: bool = False, families: bool = True):
        self.lex = Lexicon(policy)
        self.export = export        # the verified PR #200 relation export: the only source of a name relation
        self.naive_spellings = naive_spellings      # offer every catalog alias (sub-brands included) as a spelling, as the first shadow pass did
        self.families = families
        self.creatable_relations = tuple(policy["brand"]["creatable_relations"])
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

    # ---- brand ----
    def local_brand_hint(self, ice_brand: str) -> dict:
        """The consumer's OWN brand/catalog-alias reading of an Ice brand string. A DIAGNOSTIC and spelling source only: it never decides the brand Bootstrap is given, the candidate pool or a relation
        (those come from the producer's typed brand relation `br` and pool, see `brand_from_export`). Parity compares it with the producer view and fails closed when they disagree."""
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
        self._brand_cache[ice_brand] = out
        return out

    def spellings_for(self, brand_id: str) -> list[str]:
        """How a model name of this brand may start (display / prefix stripping only; carries no relation and no pool member)."""
        b = self.brands[brand_id]
        aliases = b.get("aliases", []) if self.naive_spellings else self._own_aliases(brand_id, b)
        return sorted({b["name_en"], brand_id.replace("_", " "), *aliases, *CURATED_SPELLINGS.get(brand_id, [])})

    def brand_from_export(self, ice_brand: str, subject_ids: list[str]) -> dict:
        """Relation-first brand for Bootstrap's input: the brand and relation are exactly what the producer's pool and typed brand relation (`br`) say, never the local alias table.
        All subjects carrying one Ice brand string must have the same producer view (the snapshot carries the brand per string); a split view is an error, not a guess."""
        views = {json.dumps(ir_export.producer_brand(self.export, g), sort_keys=True) for g in subject_ids}
        if len(views) != 1:
            raise ir_export.ExportError(f"BRAND_VIEW_SPLIT: the producer gives {len(views)} different brand views for the Ice brand {ice_brand!r}")
        view = json.loads(next(iter(views)))
        out = {"raw": ice_brand, "brand_id": view["brand_id"], "relation": view["relation"]}
        if view["brand_id"] and view["relation"] in self.creatable_relations:
            out["spellings"] = self.spellings_for(view["brand_id"])        # an ALIAS_RELATED marque is only ever a suspicion: its name is not offered as a spelling of the subject's brand
        if self.families and view["family"]:
            out["family"] = [{"brand_id": f["brand_id"], "relation": f["relation"], "spellings": [self.brands[f["brand_id"]]["name_en"]]} for f in view["family"]]
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

    # ---- relations: direct lookups only ----
    def target_relations(self, gid: str) -> list[dict]:
        """The subject's relations to the TDR models of ITS POOL, as the export carries them. CONTRADICTION and UNAVAILABLE are explicit 'no objection' rows and are not passed on."""
        out = []
        for cid in self.export.pool(gid):
            rel = self.export.relation_ice_tdr(gid, cid)
            if rel not in ("CONTRADICTION", "UNAVAILABLE"):
                out.append({"peer_kind": "TARGET", "peer_id": cid, "identity_state": None, "name_relation": rel})
        return out

    def subject_relations(self, gids: list[str]) -> dict[str, list[dict]]:
        """Ice x Ice relations stated once, from the smaller id (the export's orientation: SUBJECT_COARSER = the smaller id's tokens are a proper subset)."""
        out: dict[str, list[dict]] = {g: [] for g in gids}
        for g in gids:
            for peer in self.export.peers(g):
                if g < peer:
                    rel = self.export.relation_ice_ice(g, peer)
                    if rel not in ("CONTRADICTION", "UNAVAILABLE"):
                        out[g].append({"peer_kind": "SUBJECT", "peer_id": peer, "name_relation": rel})
        return out

    def brand_family_candidates(self, brand: dict) -> list[str]:
        """What the milestone-2/3 stand-in treated as the candidate set (every TDR model of the resolved brand family). Used ONLY to report candidate-pool parity against the export."""
        if not brand.get("brand_id"):
            return []
        return sorted(i["canonical_id"] for bid in self._family(brand["brand_id"]) for i in self.by_brand.get(bid, ()))

    @staticmethod
    def activation(relations: list[dict], mode: str) -> dict:
        """Mode B force-activates every subject (a stress scenario, not an upper bound on CREATE). Mode A lets a lexical duplicate of a TDR model stop at the resolver, as IR would."""
        if mode == "A" and any(r["peer_kind"] == "TARGET" and r["name_relation"] in DUPLICATE_RELATIONS for r in relations):
            return {"outcome": "PROPOSE", "reason_codes": ["STAND_IN_LEXICAL_DUPLICATE"]}
        return {"outcome": "NO_CANDIDATE", "reason_codes": []}
