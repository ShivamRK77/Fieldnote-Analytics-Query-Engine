"""In-memory SQLite store + sandboxed executor.

Tables exposed to generated SQL:
  sales(...)    view over the raw rows plus derived columns revenue, month, quarter, year
  targets(region, month, target_revenue)
SQLite >= 3.25 gives us window functions, which the 'top N per group' queries need.
Security: a SQLite authorizer allows only SELECT/READ on whitelisted tables, so even a
misbehaving LLM cannot write, attach, pragma or drop anything.
"""
from __future__ import annotations
import re
import sqlite3
import time
from typing import Any

import pandas as pd

from aqe.models import ExecResult

ALLOWED_TABLES = {"sales", "sales_raw", "targets"}
_OK_ACTIONS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}

SALES_VIEW = """
CREATE VIEW sales AS
SELECT *,
       quantity * unit_price * (1 - discount)                                  AS revenue,
       substr(order_date, 1, 7)                                                AS month,
       substr(order_date, 1, 4) || '-Q' ||
         ((CAST(substr(order_date, 6, 2) AS INTEGER) + 2) / 3)                 AS quarter,
       substr(order_date, 1, 4)                                                AS year
FROM sales_raw
"""


class QueryError(Exception):
    pass


def _strip_literals(sql: str) -> str:
    return re.sub(r"'(?:[^']|'')*'", "''", sql)


class Database:
    def __init__(self, sales: pd.DataFrame, targets: pd.DataFrame, max_rows: int = 1000):
        self.max_rows = max_rows
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        sales.astype(object).to_sql("sales_raw", self.conn, index=False)
        targets.astype(object).to_sql("targets", self.conn, index=False)
        self.conn.execute(SALES_VIEW)
        self.conn.commit()
        self.conn.set_authorizer(self._authorizer)
        self.conn.set_progress_handler(self._budget, 100_000)
        self._ops = 0

    # -- security -----------------------------------------------------------------
    @staticmethod
    def _authorizer(action, arg1, arg2, dbname, source):
        if action not in _OK_ACTIONS:
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_READ and arg1 not in ALLOWED_TABLES:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    def _budget(self):
        self._ops += 1
        return 1 if self._ops > 200 else 0      # abort runaway queries

    @staticmethod
    def check_statement(sql: str) -> str:
        sql = sql.strip().rstrip(";").strip()
        if not sql:
            raise QueryError("empty SQL")
        if ";" in _strip_literals(sql):
            raise QueryError("multiple statements are not allowed")
        if not re.match(r"(?is)^\s*(select|with)\b", sql):
            raise QueryError("only SELECT / WITH queries are allowed")
        return sql

    # -- execution ------------------------------------------------------------------
    def execute(self, sql: str, timings: dict[str, int] | None = None) -> ExecResult:
        timings = timings if timings is not None else {}
        validation_started = time.perf_counter_ns()
        sql = self.check_statement(sql)
        timings["sql_validation"] = timings.get("sql_validation", 0) + time.perf_counter_ns() - validation_started
        self._ops = 0
        validation_started = time.perf_counter_ns()
        try:
            self.conn.execute("EXPLAIN " + sql)           # catches syntax / unknown columns cheaply
        except sqlite3.Error as e:
            timings["sql_validation"] = timings.get("sql_validation", 0) + time.perf_counter_ns() - validation_started
            raise QueryError(str(e)) from e
        timings["sql_validation"] = timings.get("sql_validation", 0) + time.perf_counter_ns() - validation_started

        execution_started = time.perf_counter_ns()
        try:
            cur = self.conn.execute(sql)
            fetched = cur.fetchmany(self.max_rows + 1)
        except sqlite3.Error as e:
            timings["database_execution"] = timings.get("database_execution", 0) + time.perf_counter_ns() - execution_started
            raise QueryError(str(e)) from e
        timings["database_execution"] = timings.get("database_execution", 0) + time.perf_counter_ns() - execution_started
        cols = [d[0] for d in cur.description]
        truncated = len(fetched) > self.max_rows
        formatting_started = time.perf_counter_ns()
        rows = [{c: self._clean(v) for c, v in zip(cols, r)} for r in fetched[: self.max_rows]]
        timings["result_formatting"] = timings.get("result_formatting", 0) + time.perf_counter_ns() - formatting_started
        return ExecResult(columns=cols, rows=rows, truncated=truncated)

    @staticmethod
    def _clean(v: Any) -> Any:
        if isinstance(v, float):
            return round(v, 4)
        return v

    # -- introspection ----------------------------------------------------------------
    def distinct(self, table: str, column: str) -> list[Any]:
        return [r[0] for r in self.conn.execute(f"SELECT DISTINCT {column} FROM {table} WHERE {column} IS NOT NULL ORDER BY 1")]

    def columns(self, table: str) -> list[str]:
        return [d[0] for d in self.conn.execute(f"SELECT * FROM {table} LIMIT 0").description]

    def date_range(self) -> tuple[str, str]:
        return self.conn.execute("SELECT min(order_date), max(order_date) FROM sales_raw").fetchone()
