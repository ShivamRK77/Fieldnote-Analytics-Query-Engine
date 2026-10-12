"""Deterministic ParsedQuery -> SQLite SQL. All metric expressions come from the semantic layer."""
from __future__ import annotations
import re
from aqe.models import Unsupported
from aqe.planning.parsed import ParsedQuery
from aqe.semantic.layer import SemanticLayer
from aqe.semantic.time_resolver import TimeFilter

OPS = {">": ">", ">=": ">=", "<": "<", "<=": "<="}


def q(v: str) -> str:
    return "'" + v.replace("'", "''") + "'"


def month_cond(tf: TimeFilter, col: str = "month") -> str:
    """Express a time filter against a 'YYYY-MM' column (used for the targets table)."""
    if tf.column == "month":
        return f"{col} IN ({', '.join(q(v) for v in tf.values)})"
    if tf.column == "year":
        return " OR ".join(f"substr({col},1,4) = {q(v)}" for v in tf.values).join(["(", ")"])
    parts = []
    for v in tf.values:
        y, qn = v.split("-Q")
        months = [f"{y}-{(int(qn) - 1) * 3 + k:02d}" for k in (1, 2, 3)]
        parts.append(f"{col} IN ({', '.join(q(m) for m in months)})")
    return "(" + " OR ".join(parts) + ")"


