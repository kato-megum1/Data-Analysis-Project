"""
Skill 5: 异动检测（纯代码，无 LLM）。

基于趋势序列做单指标异动、跨指标方向背离和维度切片异常。
"""

from typing import Any, Dict, List

import pandas as pd

from state import log_error
from utils.anomaly_detector import AnomalyDetector


def run(state: Dict[str, Any]) -> Dict[str, Any]:
    facts = state.setdefault("facts", {})
    schema = state.get("schema") or {}
    data = state.get("data") or {}
    df = data.get("df")
    try:
        trends = facts.get("trends", [])
        facts["anomalies"] = detect_metric_anomalies(trends, schema)
        facts["cross_anomalies"] = detect_cross_anomalies(trends)
        facts["dimension_anomalies"] = detect_dimension_anomalies(df, schema) if df is not None else []
    except Exception as e:
        log_error(state, "anomaly", e)
        facts.setdefault("anomalies", [])
        facts.setdefault("cross_anomalies", [])
        facts.setdefault("dimension_anomalies", [])
    return state


def detect_metric_anomalies(trends: List[Dict[str, Any]],
                            schema: Dict[str, Any]) -> List[Dict[str, Any]]:
    detector = AnomalyDetector(window=4, z_threshold=2.0)
    thresholds = schema.get("anomaly_thresholds", {})
    out: List[Dict[str, Any]] = []

    for tr in trends:
        values = [p["value"] for p in tr.get("series", []) if p.get("value") is not None]
        if len(values) < 2:
            continue
        th = thresholds.get(tr["metric"], {})
        result = detector.detect(pd.Series(values).to_numpy(dtype=float),
                                 down_threshold=th.get("down"),
                                 up_threshold=th.get("up"))
        if not result.get("is_anomaly"):
            continue
        out.append({
            "id": f"a_{tr['metric']}",
            "metric": tr["metric"],
            "display_name": tr.get("display_name", tr["metric"]),
            "period": tr.get("periods", [""])[-1] if tr.get("periods") else "",
            "severity": "high" if result.get("confidence") == "high" else "medium",
            **result,
        })
    return out


def detect_cross_anomalies(trends: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    changed = [
        t for t in trends
        if isinstance(t.get("change_pct"), (int, float)) and abs(t["change_pct"]) >= 10
    ]
    out: List[Dict[str, Any]] = []
    for i, left in enumerate(changed):
        for right in changed[i + 1:]:
            if left["change_pct"] * right["change_pct"] < 0:
                out.append({
                    "id": f"x_{left['metric']}_{right['metric']}",
                    "type": "direction_divergence",
                    "metrics": [left["metric"], right["metric"]],
                    "severity": "medium",
                    "detail": (
                        f"{left['display_name']} {left['change_pct']:+.1f}% 与 "
                        f"{right['display_name']} {right['change_pct']:+.1f}% 方向背离"
                    ),
                })
    return out[:10]


def detect_dimension_anomalies(df: pd.DataFrame, schema: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for dim in schema.get("dimensions", []):
        dim_name = dim["name"]
        if dim_name not in df.columns or pd.api.types.is_datetime64_any_dtype(df[dim_name]):
            continue
        for metric in schema.get("analysis_metrics", []):
            if metric not in df.columns:
                continue
            grouped = df.groupby(dim_name)[metric].agg(["mean", "count"]).reset_index()
            if len(grouped) < 2:
                continue
            overall_mean = df[metric].mean()
            overall_std = df[metric].std()
            if not overall_std or pd.isna(overall_std):
                continue
            grouped["z"] = (grouped["mean"] - overall_mean) / overall_std
            grouped["abs_z"] = grouped["z"].abs()
            top = grouped.loc[grouped["abs_z"].idxmax()]
            if top["abs_z"] < 1.5 or int(top["count"]) < 2:
                continue
            out.append({
                "id": f"d_{dim_name}_{metric}_{str(top[dim_name])[:24]}",
                "type": "dimension_slice",
                "dimension": dim_name,
                "slice_value": str(top[dim_name]),
                "metric": metric,
                "display_name": metric,
                "z": round(float(top["z"]), 4),
                "slice_mean": round(float(top["mean"]), 4),
                "overall_mean": round(float(overall_mean), 4),
                "severity": "medium",
            })
    out.sort(key=lambda x: abs(x["z"]), reverse=True)
    return out[:10]
