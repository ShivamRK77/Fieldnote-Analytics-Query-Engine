"""Strict CSV validation and isolated compatibility staging for uploaded datasets."""
from __future__ import annotations

import csv
import io
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pandas as pd

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
_DATE_HEADER = re.compile(r"(?:date|time|timestamp|month|year)", re.I)
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[ T].*)?$")


class DatasetUploadError(ValueError):
    """The uploaded file cannot safely be used as an analytics dataset."""


def _numeric_value(value: str) -> str | None:
    try:
        number = Decimal(value.replace(",", "").strip())
    except InvalidOperation:
        return None
    if not number.is_finite():
        return None
    return format(number, "f")


def _date_value(value: str) -> str | None:
    parsed = pd.to_datetime(value, errors="coerce", format="mixed", utc=True)
    if pd.isna(parsed):
        return None
    return parsed.strftime("%Y-%m-%d")


def _identifier(index: int, header: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", header.lower()).strip("_") or "column"
    return f"upload_{index}_{slug[:48]}"


def stage_csv(content: bytes, destination: Path) -> dict[str, Any]:
    """Validate a CSV and write only generated, app-owned engine input files."""
    if not content:
        raise DatasetUploadError("The uploaded CSV is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise DatasetUploadError(f"The CSV exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise DatasetUploadError("The CSV must be UTF-8 encoded.") from error

    try:
        records = [row for row in csv.reader(io.StringIO(text, newline=""), strict=True)
                   if any(cell.strip() for cell in row)]
    except csv.Error as error:
        raise DatasetUploadError("The CSV is malformed.") from error
    if not records:
        raise DatasetUploadError("The CSV does not contain a header row.")

    headers = [header.strip() for header in records[0]]
    if not headers or any(not header for header in headers):
        raise DatasetUploadError("Every CSV column must have a non-empty header.")
    if len({header.casefold() for header in headers}) != len(headers):
        raise DatasetUploadError("CSV headers must be unique, ignoring letter case.")
    source_rows = records[1:]
    if not source_rows:
        raise DatasetUploadError("The CSV must contain at least one data row.")
    if any(len(row) != len(headers) for row in source_rows):
        raise DatasetUploadError("Every CSV row must have the same number of fields as the header.")

    columns: list[dict[str, Any]] = []
    for index, header in enumerate(headers):
        values = [row[index].strip() for row in source_rows]
        nonempty = [value for value in values if value]
        if not nonempty:
            raise DatasetUploadError(f"Column '{header}' contains no values.")

        date_values = [_date_value(value) for value in nonempty]
        has_explicit_year = all(re.search(r"\b(?:19|20)\d{2}\b", value) for value in nonempty)
        is_date = has_explicit_year and all(value is not None for value in date_values) and (
            bool(_DATE_HEADER.search(header)) or any(_ISO_DATE.match(value) for value in nonempty)
        )
        numeric_values = [_numeric_value(value) for value in nonempty]
        if is_date:
            column_type = "date"
            normalized = [_date_value(value) if value else "" for value in values]
        elif all(value is not None for value in numeric_values):
            column_type = "numeric"
            normalized = [_numeric_value(value) if value else "" for value in values]
        else:
            column_type = "categorical"
            normalized = values
        columns.append({
            "header": header,
            "internal": _identifier(index, header),
            "type": column_type,
            "values": normalized,
        })

    numeric = [column for column in columns if column["type"] == "numeric"]
    if not numeric:
        raise DatasetUploadError("The CSV needs at least one numeric column to support analytics queries.")
    categorical = [column for column in columns if column["type"] == "categorical"]
    dates = [column for column in columns if column["type"] == "date"]

    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    sales_path = destination / "sales_data.csv"
    output_headers = [column["internal"] for column in columns] + [
        "order_date", "order_id", "quantity", "unit_price", "discount", "shipping_cost", "profit", "region",
    ]
    first_date = dates[0] if dates else None

    with sales_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(output_headers)
        for row_index in range(len(source_rows)):
            values = [column["values"][row_index] for column in columns]
            date_value = first_date["values"][row_index] if first_date else ""
            values.extend([
                date_value,
                str(row_index + 1),
                "1",
                "0",
                "0",
                "0",
                "0",
                "",
            ])
            writer.writerow(values)

    with (destination / "targets.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["region", "month", "target_revenue"])

    metric_names = {id(column): f"metric_{index}" for index, column in enumerate(numeric)}
    dictionary = {
        "metrics": {metric_names[id(column)]: column["internal"] for column in numeric},
        "dimensions": [column["internal"] for column in categorical + dates],
        "synonyms": {},
        "time_mappings": {},
    }
    overrides = {
        "metric_aliases": {column["header"].lower(): metric_names[id(column)] for column in numeric},
        "dimension_aliases": {column["header"].lower(): column["internal"] for column in categorical + dates},
        "non_dimension_columns": [column["internal"] for column in numeric] + [
            "quantity", "unit_price", "discount", "shipping_cost", "profit", "region",
        ],
    }
    (destination / "data_dictionary.json").write_text(json.dumps(dictionary, indent=2), encoding="utf-8")
    (destination / "semantic_overrides.json").write_text(json.dumps(overrides, indent=2), encoding="utf-8")

    column_map = {column["internal"]: column["header"] for column in columns}
    column_map.update({metric_names[id(column)]: column["header"] for column in numeric})
    return {
        "rows": len(source_rows),
        "columns": len(headers),
        "numeric_fields": [column["header"] for column in numeric],
        "categorical_fields": [column["header"] for column in categorical],
        "date_fields": [column["header"] for column in dates],
        "potential_metrics": [column["header"] for column in numeric],
        "potential_dimensions": [column["header"] for column in categorical + dates],
        "column_map": column_map,
    }