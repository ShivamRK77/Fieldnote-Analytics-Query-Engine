"""GenAI planner: LLM turns the question into SQL, grounded in the semantic layer.

What makes this more than 'prompt -> SQL':
  * the prompt carries the live schema, real distinct values, metric definitions, synonyms,
    time phrases and the 'as of' date, so business terms map to fields deterministically;
  * similar verified past queries (feedback loop) are injected as few-shot examples;
  * on a validation/execution error the error is fed back for self-repair (done by the pipeline);
  * the model must declare assumptions and answerability, which feed confidence/explanations.
"""
from __future__ import annotations
from datetime import date

from aqe.llm.client import LLMClient
from aqe.models import Plan, Unsupported
from aqe.semantic.layer import SemanticLayer

SYSTEM = """You are the query-planning component of an analytics engine. Convert business questions into ONE read-only SQLite query.

{schema}

RULES
- Use only the tables/columns above. Query the view `sales` (it already has revenue, month, quarter, year). Never invent columns.
- Metric names the user says map through SYNONYMS to METRICS; use the exact aggregate expressions listed.
- Filter values must be copied from the listed values (match case); if the user names an entity that does not exist, still filter on it faithfully (do not substitute another value).
- Relative time ("last month", "this quarter") is relative to AS_OF = {as_of} (the latest date in the data), not the real current date. A month without a year refers to {default_year}.
- Top/bottom N overall: GROUP BY + ORDER BY + LIMIT (add a deterministic tiebreaker). Top N within groups: RANK() OVER (PARTITION BY ...) in a CTE, then filter on the rank.
- Contribution / share / percent of total: 100.0 * metric / SUM(metric) OVER (). Growth: compare against the previous period with a self-join or LAG; guard division with NULLIF.
- Target comparisons: join `targets` to monthly actual revenue on region AND month; targets exist for revenue by region only.
- ROUND monetary/percentage outputs to 2 decimals. One statement only, no comments, no trailing semicolon needed.
- If the question cannot be answered from these tables, set answerable=false and explain why. Never guess silently: list every interpretation choice in `assumptions`.
- Always respond by calling the submit_query_plan tool."""


class LLMPlanner:
    name = "llm"

    def __init__(self, client: LLMClient, sem: SemanticLayer, as_of: date, max_values: int = 50):
        self.client, self.sem, self.as_of = client, sem, as_of
        self.system = SYSTEM.format(schema=sem.describe(max_values), as_of=as_of.isoformat(),
                                    default_year=as_of.year)

    def plan(self, query: str, examples: list[tuple[str, str]] | None = None,
             previous: tuple[str, str] | None = None) -> Plan:
        parts = []
        if examples:
            parts.append("VERIFIED EXAMPLES (past questions answered correctly; follow their conventions):")
            for q, sql in examples:
                parts.append(f"Q: {q}\nSQL: {sql}")
        if previous:
            parts.append(f"YOUR PREVIOUS ATTEMPT FAILED.\nSQL: {previous[0]}\nERROR: {previous[1]}\nFix it.")
        parts.append(f"QUESTION: {query}")
        out = self.client.plan(self.system, "\n\n".join(parts))
        if not out.get("answerable", True):
            raise Unsupported(out.get("unanswerable_reason") or "the model judged the question unanswerable from this data")
        sql = (out.get("sql") or "").strip()
        if not sql:
            raise Unsupported("model returned no SQL")
        try:
            conf = max(0.0, min(1.0, float(out.get("self_confidence", 0.5))))
        except (TypeError, ValueError):
            conf = 0.5
        return Plan(sql=sql, interpretation=out.get("interpretation", ""), planner="llm",
                    assumptions=list(out.get("assumptions") or []), self_confidence=conf)
