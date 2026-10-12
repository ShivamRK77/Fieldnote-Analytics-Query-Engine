"""Builds the human-readable explanation: what was understood, and how the result was produced."""
from __future__ import annotations
import re
from aqe.models import Attempt


def query_context(plan, sql: str) -> dict[str, object]:
    """Expose only grounded, presentation-safe interpretation fields for the UI."""
    metrics = sorted({phrase for phrase, target in plan.grounded_terms.items() if target.startswith("metric:")})
    dimensions = sorted({phrase for phrase, target in plan.grounded_terms.items() if target.startswith("dimension:")})
    filters = sorted({phrase for phrase, target in plan.grounded_terms.items() if target.startswith("value:")})
    time_range = plan.grounded_terms.get("time") or "Not specified"
    is_ranking = plan.interpretation.lower().startswith("rank ")
    ranking = "Not applicable"
    limit = "Not applicable"
    if is_ranking:
        ranking = f"Ranked {' and '.join(dimensions)} by {' and '.join(metrics)}".strip()
        rank_limit = re.search(r"\brnk\s*<=\s*(\d+)\b", sql, re.I)
        sql_limit = re.search(r"\bLIMIT\s+(\d+)\b", sql, re.I)
        found_limit = rank_limit or sql_limit
        limit = found_limit.group(1) if found_limit else "Not specified"

    threshold = re.search(
        r"\bHAVING\b.*?\b(?:SUM|COUNT|AVG|MIN|MAX)\s*\([^)]*\)\s*(>=|<=|<>|!=|=|>|<)\s*(-?\d+(?:\.\d+)?)",
        sql,
        re.I | re.S,
    )
    if threshold:
        metric = metrics[0] if metrics else "aggregate value"
        filters.append(f"{metric} {threshold.group(1)} {threshold.group(2)}")

    why_parts = []
    if metrics:
        why_parts.append(f"metric: {', '.join(metrics)}")
    if dimensions:
        why_parts.append(f"dimensions: {', '.join(dimensions)}")
    if filters:
        why_parts.append(f"filters: {', '.join(filters)}")
    if is_ranking:
        why_parts.append(f"ranking: {ranking} (limit {limit})")
    if time_range != "Not specified":
        why_parts.append(f"time range: {time_range}")
    if plan.assumptions:
        why_parts.append(f"assumptions: {'; '.join(plan.assumptions)}")
    interpretation = plan.interpretation.strip()
    why = "The engine interpreted the question using " + "; ".join(why_parts) + "." if why_parts else \
        interpretation or "No additional interpretation metadata was recorded for this result."

    return {
        "metrics": metrics,
        "dimensions": dimensions,
        "filters": filters,
        "ranking": ranking,
        "limit": limit,
        "time_range": time_range,
        "interpretation": interpretation,
        "why": why,
    }


def build(query: str, attempt: Attempt | None, *, mode_note: str, verifier_note: str | None,
          conf_reasons: list[str], warnings: list[str], failure: str | None = None) -> str:
    if attempt is None:
        return f"Could not answer. {failure} {mode_note}".strip()
    p = attempt.plan
    parts = [f"UNDERSTOOD: {p.interpretation}."]
    if p.grounded_terms:
        mapped = "; ".join(f"'{k}' -> {v}" for k, v in p.grounded_terms.items())
        parts.append(f"TERM MAPPING: {mapped}.")
    how = {"llm": "A GenAI model translated the question into SQL using the live schema, metric definitions and synonyms",
           "rules": "A deterministic grammar over the semantic layer translated the question into SQL",
           "feedback": "A previously corrected query from the feedback log was reused"}[p.planner]
    steps = [f"HOW: {how}; the SQL was validated (read-only, whitelisted tables, literal values checked against the data) and executed in a sandboxed SQLite database"]
    if attempt.repairs:
        steps.append(f"after {attempt.repairs} automatic repair attempt(s)")
    parts.append(", ".join(steps) + ".")
    if verifier_note:
        parts.append(f"CROSS-CHECK: {verifier_note}")
    if p.assumptions:
        parts.append("ASSUMPTIONS: " + "; ".join(p.assumptions) + ".")
    if p.unresolved:
        parts.append("NOT UNDERSTOOD (ignored): " + ", ".join(p.unresolved) + ".")
    if warnings:
        parts.append("WARNINGS: " + "; ".join(warnings) + ".")
    if conf_reasons:
        parts.append("CONFIDENCE FACTORS: " + "; ".join(conf_reasons) + ".")
    parts.append(mode_note)
    return " ".join(x for x in parts if x)