class SQLCompiler:
    def __init__(self, sem: SemanticLayer):
        self.sem = sem

    # ------------------------------------------------------------------ helpers
    def _agg(self, name: str, avg_rows: bool = False) -> str:
        m = self.sem.metrics[name]
        sql = m.agg_sql
        if avg_rows and sql.upper().startswith("SUM("):
            sql = "AVG(" + sql[4:]
        return sql

    def _where(self, pq: ParsedQuery, skip_cols: set[str] = frozenset(), with_time: bool = True) -> str:
        conds = []
        for col, vals, neg in pq.filters:
            if col in skip_cols:
                continue
            if len(vals) == 1:
                conds.append(f"{col} {'!=' if neg else '='} {q(vals[0])}")
            else:
                conds.append(f"{col} {'NOT IN' if neg else 'IN'} ({', '.join(q(v) for v in vals)})")
        if with_time and pq.time:
            conds.append(pq.time.sql())
        return ("WHERE " + " AND ".join(conds)) if conds else ""

    def _select_metric(self, name: str, avg_rows: bool = False) -> str:
        agg = self._agg(name, avg_rows)
        return f"{agg} AS {name}" if agg.startswith("COUNT(") else f"ROUND({agg}, 2) AS {name}"

    # ------------------------------------------------------------------ entry
    def compile(self, pq: ParsedQuery) -> str:
        return getattr(self, f"_{pq.intent}")(pq)

    # ------------------------------------------------------------------ aggregate
    def _aggregate(self, pq: ParsedQuery) -> str:
        sel = list(pq.group_by)
        sel += [self._select_metric(m, pq.avg_of_rows) for m in pq.metrics]
        sql = f"SELECT {', '.join(sel)}\nFROM sales\n{self._where(pq)}".rstrip()
        if pq.group_by:
            sql += f"\nGROUP BY {', '.join(pq.group_by)}"
        if pq.having:
            op, val = pq.having
            sql += f"\nHAVING {self._agg(pq.metrics[0], pq.avg_of_rows)} {OPS[op]} {val}"
        if pq.group_by:
            time_dims = [g for g in pq.group_by if g in ("month", "quarter", "year")]
            order = time_dims or [f"{pq.metrics[0]} DESC"]
            sql += f"\nORDER BY {', '.join(order)}"
        return sql

    # ------------------------------------------------------------------ rank
    def _rank(self, pq: ParsedQuery) -> str:
        m, dim, n = pq.metrics[0], pq.rank_dim, pq.n or 1
        direction = "ASC" if pq.ascending else "DESC"
        where = self._where(pq)
        having = ""
        if pq.having:
            op, val = pq.having
            having = f"\nHAVING {self._agg(m)} {OPS[op]} {val}"
        if not pq.partition:
            return (f"SELECT {dim}, {self._select_metric(m)}\nFROM sales\n{where}\n"
                    f"GROUP BY {dim}{having}\nORDER BY {m} {direction}, {dim}\nLIMIT {n}").replace("\n\n", "\n")
        part = ", ".join(pq.partition)
        extra = f",\n       ROUND(SUM(value) OVER (PARTITION BY {part}), 2) AS top_{n}_total_{m}" \
            if (self.sem.metrics[m].additive and n > 1) else ""
        cte_having = having.replace("\nHAVING", "\n  HAVING")
        cte = (f"WITH g AS (\n  SELECT {part}, {dim}, {self._agg(m)} AS value\n  FROM sales\n  {where}\n"
               f"  GROUP BY {part}, {dim}{cte_having}\n),\n")
        return (cte + f"r AS (\n  SELECT *, RANK() OVER (PARTITION BY {part} ORDER BY value {direction}) AS rnk FROM g\n)\n"
            f"SELECT {part}, {dim}, ROUND(value, 2) AS {m}, rnk AS rank{extra}\n"
            f"FROM r\nWHERE rnk <= {n}\nORDER BY {part}, rnk, {dim}").replace("\n  \n", "\n")

    # ------------------------------------------------------------------ contribution
    def _contribution(self, pq: ParsedQuery) -> str:
        m = pq.metrics[0]
        if not self.sem.metrics[m].additive:
            raise Unsupported(f"'{m}' is a ratio; its share of a total is not meaningful")
        dims = ", ".join(pq.group_by)
        return (f"SELECT {dims}, ROUND({self._agg(m)}, 2) AS {m},\n"
                f"       ROUND(100.0 * {self._agg(m)} / SUM({self._agg(m)}) OVER (), 2) AS contribution_pct\n"
                f"FROM sales\n{self._where(pq)}\nGROUP BY {dims}\nORDER BY contribution_pct DESC").replace("\n\n", "\n")

    # ------------------------------------------------------------------ targets
    def _target(self, pq: ParsedQuery) -> str:
        by_month = "month" in pq.group_by
        keys = ["region"] + (["month"] if by_month else [])
        sel_keys = ", ".join(f"tgt.{k}" for k in keys)
        tcond = []
        for col, vals, neg in pq.filters:
            if col == "region":
                tcond.append(f"region {'NOT IN' if neg else 'IN'} ({', '.join(q(v) for v in vals)})")
        if pq.time:
            tcond.append(month_cond(pq.time))
        twhere = ("WHERE " + " AND ".join(tcond)) if tcond else ""
        awhere = self._where(pq)
        actual = "COALESCE(SUM(act.actual), 0)"
        target = "SUM(tgt.target_revenue)"
        having = ""
        if pq.target_status == "missed":
            having = f"\nHAVING {actual} < {target}"
        elif pq.target_status == "met":
            having = f"\nHAVING {actual} >= {target}"
        return (f"WITH tgt AS (\n  SELECT region, month, target_revenue FROM targets {twhere}\n),\n"
                f"act AS (\n  SELECT region, month, SUM(revenue) AS actual FROM sales {awhere}\n  GROUP BY region, month\n)\n"
                f"SELECT {sel_keys},\n"
                f"       ROUND({actual}, 2) AS actual_revenue,\n"
                f"       ROUND({target}, 2) AS target_revenue,\n"
                f"       ROUND({actual} - {target}, 2) AS variance,\n"
                f"       ROUND(100.0 * {actual} / NULLIF({target}, 0), 2) AS attainment_pct,\n"
                f"       CASE WHEN {actual} >= {target} THEN 'met' ELSE 'missed' END AS status\n"
                f"FROM tgt LEFT JOIN act ON act.region = tgt.region AND act.month = tgt.month\n"
                f"GROUP BY {sel_keys}{having}\nORDER BY {sel_keys}").replace("\n\n", "\n")

    # ------------------------------------------------------------------ growth
    def _growth(self, pq: ParsedQuery) -> str:
        m, g = pq.metrics[0], pq.growth_grain
        part = [d for d in pq.group_by if d not in ("month", "quarter", "year")]
        pcols = ", ".join(part)
        sel_p = (pcols + ", ") if part else ""
        where = self._where(pq, with_time=False)
        base = (f"WITH p AS (\n  SELECT {sel_p}{g} AS period, {self._agg(m)} AS value\n  FROM sales\n  {where}\n  GROUP BY {sel_p}{g}\n)")
        tf = f"\nWHERE {pq.time.sql().replace(pq.time.column, 'cur.period', 1) if pq.time and pq.time.column == g else '1=1'}"
        if pq.growth_kind == "yoy":
            if g == "year":
                prev = "CAST(cur.period AS INTEGER) - 1"
            else:
                prev = "(CAST(substr(cur.period, 1, 4) AS INTEGER) - 1) || substr(cur.period, 5)"
            join = " AND ".join([f"prev.{c} = cur.{c}" for c in part] + [f"prev.period = {prev}"])
            return (f"{base}\nSELECT {', '.join('cur.' + c for c in part) + ', ' if part else ''}cur.period,\n"
                    f"       ROUND(cur.value, 2) AS {m}, ROUND(prev.value, 2) AS previous_year_{m},\n"
                    f"       ROUND(100.0 * (cur.value - prev.value) / NULLIF(prev.value, 0), 2) AS yoy_growth_pct\n"
                    f"FROM p cur LEFT JOIN p prev ON {join}{tf}\nORDER BY {', '.join('cur.' + c for c in part) + ', ' if part else ''}cur.period")
        win = f"PARTITION BY {pcols} ORDER BY period" if part else "ORDER BY period"
        return (f"{base},\nl AS (SELECT *, LAG(value) OVER ({win}) AS prev_value FROM p)\n"
                f"SELECT {sel_p}period, ROUND(value, 2) AS {m}, ROUND(prev_value, 2) AS previous_period_{m},\n"
                f"       ROUND(100.0 * (value - prev_value) / NULLIF(prev_value, 0), 2) AS growth_pct\n"
                f"FROM l{tf.replace('cur.period', 'period')}\nORDER BY {sel_p}period")
