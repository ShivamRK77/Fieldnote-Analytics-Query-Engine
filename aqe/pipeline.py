"""Orchestrator: NL question -> plan -> validate -> execute -> verify -> score -> explain."""
from __future__ import annotations
import logging
import time
from collections import Counter
from datetime import date
from typing import Any

from aqe.execution.database import Database, QueryError
from aqe.execution.validator import check_literals
from aqe.explain import explainer
from aqe.feedback.store import FeedbackStore
from aqe.ingestion import loader, profiler
from aqe.llm.client import LLMClient, default_client
from aqe.models import Attempt, ExecResult, Plan, Unsupported
from aqe.planning.llm_planner import LLMPlanner
from aqe.planning.rule_planner import RulePlanner
from aqe.scoring import confidence
from aqe.semantic.layer import SemanticLayer, load_overrides
from aqe.settings import Settings

log = logging.getLogger(__name__)

_PERFORMANCE_STAGES = (
    "interpretation_and_sql_generation",
    "sql_validation",
    "database_execution",
    "result_formatting",
)


def _measure(timings: dict[str, int], stage: str, operation, *args, **kwargs):
    started = time.perf_counter_ns()
    try:
        return operation(*args, **kwargs)
    finally:
        timings[stage] = timings.get(stage, 0) + time.perf_counter_ns() - started


def _confidence_state(value: float) -> str:
    if value >= 0.8:
        return "high"
    if value >= 0.5:
        return "medium"
    return "low"


def _confidence_breakdown(overall: float, plan: Plan | None, warnings: list[str], *,
                          sql_validated: bool, execution_completed: bool, rows: int,
                          null_columns: int, truncated: bool, repairs: int) -> dict[str, Any]:
    grounding_warnings = [warning for warning in warnings if "not a known value" in warning]
    if plan is None:
        schema_state, schema_detail = "low", "The planner could not map the question to the available schema."
    elif grounding_warnings:
        schema_state, schema_detail = "low", f"{len(grounding_warnings)} filter value(s) were not grounded in the data."
    elif plan.unresolved:
        schema_state, schema_detail = "medium", f"{len(plan.unresolved)} term(s) were not mapped."
    elif plan.grounded_terms:
        schema_state, schema_detail = "high", f"{len(plan.grounded_terms)} query term(s) were mapped by the planner."
    else:
        schema_state, schema_detail = "not_measured", "The planner did not provide term-level schema mappings."

    if not sql_validated:
        sql_state, sql_detail = "low", "No successful SQL validation was recorded."
    elif grounding_warnings:
        sql_state, sql_detail = "low", f"SQL ran, but {len(grounding_warnings)} filter value(s) were not found in the data."
    elif repairs:
        sql_state, sql_detail = "medium", f"SQL passed validation after {repairs} repair attempt(s)."
    else:
        sql_state, sql_detail = "high", "SQL passed the read-only execution checks without repair."

    if not execution_completed:
        execution_state, execution_detail = "low", "The query did not complete execution."
    elif truncated:
        execution_state, execution_detail = "medium", f"Execution completed with results capped at {rows} rows."
    elif repairs:
        execution_state, execution_detail = "medium", f"Execution completed after {repairs} repair attempt(s)."
    else:
        execution_state, execution_detail = "high", f"Execution completed and returned {rows} row(s)."

    if rows == 0:
        result_state, result_detail = "low", "No result rows were returned."
    elif null_columns:
        result_state, result_detail = "low", f"{null_columns} output column(s) were entirely NULL."
    elif truncated:
        result_state, result_detail = "medium", "The returned result was truncated to the row limit."
    else:
        result_state, result_detail = "high", "Returned rows contain usable result values."

    query_score = plan.self_confidence if plan is not None else None
    query_detail = plan.interpretation if plan is not None and plan.interpretation else \
        "The planner could not produce a supported interpretation."
    query_component = {
        "name": "Query Understanding",
        "state": _confidence_state(query_score) if query_score is not None else "not_measured",
        "detail": query_detail,
    }
    if query_score is not None:
        query_component["percentage"] = round(query_score * 100)
    components = [
        query_component,
        {"name": "Schema Match", "state": schema_state, "detail": schema_detail},
        {"name": "SQL Validation", "state": sql_state, "detail": sql_detail},
        {"name": "Execution Quality", "state": execution_state, "detail": execution_detail},
        {"name": "Result Quality", "state": result_state, "detail": result_detail},
    ]
    return {"overall": overall, "overall_state": _confidence_state(overall), "components": components}


