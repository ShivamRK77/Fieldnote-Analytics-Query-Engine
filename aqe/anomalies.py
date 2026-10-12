"""Conservative, result-only statistical anomaly detection."""
from __future__ import annotations

import math
import re
from numbers import Real
from typing import Any

_MIN_SAMPLE_SIZE = 10
_MAX_FINDINGS = 5
_EXCLUDED_COLUMNS = {
    "date", "order_date", "month", "quarter", "year", "period",
    "id", "index", "rank", "rnk",
}
_HELPER_COLUMN = re.compile(
    r"^(?:rank|rnk|contribution_pct|attainment_pct|variance)$|"
    r"^(?:previous_|prior_|top_\d+_total_)|(?:growth_pct|yoy_growth_pct)$",
    re.I,
)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _quantile(values: list[float], probability: float) -> float:
    position = (len(values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    weight = position - lower
    return values[lower] * (1 - weight) + values[upper] * weight


def generate_anomalies(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Find strong IQR outliers in sufficiently large returned result columns."""
    if not isinstance(rows, list) or len(rows) < _MIN_SAMPLE_SIZE:
        return []
    if any(not isinstance(row, dict) for row in rows):
        return []

    candidates: list[tuple[float, dict[str, Any]]] = []
    for column in rows[0]:
        if not isinstance(column, str):
            continue
        normalized_column = column.lower()
        if (normalized_column in _EXCLUDED_COLUMNS or
                normalized_column.endswith(("_id", "_index", "_rank")) or
                _HELPER_COLUMN.search(column)):
            continue

        values = [(index, _number(row.get(column))) for index, row in enumerate(rows)]
        valid_values = [value for _, value in values if value is not None]
        if len(valid_values) < _MIN_SAMPLE_SIZE or len(set(valid_values)) < 5:
            continue

        ordered = sorted(valid_values)
        q1 = _quantile(ordered, 0.25)
        q3 = _quantile(ordered, 0.75)
        spread = q3 - q1
        if spread <= 0:
            continue

        lower = q1 - 1.5 * spread
        upper = q3 + 1.5 * spread
        for index, value in values:
            if value is None or lower <= value <= upper:
                continue
            boundary = upper if value > upper else lower
            amount = abs(value - boundary)
            deviation = {
                "amount": amount,
                "direction": "above" if value > upper else "below",
                "percent": amount / abs(boundary) * 100 if boundary != 0 else None,
            }
            anomaly = {
                "label": "Potential anomaly",
                "column": column,
                "value": value,
                "row_index": index + 1,
                "expected_range": {"lower": lower, "upper": upper},
                "deviation": deviation,
                "method": "IQR",
                "sample_size": len(valid_values),
            }
            candidates.append((amount / spread, anomaly))

    candidates.sort(key=lambda candidate: candidate[0], reverse=True)
    return [anomaly for _, anomaly in candidates[:_MAX_FINDINGS]]
