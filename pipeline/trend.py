"""
Skill 4: 趋势计算（纯代码，无 LLM）。

输入 state["data"]["df"] + state["schema"]，输出 state["facts"]["trends"]。
"""

import math
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from state import log_error


def run(state: Dict[str, Any]) -> Dict[str, Any]:
    data = state.get("data") or {}
    df = data.get("df")
    schema = state.get("schema") or {}
    facts = state.setdefault("facts", {})
    try:
        if df is None or df.empty:
            raise ValueError("ETL 未产出有效数据（df 为空）")
        facts["trends"] = compute_trends(df, schema)
    except Exception as e:
        log_error(state, "trend", e)
        facts.setdefault("trends", [])
    return state


def compute_trends(df: pd.DataFrame, schema: Dict[str, Any]) -> List[Dict[str, Any]]:
    trends: List[Dict[str, Any]] = []
    time_dim = _time_dimension(df, schema)
    metric_names = schema.get("analysis_metrics") or []

    for metric in metric_names:
        if metric not in df.columns:
            continue
        series = _series_for_metric(df, schema, metric, time_dim)
        values = pd.to_numeric(series["value"], errors="coerce").dropna().tolist()
        if not values:
            continue

        latest = values[-1]
        previous = values[-2] if len(values) >= 2 else None
        change_pct = None
        if previous not in (None, 0):
            change_pct = (latest - previous) / previous * 100

        slope = _slope(values)
        trends.append({
            "id": f"t_{metric}",
            "metric": metric,
            "display_name": _display_name(schema, metric),
            "periods": _periods(series),
            "series": [{"period": p, "value": _r(v)} for p, v in zip(_periods(series), values)],
            "latest": _r(latest),
            "previous": _r(previous),
            "change_pct": _r(change_pct),
            "slope": _r(slope),
            "overall_trend": _classify(values, slope),
            "points": len(values),
        })
    return trends


def _series_for_metric(df: pd.DataFrame, schema: Dict[str, Any], metric: str,
                       time_dim: Optional[str]) -> pd.DataFrame:
    agg = _metric_agg(schema, metric)
    if time_dim:
        out = df.groupby(time_dim, as_index=False)[metric].agg(agg)
        out = out.sort_values(time_dim).rename(columns={time_dim: "period", metric: "value"})
        return out
    return pd.DataFrame({"period": list(range(1, len(df) + 1)), "value": df[metric].tolist()})


def _metric_agg(schema: Dict[str, Any], metric: str) -> str:
    for m in schema.get("metrics", []):
        if m["name"] == metric:
            return "mean" if m.get("agg") in ("avg", "mean") else m.get("agg", "sum")
    return "mean"


def _time_dimension(df: pd.DataFrame, schema: Dict[str, Any]) -> Optional[str]:
    for d in schema.get("dimensions", []):
        name = d["name"]
        if name in df.columns and pd.api.types.is_datetime64_any_dtype(df[name]):
            return name
    return None


def _periods(series: pd.DataFrame) -> List[str]:
    out = []
    for p in series["period"].tolist():
        if isinstance(p, pd.Timestamp):
            out.append(p.strftime("%Y-%m-%d"))
        else:
            out.append(str(p)[:10])
    return out


def _slope(values: List[float]) -> float:
    if len(values) < 2:
        return 0.0
    x = np.arange(len(values))
    return float(np.polyfit(x, values, 1)[0])


def _classify(values: List[float], slope: float) -> str:
    if len(values) < 3:
        return "数据不足"
    mean = float(np.mean(values))
    if abs(mean) < 1e-10:
        return "平稳"
    ratio = slope / abs(mean)
    if ratio > 0.03:
        return "上升"
    if ratio < -0.03:
        return "下降"
    cv = float(np.std(values) / abs(mean)) if mean else 0.0
    return "波动" if cv > 0.2 else "平稳"


def _display_name(schema: Dict[str, Any], name: str) -> str:
    for m in schema.get("metrics", []):
        if m["name"] == name:
            return m.get("display_name", name)
    return name


def _r(x, ndigits: int = 4):
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(v) or math.isinf(v):
        return None
    return round(v, ndigits)
