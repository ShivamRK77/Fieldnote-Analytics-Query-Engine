"""Deterministic NL -> SQL planner (grammar over the semantic layer).

It plays two roles: (1) offline fallback when no LLM is reachable, and (2) an independent
second opinion used to cross-check LLM output (agreement raises confidence).

Nothing is keyed on specific queries. Every phrase is resolved through the semantic layer
(metrics, dimensions, synonyms, real data values, time grammar); anything it cannot explain
is reported back as `unresolved`, which lowers confidence.
"""
from __future__ import annotations
import re
from datetime import date

from aqe.models import Plan, Unsupported
from aqe.planning.parsed import ParsedQuery
from aqe.planning.sql_compiler import SQLCompiler
from aqe.semantic import time_resolver
from aqe.semantic.layer import SemanticLayer

TOKEN = re.compile(r"[a-z0-9_]+")
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
RANK_DESC = {"top", "best", "highest", "most", "largest", "biggest", "greatest", "leading", "maximum", "max"}
RANK_ASC = {"bottom", "worst", "lowest", "least", "smallest", "fewest", "minimum", "min", "weakest"}
MISSED = {"missed", "miss", "misses", "missing", "failed", "underperformed", "underperform", "short", "below"}
MET = {"met", "hit", "exceeded", "exceed", "achieved", "beat", "surpassed", "reached", "achieve"}
GROWTH = {"growth", "grow", "grew", "yoy", "mom", "qoq", "increase", "change"}
CONTRIB = {"contribution", "contributions", "share", "proportion", "contribute", "contributed", "percent", "pct", "percentage"}
STOP = set("""a an the in for of to by per each every across within wise is are was were be been being show me give list get find
tell what which who whom whose how much many total overall all and or with from than has have had its their our my did does do
vs versus compare compared there that this those these at on as it i we you please can could would should over under above below
more less greater higher lower exceeding least numbers number count sum average avg mean amount value values data report
generate display whats between if when where into onto against relative respective""".split())
TIME_WORDS = set(time_resolver.MONTHS) | set(time_resolver.ABBR) | {"last", "previous", "prior", "past", "this", "current",
                                                                    "month", "quarter", "year"}


def tokenize(text: str) -> list[str]:
    return TOKEN.findall(text.lower().replace("%", " percent "))


def stem(tok: str) -> str:
    return tok[:-1] if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss") else tok


