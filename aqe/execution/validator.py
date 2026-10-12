"""Post-generation grounding checks that work for ANY SQL (LLM or rule-based).

Execution already guarantees the SQL parses and touches only known columns. Here we check
the *literals*: if SQL filters `region = 'Narnia'` and no such region exists, the query is
syntactically fine but semantically ungrounded -> warn (and lower confidence).
"""
from __future__ import annotations
import re

_LIT = re.compile(r"\b(?:(?:sales|targets|s|t)\.)?([a-z_]+)\s*(=|!=|<>|IN|LIKE)\s*(\([^()]*\)|'(?:[^']|'')*')", re.I)
_STR = re.compile(r"'((?:[^']|'')*)'")


def check_literals(sql: str, value_index: dict[str, set[str]]) -> list[str]:
    """value_index: column -> set of values that really occur in the data (original case)."""
    warnings: list[str] = []
    for col, op, rhs in _LIT.findall(sql):
        col = col.lower()
        if col not in value_index:
            continue
        known = value_index[col]
        known_ci = {k.lower() for k in known}
        for lit in _STR.findall(rhs):
            lit = lit.replace("''", "'")
            if op.upper() == "LIKE":
                pat = re.escape(lit.lower()).replace("%", ".*").replace("_", ".")
                ok = any(re.fullmatch(pat, k) for k in known_ci)
            else:
                ok = lit.lower() in known_ci
            if not ok:
                warnings.append(f"'{lit}' is not a known value of {col}")
            elif op == "=" and lit not in known:
                warnings.append(f"'{lit}' matches {col} only case-insensitively")
    return warnings
