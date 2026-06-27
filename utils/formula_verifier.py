"""
公式验证工具（确定性，无 LLM）

供 FormulaDiscovery 的「提议→验证→修正」循环当作 tool 使用：
LLM 提议候选派生指标 / 分解，这里用真实数据把它算出来、判断是否站得住，
再把结果喂回 LLM。验证全部是确定性代码，杜绝"LLM 自说自话"。

两个原语：
  - verify_formula(df, expr)：候选派生指标本身是否健康（能算、范围合理、非常数）
  - check_identity(df, expr, target)：分解恒等式是否在数据上成立（expr ≈ target）
"""

from typing import Any, Dict

import numpy as np
import pandas as pd

from utils.formula_parser import FormulaParser


def verify_formula(df: pd.DataFrame, expression: str) -> Dict[str, Any]:
    """
    评估一个候选派生指标表达式。
    返回 {expression, parses, error, sane, constant, stats:{...}}。
    sane=True 表示：能解析、有效值占比足够、不是常数、未大面积除零爆炸。
    """
    out: Dict[str, Any] = {
        "expression": expression, "parses": False, "error": None,
        "sane": False, "constant": False, "stats": {},
    }
    try:
        series = FormulaParser(df).eval_formula(expression)
    except Exception as e:
        out["error"] = str(e)
        return out

    out["parses"] = True
    s = pd.to_numeric(series, errors="coerce")
    n = len(s)
    inf_rate = float(np.isinf(s).mean()) if n else 1.0
    finite = s.replace([np.inf, -np.inf], np.nan).dropna()
    null_rate = 1.0 - (len(finite) / n) if n else 1.0

    if len(finite) == 0:
        out["error"] = "结果全为空/无穷（可能除零或引用空列）"
        out["stats"] = {"null_rate": round(null_rate, 4), "inf_rate": round(inf_rate, 4)}
        return out

    out["constant"] = bool(finite.nunique() <= 1)
    out["stats"] = {
        "min": round(float(finite.min()), 4),
        "max": round(float(finite.max()), 4),
        "mean": round(float(finite.mean()), 4),
        "std": round(float(finite.std()), 4) if len(finite) > 1 else 0.0,
        "null_rate": round(null_rate, 4),
        "inf_rate": round(inf_rate, 4),
        "negative_rate": round(float((finite < 0).mean()), 4),
    }
    # 健康标准：有效值过半、非常数、几乎无 inf（除零）
    out["sane"] = (null_rate < 0.5) and (not out["constant"]) and (inf_rate < 0.05)
    return out


def check_identity(df: pd.DataFrame, expression: str, target: str,
                   tol: float = 0.01) -> Dict[str, Any]:
    """
    校验分解恒等式：expression 是否在数据上重构出 target 列（逐行相对误差 ≤ tol）。
    用于确认"销售额 = 订单量 × 客单价"这类分解真的成立，从而可用于归因。
    """
    out: Dict[str, Any] = {"expression": expression, "target": target,
                           "holds": False, "error": None}
    if target not in df.columns:
        out["error"] = f"目标列不存在: {target}"
        return out
    try:
        lhs = pd.to_numeric(FormulaParser(df).eval_formula(expression), errors="coerce")
    except Exception as e:
        out["error"] = str(e)
        return out

    rhs = pd.to_numeric(df[target], errors="coerce")
    mask = lhs.notna() & rhs.notna() & ~np.isinf(lhs) & (rhs != 0)
    if int(mask.sum()) == 0:
        out["error"] = "无可比较的数据点"
        return out

    rel_err = ((lhs[mask] - rhs[mask]).abs() / rhs[mask].abs())
    out["max_rel_err"] = round(float(rel_err.max()), 6)
    out["mean_rel_err"] = round(float(rel_err.mean()), 6)
    out["compared_rows"] = int(mask.sum())
    out["holds"] = bool(rel_err.max() <= tol)
    return out
