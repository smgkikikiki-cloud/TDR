"""Name tokens, canonical name, identity key and shape suspicions (SPEC §4, §6 G5). All vocabulary comes from the policy."""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

THAI = ("฀", "๿")


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def plain_tokens(text: str, boundary: frozenset[str]) -> list[str]:
    out, word = [], []
    for ch in _fold(text):
        if ch in boundary or ch.isspace():
            if word:
                out.append("".join(word)); word = []
        elif ch.isalnum() or THAI[0] <= ch <= THAI[1]:
            word.append(ch)
    if word:
        out.append("".join(word))
    return out


class Lexicon:
    """The policy's lexical settings, compiled once per run."""

    def __init__(self, policy: dict):
        self.boundary = frozenset(policy["lexical"]["token_boundary_characters"])
        self.generic = frozenset(_fold(g) for g in policy["lexical"]["generic_tokens"])
        shape = policy["shape"]
        self.classes = []
        for cls, code in shape["codes"].items():
            spec = shape[cls]
            self.classes.append((code, frozenset(_fold(t) for t in spec.get("tokens", [])),
                                 [re.compile(p) for p in spec.get("token_patterns", [])],
                                 [re.compile(p) for p in spec.get("name_patterns", [])],
                                 [re.compile(p) for p in spec.get("contextual_token_patterns", [])], spec.get("contextual_min_tokens", 2)))
        trunc = shape["truncation"]
        self.trunc_code, self.trunc_min, self.trunc_digits_exempt = trunc["code"], trunc["min_compact_chars"], trunc["exempt_digit_only"]
        self.dangling = frozenset(_fold(w) for w in trunc["dangling_tokens"])
        self.sub_brands = {bid: frozenset("".join(plain_tokens(n, self.boundary)) for n in names) for bid, names in policy["brand"]["sub_brands"].items()}
        unavailable = policy["subject"]["unavailable_name_values"]
        self.unavailable = frozenset("".join(plain_tokens(v, self.boundary)) for v in unavailable)
        raw = policy["subject"]["raw_name"]
        self.raw_separators = tuple(raw["separator_characters"])
        self.raw_code = re.compile(raw["registration_code_token_pattern"])
        self.code_segment = re.compile(raw["code_segment_pattern"])
        self.strip_brand = policy["allocation"]["canonical_name"]["strip_brand_prefix"]
        self.collapse = policy["allocation"]["canonical_name"]["collapse_whitespace"]

    def tokens(self, name: str, spellings: tuple[str, ...]) -> list[str]:
        toks = plain_tokens(name, self.boundary)
        best = 0
        for spelling in spellings:
            lead = plain_tokens(spelling, self.boundary)
            if lead and len(lead) < len(toks) and toks[:len(lead)] == lead:
                best = max(best, len(lead))
        return [t for t in toks[best:] if t not in self.generic]

    def canonical_name(self, display: str, spellings: tuple[str, ...]) -> str:
        words = display.split()
        if self.strip_brand:
            best = 0
            for spelling in spellings:
                lead = plain_tokens(spelling, self.boundary)
                seen: list[str] = []
                for count, word in enumerate(words, start=1):
                    seen += plain_tokens(word, self.boundary)
                    if seen == lead:
                        if lead and count < len(words):
                            best = max(best, count)
                        break
                    if lead[:len(seen)] != seen:
                        break
            words = words[best:]
        return " ".join(words) if self.collapse else display

    def marque_spellings(self, brand_id: str | None, spellings: tuple[str, ...]) -> tuple[str, ...]:
        """Only spellings of the marque itself: a sub-brand the adapter offered (Ora/Haval/Tank under GWM) is dropped, never stripped from a name."""
        banned = self.sub_brands.get(brand_id or "", frozenset())
        return tuple(s for s in spellings if "".join(plain_tokens(s, self.boundary)) not in banned)

    def unavailable_name(self, tokens: list[str]) -> bool:
        return not tokens or "".join(tokens) in self.unavailable

    def raw_shaped(self, entity_id: str, display: str, tokens: list[str]) -> bool:
        return any(c in entity_id or c in display for c in self.raw_separators) or any(self.raw_code.search(t) for t in tokens) \
            or bool(self.code_segment.search(_fold(display)))

    def shape(self, display: str, tokens: list[str]) -> set[str]:
        lowered = _fold(display)
        joined = ["".join(tokens)] if len(tokens) > 1 else []
        fired = set()
        for code, words, token_patterns, name_patterns, contextual, min_tokens in self.classes:
            if any(t in words for t in tokens) \
                    or any(p.search(t) for p in token_patterns for t in tokens + joined) \
                    or any(p.search(lowered) for p in name_patterns) \
                    or (len(tokens) >= min_tokens and any(p.search(t) for p in contextual for t in tokens)):
                fired.add(code)
        if tokens:
            compact = "".join(tokens)
            if (len(compact) < self.trunc_min and not (self.trunc_digits_exempt and compact.isdigit())) or all(t in self.dangling for t in tokens):
                fired.add(self.trunc_code)
        return fired
