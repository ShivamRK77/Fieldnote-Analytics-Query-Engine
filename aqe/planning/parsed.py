"""Intermediate representation produced by the rule-based parser and consumed by the SQL compiler."""
from __future__ import annotations
from dataclasses import dataclass, field
from aqe.semantic.time_resolver import TimeFilter


@dataclass
class ParsedQuery:
    intent: str = "aggregate"      # aggregate | rank | contribution | target | growth
    metrics: list[str] = field(default_factory=list)
    group_by: list[str] = field(default_factory=list)
    rank_dim: str | None = None
    partition: list[str] = field(default_factory=list)
    n: int | None = None
    ascending: bool = False
    filters: list[tuple[str, list[str], bool]] = field(default_factory=list)   # (col, values, negated)
    time: TimeFilter | None = None
    growth_grain: str = "year"
    growth_kind: str = "yoy"       # yoy | prev
    target_status: str | None = None   # missed | met
    having: tuple[str, float] | None = None
    avg_of_rows: bool = False
