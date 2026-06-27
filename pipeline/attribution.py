"""
Skill 6: 归因分解（纯代码，无 LLM）。
"""

from typing import Any, Dict, List

import pandas as pd

from state import log_error
from utils.attribution import AttributionEngine


def run(state: Dict[str, Any]) -> Dict[str, Any]:
    facts = state.setdefault("facts", {})
    data = state.get("data") or {}
    df = data.get("df")
    schema = state.get("schema") or {}
    try:
        if df is None or df.empty:
            raise ValueError("ETL 未产出有效数据（df 为空）")
        facts["attributions"] = compute_attributions(df, schema, data.get("formula_types", {}))
    except Exception as e:
        log_error(state, "attribution", e)
        facts.setdefault("attributions", [])
    return state


def compute_attributions(df: pd.DataFrame, schema: Dict[str, Any],
                         formula_types: Dict[str, str]) -> List[Dict[str, Any]]:
    engine = AttributionEngine()
    out: List[Dict[str, Any]] = []
    if len(df) < 2:
        return out

    mid = max(1, len(df) // 2)
    before_df = df.iloc[:mid]
    after_df = df.iloc[mid:]

    for formula in schema.get("formulas", []):
        name = formula.get("name")
        parts = [p for p in formula.get("parts", []) if p in df.columns]
        if not name or len(parts) < 2 or name not in df.columns:
            continue

        before = {p: float(before_df[p].mean()) for p in parts}
        after = {p: float(after_df[p].mean()) for p in parts}
        kind = formula_types.get(name, "unknown")
        if kind == "multiplicative":
            decomposition = engine.multiplicative_attribution(before, after)
        else:
            decomposition = engine.additive_attribution(before, after)

        out.append({
            "id": f"attr_{name}",
            "metric": name,
            "method": "LMDI" if kind == "multiplicative" else "additive",
            "expression": formula.get("expression", ""),
            "before": {k: round(v, 4) for k, v in before.items()},
            "after": {k: round(v, 4) for k, v in after.items()},
            "contributions": _normalize_decomp(decomposition),
        })

    out.extend(_dimension_contributions(df, schema))
    return out


def _normalize_decomp(decomposition: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    for factor, info in decomposition.items():
        rows.append({
            "factor": factor,
            "delta": round(float(info.get("delta", 0)), 4),
            "pct": round(float(info.get("contribution_pct", 0)), 4),
            "detail": info.get("contribution_desc", ""),
        })
    rows.sort(key=lambda x: abs(x["pct"]), reverse=True)
    return rows


def _dimension_contributions(df: pd.DataFrame, schema: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    dims = [d["name"] for d in schema.get("dimensions", []) if d["name"] in df.columns]
    metrics = [m for m in schema.get("analysis_metrics", []) if m in df.columns]
    for metric in metrics[:5]:
        for dim in dims:
            if pd.api.types.is_datetime64_any_dtype(df[dim]):
                continue
            total = df[metric].sum()
            if not total or pd.isna(total):
                continue
            grouped = df.groupby(dim)[metric].sum().sort_values(ascending=False).head(5)
            out.append({
                "id": f"attr_dim_{metric}_{dim}",
                "metric": metric,
                "method": "dimension_share",
                "dimension": dim,
                "top_contributors": [
                    {"value": str(idx), "sum": round(float(val), 4), "share_pct": round(float(val / total * 100), 4)}
                    for idx, val in grouped.items()
                ],
            })
    return out[:20]
