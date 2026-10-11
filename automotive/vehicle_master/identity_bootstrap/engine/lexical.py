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
                                 [re.compile(p) for p in spec.get("name_patterns", [])]))
        unavailable = policy["subject"]["unavailable_name_values"]
        self.unavailable = frozenset("".join(plain_tokens(v, self.boundary)) for v in unavailable)
        raw = policy["subject"]["raw_name"]
        self.raw_separators = tuple(raw["separator_characters"])
        self.raw_code = re.compile(raw["registration_code_token_pattern"])
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

    def unavailable_name(self, tokens: list[str]) -> bool:
        return not tokens or "".join(tokens) in self.unavailable

    def raw_shaped(self, entity_id: str, display: str, tokens: list[str]) -> bool:
        return any(c in entity_id or c in display for c in self.raw_separators) or any(self.raw_code.search(t) for t in tokens)

    def shape(self, display: str, tokens: list[str]) -> set[str]:
        lowered = _fold(display)
        joined = ["".join(tokens)] if len(tokens) > 1 else []
        fired = set()
        for code, words, token_patterns, name_patterns in self.classes:
            if any(t in words for t in tokens) \
                    or any(p.search(t) for p in token_patterns for t in tokens + joined) \
                    or any(p.search(lowered) for p in name_patterns):
                fired.add(code)
        return fired
