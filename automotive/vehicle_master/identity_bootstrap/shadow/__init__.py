"""Read-only shadow evaluation of Identity Bootstrap on a pinned Ice package. Writes only report files under a caller-given output directory.

``stand_in`` is a lexical STAND-IN for the Identity Resolution layer (PR #200 has no engine yet). It exists so the shadow run can feed the
engine realistic relations; it is not part of the contract and must be replaced by Identity Resolution's own output when that exists.
"""
