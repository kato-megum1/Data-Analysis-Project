"""
Skill 3：指标计算（纯代码，无 LLM）

输入：state["data"]["df"]（ETL 聚合后底表） + state["schema"]
输出：
  - 原地给 df 增列：派生指标（如 利润 / 利润率）
  - state["data"]["formula_types"]：{公式名: additive|multiplicative|mixed}（供归因用）
  - state["facts"]["metrics"]：{指标: 描述统计}
  - state["facts"]["fence_violations"]：[{id, metric, bounds, violation_count, ...}]

职责边界：只做"算指标 + 描述统计 + 围栏越界判断"。趋势/异动/归因在后续 skill。
"""

import math
from typing import Any, Dict, List

import pandas as pd

from state import log_error
from utils.formula_parser import FormulaParser


def run(state: Dict[str, Any]) -> Dict[str, Any]:
    """流水线入口：算派生指标 + 统计 + 围栏，写入 df 与 facts。"""
    data = state.get("data") or {}
    df = data.get("df")
    schema = state.get("schema") or {}
    facts = state.setdefault("facts", {})
    try:
        if df is None or len(df) == 0:
            raise ValueError("ETL 未产出有效数据（df 为空）")

        formula_types = compute_derived(df, schema, state)
        data["formula_types"] = formula_types

        facts["metrics"] = compute_stats(df, schema)
        facts["fence_violations"] = check_fences(df, schema)
    except Exception as e:
        log_error(state, "metric", e)
        facts.setdefault("metrics", {})
        facts.setdefault("fence_violations", [])
    return state


# ----------------------------------------------------------- 派生指标

def compute_derived(df: pd.DataFrame, schema: Dict[str, Any],
                    state: Dict[str, Any]) -> Dict[str, str]:
    """
    按公式计算派生指标，支持依赖链（利润率 依赖 利润 依赖 销售额/成本）。
    多趟求值：每趟只算依赖已就绪的公式，直到无新增。
    返回 {公式名: 公式类型}。
    """
    formulas = [f for f in schema.get("formulas", []) if f.get("name") and f.get("expression")]
    computed = set(df.columns)
    formula_types: Dict[str, str] = {}

    for _ in range(len(formulas) + 1):
        pending = [f for f in formulas if f["name"] not in computed]
        if not pending:
            break
        parser = FormulaParser(df)
        progressed = False
        for f in pending:
            try:
                df[f["name"]] = parser.eval_formula(f["expression"])
                computed.add(f["name"])
                progressed = True
            except ValueError as e:
                if "未定义的列" in str(e) or "未找到匹配的列名" in str(e):
                    continue  # 依赖未就绪，下一趟再试
                log_error(state, "metric", f"公式 [{f['name']}={f['expression']}] 失败: {e}")
            except Exception as e:
                log_error(state, "metric", f"公式 [{f['name']}={f['expression']}] 失败: {e}")
        if not progressed:
            break  # 死锁（循环依赖或全部失败），避免空转

    # 公式类型（加法/乘法/混合）—— 供归因 skill 选择分解方法
    parser = FormulaParser(df)
    for f in formulas:
        try:
            formula_types[f["name"]] = parser.get_formula_type(f["expression"])
        except Exception:
            formula_types[f["name"]] = "unknown"
    return formula_types


# ----------------------------------------------------------- 描述统计

def compute_stats(df: pd.DataFrame, schema: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """对所有 analysis_metrics 计算描述统计。"""
    metric_names = schema.get("analysis_metrics") or [m["name"] for m in schema.get("metrics", [])]
    stats: Dict[str, Dict[str, Any]] = {}
    for name in metric_names:
        if name not in df.columns:
            continue
        col = df[name].dropna()
        if len(col) == 0:
            continue
        stats[name] = {
            "count": int(col.count()),
            "sum": _r(col.sum()),
            "mean": _r(col.mean()),
            "median": _r(col.median()),
            "std": _r(col.std()),
            "min": _r(col.min()),
            "max": _r(col.max()),
            "q25": _r(col.quantile(0.25)),
            "q75": _r(col.quantile(0.75)),
            "missing": int(df[name].isnull().sum()),
        }
    return stats


# ----------------------------------------------------------- 围栏越界

def check_fences(df: pd.DataFrame, schema: Dict[str, Any]) -> List[Dict[str, Any]]:
    """逐围栏判断越界，产出每指标一条结构化 fact（id = f_<metric>）。"""
    dim_names = [d["name"] for d in schema.get("dimensions", []) if d["name"] in df.columns]
    violations: List[Dict[str, Any]] = []

    for fence in schema.get("fences", []):
        name = fence["name"]
        if name not in df.columns:
            continue
        lo, hi = fence.get("min"), fence.get("max")
        col = pd.to_numeric(df[name], errors="coerce")

        below = col < lo if lo is not None else pd.Series(False, index=col.index)
        above = col > hi if hi is not None else pd.Series(False, index=col.index)
        mask = (below | above).fillna(False)
        n_viol = int(mask.sum())
        total = int(col.notna().sum())
        if n_viol == 0:
            continue

        samples = []
        for idx in df.index[mask][:8]:
            val = col.loc[idx]
            samples.append({
                "value": _r(val),
                "side": "min" if (lo is not None and val < lo) else "max",
                "dims": {d: _cell(df.loc[idx, d]) for d in dim_names},
            })

        violations.append({
            "id": f"f_{name}",
            "metric": name,
            "display_name": fence.get("display_name", name),
            "bounds": {"min": lo, "max": hi},
            "violation_count": n_viol,
            "total_count": total,
            "violation_rate": _r(n_viol / total * 100) if total else 0.0,
            "samples": samples,
        })
    return violations


# ----------------------------------------------------------- 工具

def _r(x, ndigits: int = 4):
    """nan/inf 安全的四舍五入。"""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(v) or math.isinf(v):
        return None
    return round(v, ndigits)


def _cell(x):
    """把单元格值转成 JSON 友好的标量。"""
    if isinstance(x, pd.Timestamp):
        return x.strftime("%Y-%m-%d")
    if pd.isna(x):
        return None
    if hasattr(x, "item"):
        return x.item()
    return x
