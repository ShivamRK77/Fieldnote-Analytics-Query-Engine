"""Deterministic, result-only business insights for displayed query rows."""
from __future__ import annotations

import math
import re
from numbers import Real
from typing import Any

_TIME_COLUMNS = {"date", "order_date", "month", "quarter", "year", "period"}
_HELPER_COLUMN = re.compile(r"^(?:rank|rnk|contribution_pct|attainment_pct|variance)$|^(?:previous_|prior_|top_\d+_total_)|(?:growth_pct|yoy_growth_pct)$", re.I)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _label(column: str) -> str:
    return column.replace("_", " ")


def _insight(text: str, severity: str, icon: str) -> dict[str, str]:
    return {"text": text, "severity": severity, "icon": icon, "source": "deterministic"}


def _time_column(rows: list[dict[str, Any]]) -> str | None:
    for column in rows[0]:
        if column.lower() not in _TIME_COLUMNS:
            continue
        values = [row.get(column) for row in rows]
        if all(isinstance(value, str) and value.strip() for value in values):
            return column
    return None


def _rank_change(rows: list[dict[str, Any]], time: str) -> dict[str, str] | None:
    columns = rows[0].keys()
    rank = next((column for column in columns if column.lower() in {"rank", "rnk"}), None)
    category = next((column for column in columns if column != time and column != rank and
                     all(isinstance(row.get(column), str) and row[column] for row in rows)), None)
    if not rank or not category:
        return None

    periods = sorted({row[time] for row in rows})
    if len(periods) < 2:
        return None
    first, last = periods[0], periods[-1]
    before = {row[category]: _number(row.get(rank)) for row in rows if row[time] == first}
    after = {row[category]: _number(row.get(rank)) for row in rows if row[time] == last}
    movements = [(name, before[name], after[name]) for name in before.keys() & after.keys()
                 if before[name] is not None and after[name] is not None and before[name] != after[name]]
    if not movements:
        return None
    name, old_rank, new_rank = max(movements, key=lambda item: (abs(item[1] - item[2]), item[2] < item[1], item[0]))
    direction = "moved up" if new_rank < old_rank else "moved down"
    severity = "positive" if new_rank < old_rank else "warning"
    return _insight(f"{name} {direction} from rank {old_rank:g} to rank {new_rank:g} between {first} and {last}.",
                    severity, "ranking")


def _time_change(rows: list[dict[str, Any]], time: str, metrics: list[str]) -> list[dict[str, str]]:
    ordered = sorted(rows, key=lambda row: row[time])
    first, last = ordered[0], ordered[-1]
    insights = []
    for metric in metrics[:2]:
        start, end = _number(first.get(metric)), _number(last.get(metric))
        if start is None or end is None or start == 0 or start == end:
            continue
        change = (end - start) / abs(start) * 100
        direction = "increased" if change > 0 else "declined"
        severity = "positive" if change > 0 else "warning"
        insights.append(_insight(
            f"{_label(metric).capitalize()} {direction} by {abs(change):.1f}% from {first[time]} to {last[time]}.",
            severity, "trend"))
    return insights


def _category_insights(rows: list[dict[str, Any]], category: str, metrics: list[str]) -> list[dict[str, str]]:
    insights = []
    share_column = next((column for column in rows[0] if column.lower() == "contribution_pct"), None)
    if share_column:
        share_rows = [(row, _number(row.get(share_column))) for row in rows]
        share_rows = [(row, value) for row, value in share_rows if value is not None and value >= 0]
        total_share = sum(value for _, value in share_rows)
        if share_rows and (abs(total_share - 100) <= 1 or abs(total_share - 1) <= 0.01):
            row, share = max(share_rows, key=lambda item: item[1])
            insights.append(_insight(f"{row[category]} contributed {share:.1f}% of the returned total.",
                                     "info", "share"))

    for metric in metrics[:1]:
        scored = [(row, _number(row.get(metric))) for row in rows]
        scored = [(row, value) for row, value in scored if value is not None]
        if len(scored) < 2:
            continue
        highest, second = sorted(scored, key=lambda item: item[1], reverse=True)[:2]
        high_name, high_value = highest[0][category], highest[1]
        second_name, second_value = second[0][category], second[1]
        metric_name = _label(metric)
        if high_value != second_value:
            insights.append(_insight(f"{high_name} had the highest displayed {metric_name} at {high_value:,.1f}.",
                                     "positive", "leader"))
            if high_value > 0 and 0 <= second_value < high_value:
                difference = (high_value - second_value) / high_value * 100
                insights.append(_insight(f"{second_name} generated {difference:.1f}% less {metric_name} than {high_name}.",
                                         "info", "difference"))

        if not share_column and all(value >= 0 for _, value in scored):
            total = sum(value for _, value in scored)
            if total > 0:
                share = high_value / total * 100
                insights.append(_insight(f"{high_name} accounted for {share:.1f}% of displayed {metric_name}.",
                                         "info", "share"))
        break
    return insights


def generate_insights(query: str, rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Return concise deterministic statements supported only by ``rows``."""
    if not isinstance(rows, list) or len(rows) < 2 or not isinstance(rows[0], dict):
        return []
    if any(not isinstance(row, dict) for row in rows):
        return []

    columns = list(rows[0])
    metrics = [column for column in columns if not _HELPER_COLUMN.search(column) and
               all(_number(row.get(column)) is not None for row in rows)]
    if not metrics:
        return []

    time = _time_column(rows)
    if time:
        ranking = _rank_change(rows, time)
        insights = [ranking] if ranking else []
        insights.extend(_time_change(rows, time, metrics))
    else:
        category = next((column for column in columns if column.lower() not in _TIME_COLUMNS and
                         column not in metrics and
                         all(isinstance(row.get(column), str) and row[column].strip() for row in rows)), None)
        insights = _category_insights(rows, category, metrics) if category else []

    return insights[:4]