def _clarification_suggestions(query: str, score: float, plan: Plan | None,
                               warnings: list[str], failure: str | None,
                               metrics: list[str]) -> list[str]:
    if score >= 0.5:
        return []
    suggestions = []
    if not query.strip():
        suggestions.append("Enter a question about the available data.")
    if plan and plan.unresolved:
        suggestions.append(f"Clarify the unmapped term(s): {', '.join(plan.unresolved)}.")
    if any("not a known value" in warning for warning in warnings) or \
            failure and "not a value in the data" in failure:
        suggestions.append("Check that the named filter values exist in the active dataset.")
    if failure and "date" in failure.lower():
        suggestions.append("Use a dataset with date values for time-based questions.")
    if not suggestions and metrics:
        suggestions.append(f"Try naming a supported metric, such as {', '.join(metrics[:4])}.")
    return suggestions[:3]


class Engine:
    """mode: 'auto' (LLM + rules cross-check if an LLM is available, else rules), 'llm', 'rules'."""

    def __init__(self, settings: Settings | None = None, llm: LLMClient | None = None, mode: str = "auto"):
        self.s = settings or Settings()
        d = self.s.dataset_dir
        sales, targets = loader.load_sales(d / "sales_data.csv"), loader.load_targets(d / "targets.csv")
        self.data_warnings = profiler.profile(sales, targets)
        self.db = Database(sales, targets, self.s.max_rows)
        self.sem = SemanticLayer(loader.load_json(d / "data_dictionary.json"), self.db, load_overrides(self.s.overrides_path))
        self.as_of = date.fromisoformat(self.s.as_of or self.sem.data_max_date or "1970-01-01")
        years = sorted({int(y) for y in self.sem.value_index["year"] if str(y).isdigit()})
        self.rules = RulePlanner(self.sem, self.as_of, years)
        self.feedback = FeedbackStore(self.s.feedback_path)
        client = llm if llm is not None else (None if mode == "rules" else default_client(self.s.llm_model, self.s.llm_max_tokens))
        self.llm = LLMPlanner(client, self.sem, self.as_of, self.s.max_distinct_values_in_prompt) if client else None
        if mode == "llm" and not self.llm:
            raise RuntimeError("mode='llm' requires ANTHROPIC_API_KEY (or an injected client)")
        self.mode = mode

    # ------------------------------------------------------------------------------ public
    def answer(self, query: str, verbose: bool = False) -> dict[str, Any]:
        started = time.perf_counter_ns()
        timings = {stage: 0 for stage in _PERFORMANCE_STAGES}
        result = self._answer(query, verbose, timings)
        if verbose:
            result.setdefault("metadata", {})["performance"] = {
                "total_ms": round((time.perf_counter_ns() - started) / 1_000_000, 3),
                "stages_ms": {
                    stage: round(duration / 1_000_000, 3)
                    for stage, duration in timings.items()
                },
            }
        return result

    def _answer(self, query: str, verbose: bool, timings: dict[str, int]) -> dict[str, Any]:
        query = (query or "").strip()
        meta: dict[str, Any] = {"planner": None, "llm_available": self.llm is not None}
        if not query:
            meta["confidence_breakdown"] = _confidence_breakdown(
                0.0, None, [], sql_validated=False, execution_completed=False,
                rows=0, null_columns=0, truncated=False, repairs=0)
            meta["clarification_suggestions"] = _clarification_suggestions(
                query, 0.0, None, [], "empty query", list(self.sem.metrics))
            return self._out(query, "", [], 0.0, "Empty query.", meta, verbose)

        sims = self.feedback.similar(query, self.s.feedback_similarity_threshold)
        attempt, failure = self._primary(query, sims, timings)
        if attempt is None:
            meta["confidence_breakdown"] = _confidence_breakdown(
                0.0, None, [], sql_validated=False, execution_completed=False,
                rows=0, null_columns=0, truncated=False, repairs=0)
            meta["clarification_suggestions"] = _clarification_suggestions(
                query, 0.0, None, [], failure, list(self.sem.metrics))
            return self._out(query, "", [], 0.0, explainer.build(query, None, mode_note="", verifier_note=None,
                             conf_reasons=[], warnings=[], failure=failure), meta, verbose)

        res = attempt.result
        meta["planner"] = attempt.plan.planner
        # ---- cross-check with the independent planner
        verifier_note, agreement, p_ver = None, None, None
        if attempt.plan.planner in ("llm", "feedback"):
            v = self._try(self.rules.plan, query, timings)
            if v and v.result is not None:
                agreement = _agree(res, v.result)
                p_ver = v.plan.self_confidence
                verifier_note = ("an independent rule-based planner produced a matching result" if agreement else
                                 f"an independent rule-based planner produced a DIFFERENT result (its SQL: {v.plan.sql.splitlines()[0]} ...)")
                meta["verifier_sql"] = v.plan.sql
            else:
                verifier_note = "the rule-based planner could not interpret this phrasing, so no independent check was possible"

        # ---- sanity + grounding
        warnings = list(attempt.warnings)
        null_cols = [c for c in res.columns if res.rows and all(r[c] is None for r in res.rows)]
        if res.rows == [] :
            warnings.append("the query returned no rows")
        for c in null_cols:
            warnings.append(f"column '{c}' is NULL for every row (e.g. no earlier period to compare against)")
        if res.truncated:
            warnings.append(f"result truncated to {self.s.max_rows} rows")

        neg = pos = False
        for e, sim in sims:
            if e.generated_logic and _norm(e.generated_logic) == _norm(attempt.plan.sql):
                neg |= e.rating < 0 and not e.corrected_logic
                pos |= e.rating > 0
        score, reasons = confidence.score(confidence.ConfidenceInputs(
            p_primary=attempt.plan.self_confidence, p_verifier=p_ver, agreement=agreement,
            ungrounded_literals=sum("not a known value" in w for w in warnings),
            repairs=attempt.repairs, empty_result=res.rows == [], null_columns=len(null_cols),
            truncated=res.truncated, feedback_negative=neg, feedback_positive=pos))
        if attempt.plan.unresolved:
            reasons.append(f"{len(attempt.plan.unresolved)} word(s) in the question could not be mapped")
        mode_note = "" if self.llm else "Note: no LLM was available, so only the deterministic planner was used (set ANTHROPIC_API_KEY to enable GenAI planning)."
        expl = explainer.build(query, attempt, mode_note=mode_note, verifier_note=verifier_note,
                               conf_reasons=reasons, warnings=warnings)
        meta.update(repairs=attempt.repairs, warnings=warnings, data_warnings=self.data_warnings,
                    assumptions=attempt.plan.assumptions, rows=len(res.rows),
                    explain=explainer.query_context(attempt.plan, attempt.plan.sql))
        meta["confidence_breakdown"] = _confidence_breakdown(
            score, attempt.plan, warnings, sql_validated=bool(attempt.plan.sql),
            execution_completed=attempt.result is not None, rows=len(res.rows),
            null_columns=len(null_cols), truncated=res.truncated, repairs=attempt.repairs)
        meta["clarification_suggestions"] = _clarification_suggestions(
            query, score, attempt.plan, warnings, None, list(self.sem.metrics))
        return self._out(query, attempt.plan.sql, res.rows, score, expl, meta, verbose)

    def feedback_on(self, query: str, sql: str, rating: int, corrected: str = "", comment: str = "") -> None:
        self.feedback.record(query, sql, rating, corrected, comment)

    # ------------------------------------------------------------------------------ internals
    def _primary(self, query: str, sims, timings: dict[str, int]) -> tuple[Attempt | None, str]:
        # 1) reuse a human-corrected query for a near-identical question
        for e, sim in sims:
            if e.corrected_logic and sim >= self.s.feedback_reuse_threshold:
                a = self._run(Plan(e.corrected_logic, f"Reused corrected logic from feedback (similarity {sim:.2f}) for: '{e.query}'",
                                   "feedback", self_confidence=0.9), timings=timings)
                if a.result is not None:
                    return a, ""
        # 2) GenAI planner with self-repair
        failure = ""
        if self.llm and self.mode in ("auto", "llm"):
            examples = [(e.query, e.good_sql) for e, _ in sims if e.good_sql][:3]
            prev: tuple[str, str] | None = None
            for attempt_no in range(self.s.llm_max_repairs + 1):
                try:
                    plan = _measure(timings, "interpretation_and_sql_generation",
                                    self.llm.plan, query, examples, prev)
                except Unsupported as u:
                    failure = f"The model reported the question cannot be answered from this data: {u}."
                    return None, failure
                except Exception as ex:                        # network/API failure -> degrade gracefully
                    log.warning("LLM planner failed: %s", ex)
                    failure = f"LLM unavailable ({type(ex).__name__}); fell back to rules."
                    break
                a = self._run(plan, repairs=attempt_no, timings=timings)
                if a.result is not None:
                    return a, ""
                prev = (plan.sql, a.error or "")
                failure = f"LLM SQL failed validation after {attempt_no + 1} attempt(s): {a.error}."
            if self.mode == "llm":
                return None, failure
        # 3) deterministic planner
        try:
            plan = _measure(timings, "interpretation_and_sql_generation", self.rules.plan, query)
        except Unsupported as u:
            return None, f"{failure} Could not interpret the question: {u}.".strip()
        a = self._run(plan, timings=timings)
        if a.result is None:
            return None, f"Generated SQL failed: {a.error}"
        if failure:
            a.warnings.append(failure)
        return a, ""

    def _run(self, plan: Plan, repairs: int = 0,
             timings: dict[str, int] | None = None) -> Attempt:
        a = Attempt(plan=plan, repairs=repairs)
        timings = timings if timings is not None else {stage: 0 for stage in _PERFORMANCE_STAGES}
        try:
            a.result = self.db.execute(plan.sql, timings=timings)
            validation_started = time.perf_counter_ns()
            try:
                plan.sql = self.db.check_statement(plan.sql)
                a.warnings += check_literals(plan.sql, self.sem.value_index)
            finally:
                timings["sql_validation"] += time.perf_counter_ns() - validation_started
        except QueryError as e:
            a.error = str(e)
        return a

    def _try(self, fn, query: str, timings: dict[str, int] | None = None) -> Attempt | None:
        try:
            plan = _measure(timings, "interpretation_and_sql_generation", fn, query) if timings is not None else fn(query)
            return self._run(plan, timings=timings)
        except Unsupported:
            return None

    @staticmethod
    def _out(query, sql, rows, score, expl, meta, verbose) -> dict[str, Any]:
        out = {"query": query, "generated_logic": sql, "result": rows,
               "confidence_score": score, "explanation": expl}
        if verbose:
            out["metadata"] = meta
        return out


def _norm(sql: str) -> str:
    return " ".join(sql.lower().replace(";", "").split())


def _row_bag(r: dict) -> Counter:
    bag: Counter = Counter()
    for v in r.values():
        bag[f"{round(v, 1):.1f}" if isinstance(v, float) else str(v)] += 1
    return bag


def _agree(a: ExecResult, b: ExecResult) -> bool:
    """Row-for-row agreement ignoring column names/order; the narrower result may be a projection
    of the wider one (e.g. an extra helper column)."""
    if len(a.rows) != len(b.rows):
        return False
    small, large = (a, b) if len(a.columns) <= len(b.columns) else (b, a)
    pool = [_row_bag(r) for r in large.rows]
    for r in small.rows:
        bag = _row_bag(r)
        for i, cand in enumerate(pool):
            if not (bag - cand):
                pool.pop(i)
                break
        else:
            return False
    return True
