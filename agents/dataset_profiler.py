"""A0 dataset profiler for intent and config agents."""

from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd

from agents.config_advisor import profile_columns


def build_dataset_profile(df: pd.DataFrame, file_name: str = "") -> Dict[str, Any]:
    profile = profile_columns(df)
    numeric = []
    dates = []
    categories = []
    ignored = []
    for col in profile.get("columns", []):
        name = col["name"]
        if col.get("is_datelike"):
            dates.append(name)
        elif col["dtype"] == "numeric" and not _looks_like_id(name, col):
            numeric.append(name)
        elif col["dtype"] == "text" or col.get("unique_ratio", 1) <= 0.5:
            categories.append(name)
        else:
            ignored.append(name)
    return {
        "file_name": file_name,
        "row_count": profile.get("total_rows", 0),
        "column_count": profile.get("column_count", 0),
        "columns": profile.get("columns", []),
        "numeric_columns": numeric,
        "date_columns": dates,
        "category_columns": categories,
        "ignored_candidates": ignored,
    }


def _looks_like_id(name: str, col: Dict[str, Any]) -> bool:
    low = name.lower()
    if any(key in low for key in ("id", "编号", "单号", "transaction")):
        return True
    return col.get("unique_ratio", 0) > 0.8 and col.get("is_integer")
