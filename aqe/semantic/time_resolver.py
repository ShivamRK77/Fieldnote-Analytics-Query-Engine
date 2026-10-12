"""Resolve time phrases ('March', 'Q1 2024', 'last month', 'this quarter', '2024') to SQL
conditions on the derived month/quarter/year columns. Relative phrases are anchored to
`as_of` (default: latest order date in the data, because 'today' is outside the dataset)."""
from __future__ import annotations
import re
from dataclasses import dataclass
from datetime import date

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], 1)}
ABBR = {k[:3]: v for k, v in MONTHS.items()} | {"sept": 9}


@dataclass
class TimeFilter:
    column: str            # month | quarter | year
    values: list[str]
    description: str
    assumption: str | None = None

    def sql(self) -> str:
        if len(self.values) == 1:
            return f"{self.column} = '{self.values[0]}'"
        return f"{self.column} IN ({', '.join(repr(v) for v in self.values)})"


def _shift_month(y: int, m: int, delta: int) -> tuple[int, int]:
    idx = y * 12 + (m - 1) + delta
    return idx // 12, idx % 12 + 1


def resolve(text: str, as_of: date, data_years: list[int]) -> TimeFilter | None:
    t = text.lower()
    ay, am = as_of.year, as_of.month
    aq = (am - 1) // 3 + 1

    # relative phrases
    m = re.search(r"\b(last|previous|prior|past|this|current)\s+(month|quarter|year)\b", t)
    if m:
        which, unit = m.groups()
        delta = -1 if which in ("last", "previous", "prior", "past") else 0
        if unit == "month":
            y, mo = _shift_month(ay, am, delta)
            return TimeFilter("month", [f"{y}-{mo:02d}"], f"{which} {unit} = {y}-{mo:02d} (relative to {as_of})",
                              f"'{which} {unit}' anchored to {as_of} (latest date in data)")
        if unit == "quarter":
            qi = ay * 4 + (aq - 1) + delta
            y, q = qi // 4, qi % 4 + 1
            return TimeFilter("quarter", [f"{y}-Q{q}"], f"{which} {unit} = {y}-Q{q} (relative to {as_of})",
                              f"'{which} {unit}' anchored to {as_of} (latest date in data)")
        y = ay + delta
        return TimeFilter("year", [str(y)], f"{which} {unit} = {y}", f"'{which} {unit}' anchored to {as_of}")

    # explicit YYYY-MM
    m = re.search(r"\b(20\d{2})-(0[1-9]|1[0-2])\b", t)
    if m:
        return TimeFilter("month", [f"{m.group(1)}-{m.group(2)}"], f"month {m.group(1)}-{m.group(2)}")

    # quarter: Q1 2024 / 2024 Q1 / q1
    m = re.search(r"\bq([1-4])\b(?:\s*(?:of\s*)?(20\d{2}))?", t) or None
    if m:
        y = m.group(2) or str(max(data_years))
        return TimeFilter("quarter", [f"{y}-Q{m.group(1)}"], f"quarter {y}-Q{m.group(1)}",
                          None if m.group(2) or len(data_years) == 1 else f"year not given; assumed {y}")
    m = re.search(r"\b(20\d{2})\s*q([1-4])\b", t)
    if m:
        return TimeFilter("quarter", [f"{m.group(1)}-Q{m.group(2)}"], f"quarter {m.group(1)}-Q{m.group(2)}")

    # month name (optionally with year). 'may' only counts after a preposition to avoid the verb.
    pat = r"\b(" + "|".join(list(MONTHS) + list(ABBR)) + r")\b(?:\s*,?\s*(20\d{2}))?"
    for m in re.finditer(pat, t):
        name = m.group(1)
        if name == "may" and not re.search(r"\b(in|for|during|of|since|until)\s+may\b", t) and not m.group(2):
            continue
        if name in ("mar", "jan", "dec", "sep", "oct", "nov", "aug", "jun", "jul", "apr", "feb") and \
                not re.search(r"\b(in|for|during|of)\s+" + name + r"\b", t) and not m.group(2) and name not in MONTHS:
            continue
        mo = MONTHS.get(name) or ABBR.get(name)
        if not mo:
            continue
        y = m.group(2) or str(max(data_years))
        return TimeFilter("month", [f"{y}-{mo:02d}"], f"month {y}-{mo:02d}",
                          None if m.group(2) or len(data_years) == 1 else f"year not given; assumed {y}")

    m = re.search(r"\b(?:in|for|during|of)?\s*(20\d{2})\b", t)
    if m:
        return TimeFilter("year", [m.group(1)], f"year {m.group(1)}")
    return None
