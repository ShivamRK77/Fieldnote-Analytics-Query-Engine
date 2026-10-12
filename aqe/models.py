"""Shared data structures."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Plan:
    """What a planner produced: executable SQL plus its own account of how/why."""
    sql: str
    interpretation: str                       # what the system understood
    planner: str                              # "llm" | "rules" | "feedback"
    assumptions: list[str] = field(default_factory=list)
    self_confidence: float = 0.5              # planner's own belief (0..1)
    grounded_terms: dict[str, str] = field(default_factory=dict)   # phrase -> schema element
    unresolved: list[str] = field(default_factory=list)            # query words nothing explained
    notes: list[str] = field(default_factory=list)


class Unsupported(Exception):
    """Planner could not interpret the query."""


@dataclass
class ExecResult:
    columns: list[str]
    rows: list[dict[str, Any]]
    truncated: bool = False


@dataclass
class Attempt:
    plan: Plan
    result: ExecResult | None = None
    error: str | None = None
    warnings: list[str] = field(default_factory=list)
    repairs: int = 0
