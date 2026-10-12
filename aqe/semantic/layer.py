"""Semantic layer: business vocabulary -> SQL, built dynamically from data_dictionary.json,
the live schema and an optional overrides file. Nothing here is specific to any query."""
from __future__ import annotations
import json
import re
from dataclasses import dataclass
from pathlib import Path

from aqe.execution.database import Database

TIME_DIMS = ["month", "quarter", "year"]
_AGG = re.compile(r"\b(sum|count|avg|min|max)\s*\(", re.I)
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def plural_forms(word: str) -> set[str]:
    forms = {word}
    if word.endswith("y") and not word.endswith(("ay", "ey", "oy", "uy")):
        forms.add(word[:-1] + "ies")
    forms.add(word + "s")
    if word.endswith(("s", "x", "ch", "sh")):
        forms.add(word + "es")
    return forms


@dataclass
class Metric:
    name: str
    agg_sql: str           # aggregate expression usable in SELECT
    additive: bool         # may be summed across groups (needed for % contribution)
    source: str


class SemanticLayer:
    def __init__(self, dictionary: dict, db: Database, overrides: dict | None = None):
        overrides = overrides or {}
        self.dictionary = dictionary
        self.time_mappings: dict[str, str] = dictionary.get("time_mappings", {})
        self.metrics: dict[str, Metric] = {}
        self.metric_aliases: dict[str, str] = {}
        self.dimensions: list[str] = []
        self.dimension_aliases: dict[str, str] = {}
        self.value_index: dict[str, set[str]] = {}       # column -> real values
        self.lower_values: dict[str, tuple[str, str]] = {}  # lowercase value -> (column, value)
        self._build_metrics(dictionary.get("metrics", {}), overrides.get("extra_metrics", {}))
        self._build_dimensions(dictionary.get("dimensions", []), db, overrides.get("dimension_aliases", {}),
                       overrides.get("non_dimension_columns", []))
        self._build_aliases(dictionary.get("synonyms", {}), overrides.get("metric_aliases", {}))
        self._build_values(db)
        lo, hi = db.date_range()
        self.data_min_date, self.data_max_date = lo, hi

    # ---- metrics ------------------------------------------------------------------
    def _build_metrics(self, defs: dict[str, str], extra: dict[str, str]) -> None:
        pending = dict(defs)
        # two passes so composite metrics (revenue / orders) can reference base ones
        for _ in range(3):
            for name, expr in list(pending.items()):
                refs = {t for t in _IDENT.findall(expr) if t in pending and t != name}
                if refs - set(self.metrics):
                    continue
                self.metrics[name] = self._compile_metric(name, expr)
                pending.pop(name)
        for name, expr in pending.items():          # unresolved composites: best effort
            self.metrics[name] = self._compile_metric(name, expr)
        for name, expr in extra.items():
            self.metrics.setdefault(name, Metric(name, expr, True, "overrides"))

    def _compile_metric(self, name: str, expr: str) -> Metric:
        e = expr.strip()
        refs = [t for t in _IDENT.findall(e) if t in self.metrics and t != name]
        if refs and not _AGG.search(e):             # composite: substitute metric names
            def sub(m):
                before = e[: m.start()].rstrip()
                inner = f"({self.metrics[m.group(0)].agg_sql})"
                return f"NULLIF({inner}, 0)" if before.endswith("/") else inner
            out = _IDENT.sub(lambda m: sub(m) if m.group(0) in self.metrics else m.group(0), e)
            return Metric(name, f"1.0 * {out}", False, "dictionary")
        if _AGG.search(e):
            e = re.sub(r"\b(sum|count|avg|min|max)\s*\(", lambda m: m.group(1).upper() + "(", e, flags=re.I)
            return Metric(name, e, e.startswith("COUNT"), "dictionary")
        return Metric(name, f"SUM({e})", True, "dictionary")

    # ---- dimensions -----------------------------------------------------------------
    def _build_dimensions(self, dims: list[str], db: Database, overrides: dict[str, str],
                          non_dimensions: list[str]) -> None:
        cols = db.columns("sales_raw")
        numeric = {"quantity", "unit_price", "discount", "shipping_cost", "profit"}
        excluded = numeric | set(non_dimensions)
        derived = [c for c in cols if c not in excluded and c not in ("order_id", "order_date")]
        self.dimensions = list(dict.fromkeys(list(dims) + derived + TIME_DIMS))
        for d in self.dimensions:
            words = d.replace("_", " ")
            for form in plural_forms(words):
                self.dimension_aliases[form] = d
            # short form: product_category -> "category"
            if "_" in d:
                last = d.split("_")[-1]
                for form in plural_forms(last):
                    self.dimension_aliases.setdefault(form, d)
        self.dimension_aliases.update(overrides)
        self.dimension_aliases["by month"] = "month"

    # ---- aliases ----------------------------------------------------------------------
    def _build_aliases(self, synonyms: dict[str, str], overrides: dict[str, str]) -> None:
        for name in self.metrics:
            for form in plural_forms(name.replace("_", " ")):
                self.metric_aliases[form] = name
        for term, target in {**synonyms, **overrides}.items():
            t = target.strip().lower()
            if target in self.metrics:
                self.metric_aliases[term.lower()] = target
            elif t in self.metrics:
                self.metric_aliases[term.lower()] = t
            # synonyms whose value is raw SQL (e.g. orders -> count(order_id)) are already
            # covered by the metric of the same name.

    # ---- value index ----------------------------------------------------------------------
    def _build_values(self, db: Database) -> None:
        for d in self.dimensions:
            if d in ("customer_id",):
                pass
            try:
                vals = [str(v) for v in db.distinct("sales", d) if str(v).strip()]
            except Exception:
                continue
            self.value_index[d] = set(vals)
            if d in TIME_DIMS:
                continue
            for v in vals:
                self.lower_values.setdefault(v.lower(), (d, v))
        self.value_index["region"] = self.value_index.get("region", set()) | set(
            str(v) for v in db.distinct("targets", "region"))
        self.value_index["month"] = self.value_index.get("month", set()) | set(
            str(v) for v in db.distinct("targets", "month"))

    # ---- prompt context ----------------------------------------------------------------------
    def describe(self, max_values: int = 50) -> str:
        lines = ["TABLE sales (one row per order line; view):"]
        for d in self.dimensions:
            vals = sorted(self.value_index.get(d, []))
            shown = ", ".join(vals[:max_values]) + (" ..." if len(vals) > max_values else "")
            lines.append(f"  - {d}: values = [{shown}]")
        lines.append("  - order_id, order_date (YYYY-MM-DD text), quantity, unit_price, discount (0-1), shipping_cost, profit (numeric)")
        lines.append("  - revenue = quantity * unit_price * (1 - discount)  [derived column, already in the view]")
        lines.append("TABLE targets (region, month 'YYYY-MM', target_revenue)  -- monthly REVENUE targets per region")
        lines.append("METRICS (use these exact aggregate expressions):")
        for m in self.metrics.values():
            lines.append(f"  - {m.name}: {m.agg_sql}")
        lines.append("SYNONYMS: " + json.dumps({k: v for k, v in self.metric_aliases.items()}))
        lines.append("TIME PHRASES: " + json.dumps(self.time_mappings))
        return "\n".join(lines)


def load_overrides(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return {}