class RulePlanner:
    name = "rules"

    def __init__(self, sem: SemanticLayer, as_of: date, data_years: list[int]):
        self.sem, self.as_of, self.years = sem, as_of, data_years
        self.compiler = SQLCompiler(sem)
        self.metric_phrases = sorted(((tuple(tokenize(a)), m) for a, m in sem.metric_aliases.items()), key=lambda x: -len(x[0]))
        self.dim_phrases = sorted(((tuple(tokenize(a)), d) for a, d in sem.dimension_aliases.items() if a != "by month"),
                                  key=lambda x: -len(x[0]))
        self.value_phrases = sorted(((tuple(stem(t) for t in tokenize(v)), col, val)
                                     for v, (col, val) in sem.lower_values.items()), key=lambda x: -len(x[0]))

    # ------------------------------------------------------------------------------------
    def plan(self, query: str) -> Plan:
        toks = tokenize(query)
        if not toks:
            raise Unsupported("empty query")
        if not self.years and (set(toks) & TIME_WORDS or re.search(r"\b(?:q[1-4]|20\d{2})\b", query.lower())):
            raise Unsupported("time analysis is unavailable because this dataset has no usable date values")
        used = [False] * len(toks)
        grounded: dict[str, str] = {}
        assumptions: list[str] = []
        pq = ParsedQuery()

        def find(phrases, kind):
            hits = []
            for ph, *rest in phrases:
                L = len(ph)
                for i in range(len(toks) - L + 1):
                    if not any(used[i:i + L]) and tuple(toks[i:i + L] if kind != "value" else (stem(t) for t in toks[i:i + L])) == ph:
                        for k in range(i, i + L):
                            used[k] = True
                        hits.append((i, L, *rest))
            return sorted(hits)

        # 1. metrics
        for i, L, metric in find(self.metric_phrases, "metric"):
            if metric not in pq.metrics:
                pq.metrics.append(metric)
            grounded[" ".join(toks[i:i + L])] = f"metric:{metric}"

        # 2. dimensions with their syntactic role
        dim_hits = find(self.dim_phrases, "dim")
        roles = []
        for i, L, dim in dim_hits:
            prev = toks[max(0, i - 3):i]
            nxt = toks[i + L:i + L + 1]
            word = toks[i + L - 1]
            if prev and (prev[-1] in {"by", "per", "each", "every", "across", "within", "into"} or nxt == ["wise"]):
                role = "group"
            elif any(p in RANK_DESC | RANK_ASC for p in prev) and not (prev and prev[-1] in {"by", "per", "each"}):
                role = "rank"
            elif prev and prev[-1] in {"which", "what"}:
                role = "which"
            elif dim in ("month", "quarter", "year") and prev and prev[-1] in {"by", "per", "each"}:
                role = "group"
            elif prev and prev[-1] in {"and", "&"} and roles and roles[-1][3] == "group" and roles[-1][0] + roles[-1][1] == i - 1:
                role = "group"
            else:
                role = "mention"
            roles.append((i, L, dim, role, word))
            grounded[" ".join(toks[i:i + L])] = f"dimension:{dim}"
            if nxt == ["wise"]:
                used[i + L] = True

        for i, L, dim, role, word in roles:
            if role == "mention":
                assumptions.append(f"dimension '{word}' was mentioned but not used for grouping/ranking")
        # 3. time (before values so month names are not treated as entities)
        tf = time_resolver.resolve(" ".join(toks), self.as_of, self.years)
        if tf:
            pq.time = tf
            if tf.assumption:
                assumptions.append(tf.assumption)
            for k, t in enumerate(toks):
                if t in TIME_WORDS or re.fullmatch(r"q[1-4]|20\d\d", t):
                    used[k] = True
            grounded["time"] = f"{tf.column}:{','.join(tf.values)}"
        for k, t in enumerate(toks):
            if t in {"monthly", "quarterly", "yearly", "annual", "annually", "trend", "trends"}:
                used[k] = True
                col = {"monthly": "month", "quarterly": "quarter", "yearly": "year", "annual": "year", "annually": "year"}.get(t, "month")
                roles.append((k, 1, col, "group", t))
                grounded[t] = f"dimension:{col}"

        # 4. entity filters
        by_col: dict[str, list[str]] = {}
        negated: dict[str, bool] = {}
        for i, L, col, val in find(self.value_phrases, "value"):
            by_col.setdefault(col, [])
            if val not in by_col[col]:
                by_col[col].append(val)
            before = toks[max(0, i - 2):i]
            if any(w in before for w in ("excluding", "except", "without", "not")) or before[-2:] == ["other", "than"]:
                negated[col] = True
                for k in range(max(0, i - 2), i):
                    if toks[k] in {"excluding", "except", "without", "not", "other", "than"}:
                        used[k] = True
            grounded[" ".join(toks[i:i + L])] = f"value:{col}={val}"
        for col, vals in by_col.items():
            pq.filters.append((col, vals, negated.get(col, False)))

        # 5. intent keywords
        tset = set(toks)
        n_val = None
        for k, t in enumerate(toks):
            if t.isdigit() and not re.fullmatch(r"20\d\d", t) and k > 0 and toks[k - 1] in RANK_DESC | RANK_ASC | {"first", "last"}:
                n_val = int(t); used[k] = True
            elif t in NUMBER_WORDS and k > 0 and toks[k - 1] in RANK_DESC | RANK_ASC:
                n_val = NUMBER_WORDS[t]; used[k] = True
        rank_word = next((t for t in toks if t in RANK_DESC | RANK_ASC), None)
        pq.ascending = rank_word in RANK_ASC if rank_word else False
        is_target = bool(re.search(r"\btargets?\b", " ".join(toks)))
        status = "missed" if tset & MISSED else ("met" if tset & MET else None)
        is_growth = bool(tset & GROWTH)
        is_contrib = bool(tset & CONTRIB)
        for k, t in enumerate(toks):
            if t in RANK_DESC | RANK_ASC | MISSED | MET | GROWTH | CONTRIB | {"target", "targets", "first"}:
                used[k] = True

        # having (numeric threshold)
        hv = re.search(r"\b(more than|greater than|above|over|higher than|exceeding|at least|less than|below|under|lower than)\s+\$?(\d[\d,]*(?:\.\d+)?)", query.lower())
        if hv and not (tf and tf.column == "year" and re.fullmatch(r"20\d\d", hv.group(2))):
            word = hv.group(1)
            op = ">=" if word == "at least" else ">" if word in {"more than", "greater than", "above", "over", "higher than", "exceeding"} else "<"
            pq.having = (op, float(hv.group(2).replace(",", "")))
            for k, t in enumerate(toks):
                if t == hv.group(2).replace(",", "") or t in {"more", "greater", "higher", "than", "above", "over", "exceeding", "at", "least", "less", "below", "under", "lower"}:
                    used[k] = True

        group = [d for _, _, d, r, _ in roles if r == "group"]
        rank_dims = [(d, w) for _, _, d, r, w in roles if r == "rank"]
        which = [d for _, _, d, r, _ in roles if r == "which"]

        # 6. decide intent
        if is_target and (status or not is_growth):
            pq.intent = "target"
            pq.target_status = status
            if pq.metrics and pq.metrics != ["revenue"]:
                raise Unsupported("targets exist for revenue only")
            if not pq.metrics:
                pq.metrics = ["revenue"]
            pq.group_by = [g for g in dict.fromkeys(group) if g == "month"]
            others = [d for d in dict.fromkeys(group + which) if d not in ("region", "month")]
            if others:
                raise Unsupported(f"targets are defined per region and month only, not per {others[0]}")
            if any(c != "region" for c, _, _ in pq.filters):
                assumptions.append("non-region filters apply to actual revenue only; targets are region-wide")
        elif is_growth and (pq.metrics or "yoy" in tset or "mom" in tset):
            pq.intent = "growth"
            if not pq.metrics:
                pq.metrics = ["revenue"]; assumptions.append("no metric named; defaulted to revenue")
            if "mom" in tset or "month" in toks and ("over" in toks and toks.count("month") > 1):
                pq.growth_kind, pq.growth_grain = "prev", "month"
            elif "qoq" in tset:
                pq.growth_kind, pq.growth_grain = "prev", "quarter"
            else:
                pq.growth_kind = "yoy"
                pq.growth_grain = pq.time.column if pq.time else next((g for g in group if g in ("month", "quarter")), "year")
            pq.group_by = list(dict.fromkeys(group + which))
        elif rank_word and (rank_dims or which or group):
            pq.intent = "rank"
            pq.rank_dim = rank_dims[0][0] if rank_dims else (which[0] if which else group[0])
            pq.partition = [d for d in dict.fromkeys(group) if d != pq.rank_dim]
            word = rank_dims[0][1] if rank_dims else ""
            if n_val:
                pq.n = n_val
            elif rank_word in {"highest", "lowest", "most", "least", "maximum", "minimum", "max", "min"} or not word.endswith("s"):
                pq.n = 1
            else:
                pq.n = 5; assumptions.append("'top' without a number: defaulted to 5")
            if not pq.metrics:
                pq.metrics = ["revenue"]; assumptions.append("no metric named; ranked by revenue (sales)")
        elif is_contrib and (group or which or rank_dims):
            pq.intent = "contribution"
            pq.group_by = list(dict.fromkeys(group + which + [d for d, _ in rank_dims]))
            if not pq.metrics:
                pq.metrics = ["revenue"]; assumptions.append("no metric named; contribution of revenue")
        else:
            pq.intent = "aggregate"
            pq.group_by = list(dict.fromkeys(group + which))
            if not pq.metrics:
                raise Unsupported("no recognisable metric (e.g. revenue, profit, orders, average order value)")
            if tset & {"average", "avg", "mean"} and len(pq.metrics) == 1 and self.sem.metrics[pq.metrics[0]].additive and \
                    pq.metrics[0] not in ("orders",):
                pq.avg_of_rows = True
                assumptions.append(f"'average {pq.metrics[0]}' read as the mean per order line")
        if pq.intent in ("rank", "aggregate") and len(set(f[0] for f in pq.filters)) and len(by_col) and \
                re.search(r"\b(compare|vs|versus)\b", " ".join(toks)):
            for col, vals, neg in pq.filters:
                if len(vals) > 1 and col not in pq.group_by and pq.intent == "aggregate":
                    pq.group_by.append(col)

        sql = self.compiler.compile(pq)

        # 7. explain what is understood / unexplained
        for k, t in enumerate(toks):
            if t in STOP or t.isdigit() and used[k]:
                used[k] = True
        unresolved = [t for k, t in enumerate(toks) if not used[k] and t not in STOP and not t.isdigit()]
        proper = {w.lower() for w in re.findall(r"\b[A-Za-z][A-Za-z0-9_]*\b", query)[1:] if w[0].isupper()}
        unknown_entities = [u for u in unresolved if u in proper]
        if unknown_entities:
            raise Unsupported(f"'{unknown_entities[0]}' is not a value in the data (checked every categorical column) "
                              f"and not a known metric/dimension; refusing to silently drop it")
        conf = 0.92 - 0.08 * len(assumptions) - 0.3 * len(unresolved)
        return Plan(sql=sql, interpretation=self._describe(pq), planner="rules", assumptions=assumptions,
                    self_confidence=max(0.05, min(0.95, conf)), grounded_terms=grounded, unresolved=unresolved)

    # ------------------------------------------------------------------------------------
    def _describe(self, pq: ParsedQuery) -> str:
        flt = "; ".join(f"{c} {'not in' if n else 'in'} {v}" for c, v, n in pq.filters)
        t = f"; period {pq.time.description}" if pq.time else ""
        flt = (f" filtered to {flt}" if flt else "") + t
        m = ", ".join(pq.metrics)
        if pq.intent == "rank":
            part = f" within each {', '.join(pq.partition)}" if pq.partition else ""
            return f"Rank {pq.rank_dim} by {m} ({'lowest' if pq.ascending else 'highest'} first), keep the {'bottom' if pq.ascending else 'top'} {pq.n}{part}{flt}"
        if pq.intent == "contribution":
            return f"Share (%) of total {m} contributed by each {', '.join(pq.group_by)}{flt}"
        if pq.intent == "target":
            st = {"missed": "which fell short of", "met": "which reached"}.get(pq.target_status or "", "compared with")
            return f"Actual revenue vs target per region ({st} target){flt}"
        if pq.intent == "growth":
            kind = "year-over-year" if pq.growth_kind == "yoy" else "period-over-period"
            return f"{kind.capitalize()} growth of {m} by {pq.growth_grain}{flt}"
        g = f" grouped by {', '.join(pq.group_by)}" if pq.group_by else ""
        what = f"average per order line of {m}" if pq.avg_of_rows else m
        return f"Aggregate {what}{g}{flt}"
