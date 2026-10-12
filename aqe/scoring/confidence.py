"""Confidence score in [0, 1]. A transparent heuristic, not a calibrated probability.

  base      planner evidence. One planner: its own confidence (LLM self-report / rule coverage).
            Two independent planners that AGREE on the executed result: noisy-OR
            1-(1-p1)(1-p2). If they DISAGREE: 0.4 * max(p1, p2).
  penalties multiplicative factors, each explained to the user:
            ungrounded literal (value not in data)      x0.5 each (min 0.2)
            self-repair needed                          x0.85 per repair
            empty result                                x0.6
            all-NULL column (e.g. no prior-year data)   x0.7
            truncated result                            x0.9
            similar past query rated bad                x0.6
  bonus     similar past query rated good with same SQL: +0.05
Capped at 0.98 so the system never claims certainty.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class ConfidenceInputs:
    p_primary: float
    p_verifier: float | None = None        # independent second planner, if it produced a result
    agreement: bool | None = None          # None = no verifier result available
    ungrounded_literals: int = 0
    repairs: int = 0
    empty_result: bool = False
    null_columns: int = 0
    truncated: bool = False
    feedback_negative: bool = False
    feedback_positive: bool = False
    notes: list[str] = field(default_factory=list)


def score(i: ConfidenceInputs) -> tuple[float, list[str]]:
    reasons: list[str] = []
    if i.agreement is True and i.p_verifier is not None:
        base = 1 - (1 - i.p_primary) * (1 - i.p_verifier)
        reasons.append("two independent planners produced the same result")
    elif i.agreement is False:
        base = 0.4 * max(i.p_primary, i.p_verifier or 0)
        reasons.append("the two planners produced DIFFERENT results")
    else:
        base = i.p_primary
    mult = 1.0
    if i.ungrounded_literals:
        mult *= max(0.2, 0.5 ** i.ungrounded_literals); reasons.append(f"{i.ungrounded_literals} filter value(s) not found in the data")
    if i.repairs:
        mult *= 0.85 ** i.repairs; reasons.append(f"needed {i.repairs} self-repair attempt(s)")
    if i.empty_result:
        mult *= 0.6; reasons.append("result is empty")
    if i.null_columns:
        mult *= 0.7; reasons.append("some output columns are entirely NULL (insufficient data for the calculation)")
    if i.truncated:
        mult *= 0.9; reasons.append("result truncated to the row cap")
    if i.feedback_negative:
        mult *= 0.6; reasons.append("a similar past answer was rated bad")
    out = base * mult
    if i.feedback_positive:
        out += 0.05; reasons.append("a similar past answer was rated good")
    return round(max(0.0, min(0.98, out)), 2), reasons
