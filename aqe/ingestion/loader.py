"""Tolerant loaders for the dataset files.

The supplied files were exported through a spreadsheet tool: every *line* is wrapped in
quotes (inner quotes doubled) and a UTF-8 BOM is present. Standard parsers read the CSVs
as a single column and the JSON as invalid. We detect that and repair it, otherwise we
behave like a normal loader.

Edge case worth naming: region code "NA" (North America) is parsed as NaN by pandas
by default, so every read uses keep_default_na=False.
"""
from __future__ import annotations
import io
import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

log = logging.getLogger(__name__)
NUMERIC = ["quantity", "unit_price", "discount", "shipping_cost", "profit"]


def _read_text(path: Path) -> str:
    return Path(path).read_bytes().decode("utf-8-sig")


def _unwrap_quoted_lines(text: str) -> str:
    out = []
    for line in text.splitlines():
        s = line.rstrip()
        if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
            s = s[1:-1].replace('""', '"')
        out.append(s)
    return "\n".join(out)


def load_json(path: Path) -> Any:
    text = _read_text(path)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        log.warning("%s is not valid JSON; repairing quoted-line export", Path(path).name)
        return json.loads(_unwrap_quoted_lines(text))


def load_csv(path: Path) -> pd.DataFrame:
    text = _read_text(path)
    df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    if df.shape[1] == 1 and "," in str(df.columns[0]):
        log.warning("%s parsed as one column; repairing quoted-line export", Path(path).name)
        df = pd.read_csv(io.StringIO(_unwrap_quoted_lines(text)), dtype=str, keep_default_na=False)
    df.columns = [c.strip() for c in df.columns]
    for c in df.columns:
        df[c] = df[c].str.strip()
    return df


def load_sales(path: Path) -> pd.DataFrame:
    df = load_csv(path)
    for c in NUMERIC:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["order_date"] = pd.to_datetime(df["order_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    return df


def load_targets(path: Path) -> pd.DataFrame:
    df = load_csv(path)
    df["target_revenue"] = pd.to_numeric(df["target_revenue"], errors="coerce")
    return df
