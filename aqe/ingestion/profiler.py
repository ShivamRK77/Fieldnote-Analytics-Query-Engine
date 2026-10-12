"""Data-quality checks run once at load time. Findings flow into explanations and lower
confidence where they could affect an answer."""
from __future__ import annotations
import pandas as pd


def profile(sales: pd.DataFrame, targets: pd.DataFrame) -> list[str]:
    w: list[str] = []
    if sales["order_id"].duplicated().any():
        w.append(f"{int(sales['order_id'].duplicated().sum())} duplicate order_id rows in sales data")
    if sales["order_date"].isna().any():
        w.append("some order_date values could not be parsed")
    for c in ("quantity", "unit_price", "discount", "profit"):
        n = int(sales[c].isna().sum())
        if n:
            w.append(f"{n} missing/non-numeric values in {c}")
    if ((sales["discount"] < 0) | (sales["discount"] > 1)).any():
        w.append("discount values outside [0,1]")
    if (sales["quantity"] < 0).any():
        w.append("negative quantities present (returns?)")
    if not targets.empty:
        missing = set(sales["region"]) - set(targets["region"])
        if missing:
            w.append(f"regions without targets: {sorted(missing)}")
    return w
