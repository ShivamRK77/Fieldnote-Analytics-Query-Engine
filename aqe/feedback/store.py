"""Feedback loop backed by feedback_log.csv (created on first write; optional on read).

Columns: timestamp, query, generated_logic, rating, corrected_logic, comment
  rating: 1 / good / correct  |  -1 / bad / incorrect
Uses of the log:
  1. few-shot: similar queries that were rated good (or corrected) become LLM examples;
  2. reuse: a near-identical query with a corrected SQL reuses that SQL directly;
  3. penalty: a similar query whose SQL was rated bad (and not fixed) lowers confidence when
     the engine would produce the same SQL again.
"""
from __future__ import annotations
import csv
import io
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

COLS = ["timestamp", "query", "generated_logic", "rating", "corrected_logic", "comment"]
_STOP = {"the", "a", "an", "in", "of", "for", "by", "per", "to", "is", "are", "what", "which", "show", "me", "and", "please", "give", "list", "get"}
POS = {"1", "good", "correct", "up", "true", "yes", "+1"}
NEG = {"-1", "0", "bad", "incorrect", "down", "false", "no", "wrong"}


def _tokens(text: str) -> set[str]:
    toks = re.findall(r"[a-z0-9]+", text.lower())
    return {t[:-1] if len(t) > 3 and t.endswith("s") else t for t in toks if t not in _STOP}


def similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


@dataclass
class Entry:
    query: str
    generated_logic: str
    rating: int
    corrected_logic: str
    comment: str

    @property
    def good_sql(self) -> str | None:
        if self.corrected_logic:
            return self.corrected_logic
        return self.generated_logic if self.rating > 0 else None


class FeedbackStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.entries: list[Entry] = []
        self.load()

    def load(self) -> None:
        self.entries = []
        if not self.path.exists():
            return
        text = self.path.read_bytes().decode("utf-8-sig")
        for row in csv.DictReader(io.StringIO(text, newline="")):
            r = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            if not r.get("query"):
                continue
            raw = r.get("rating", "").lower()
            rating = 1 if raw in POS else -1 if raw in NEG else 0
            self.entries.append(Entry(r["query"], r.get("generated_logic", ""), rating,
                                      r.get("corrected_logic", ""), r.get("comment", "")))

    def similar(self, query: str, threshold: float, k: int = 3) -> list[tuple[Entry, float]]:
        scored = [(e, similarity(query, e.query)) for e in self.entries]
        return sorted([x for x in scored if x[1] >= threshold], key=lambda x: -x[1])[:k]

    def record(self, query: str, generated_logic: str, rating: int, corrected_logic: str = "", comment: str = "") -> None:
        new = not self.path.exists()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(COLS)
            w.writerow([datetime.now(timezone.utc).isoformat(timespec="seconds"), query, generated_logic,
                        rating, corrected_logic, comment])
        self.load()
