"""
FormulaDiscovery (有界 agentic loop, 🤖 LLM + 确定性验证工具)

定位：ConfigAdvisor 里唯一需要"探索"的子任务——发现有分析价值的派生指标，
尤其是乘法分解（如 销售额 = 订单量 × 客单价），为后续归因(LMDI)创造可拆解结构。
原子指标靠看列名是猜不出这些的，必须"提议→在真实数据上验证→修正"。

三要素使它成为一个（有界的）agent：
  - 目标：找出站得住、且有分析价值的派生指标 / 分解
  - 工具：utils.formula_verifier（确定性，在真实 df 上算）
  - 迭代：把验证结果喂回 LLM，最多 max_iters 轮

护栏：迭代次数写死上限；验证由代码做（非 LLM 自评）；产物仍是草稿待人工确认。
零业务硬编码：只从已有指标 + 用户背景出发。
"""

import json
from typing import Any, Dict, List

import pandas as pd

from utils.formula_parser import FormulaParser
from utils.formula_verifier import check_identity, verify_formula


def discover_formulas(df: pd.DataFrame, atomic_metrics: List[str], llm: Any,
                      background: str = "", max_iters: int = 3,
                      identity_tol: float = 0.01) -> Dict[str, Any]:
    """
    返回：
      {
        "formulas":       [{"name","expression","purpose","stats"}],  # 已验证的派生指标
        "decompositions": [{"target","expression","max_rel_err"}],    # 已验证的分解恒等式
        "rejected":       [{"name","expression","reason"}],
        "iterations": int
      }
    """
    work = df.copy()                       # 工作副本：采纳的派生指标会加进来，供后续依赖
    accepted: List[Dict[str, Any]] = []
    accepted_names = set()
    decompositions: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    it = 0

    while it < max_iters:
        it += 1
        try:
            resp = llm.structured_call(
                _SYSTEM,
                _build_prompt(work, atomic_metrics, accepted, rejected, background),
                temperature=0.2, max_tokens=1536,
            )
        except Exception as e:
            rejected.append({"name": "", "expression": "", "reason": f"LLM 调用失败: {e}"})
            break

        progressed = False

        # 1) 处理候选派生指标
        for f in _as_list(resp.get("formulas")):
            name, expr = f.get("name", ""), f.get("expression", "")
            if not name or not expr or name in accepted_names:
                continue
            v = verify_formula(work, expr)
            if not v["parses"]:
                rejected.append({"name": name, "expression": expr,
                                 "reason": f"无法解析: {v['error']}"})
            elif not v["sane"]:
                reason = "常数" if v["constant"] else f"取值异常 {v['stats']}"
                rejected.append({"name": name, "expression": expr, "reason": reason})
            else:
                work[name] = pd.to_numeric(
                    FormulaParser(work).eval_formula(expr), errors="coerce")
                accepted.append({"name": name, "expression": expr,
                                 "purpose": f.get("purpose", ""), "stats": v["stats"]})
                accepted_names.add(name)
                progressed = True

        # 2) 处理分解恒等式（依赖上面采纳的派生指标，故放在其后）
        for d in _as_list(resp.get("decompositions")):
            target, expr = d.get("target", ""), d.get("expression", "")
            if not target or not expr:
                continue
            chk = check_identity(work, expr, target, tol=identity_tol)
            if chk.get("holds"):
                if not any(x["target"] == target and x["expression"] == expr
                           for x in decompositions):
                    decompositions.append({"target": target, "expression": expr,
                                           "max_rel_err": chk.get("max_rel_err")})
                    progressed = True
            else:
                rejected.append({"name": f"分解({target})", "expression": expr,
                                 "reason": chk.get("error") or f"不成立 max_rel_err={chk.get('max_rel_err')}"})

        if resp.get("done") or not progressed:
            break

    return {"formulas": accepted, "decompositions": decompositions,
            "rejected": rejected, "iterations": it}


# ------------------------------------------------------------ prompt 构造

_SYSTEM = (
    "你是数据建模专家。基于给定的原子指标，提议有分析价值的派生指标，"
    "尤其优先【乘法分解】（如 总量 = 数量 × 单位量），这类分解能支撑后续归因分析。"
    "表达式只能引用已存在或你本轮已提议的列，仅用 + - * / ( )。"
    "不要臆造数据里没有的概念。严格输出 JSON 对象。"
)


def _build_prompt(df: pd.DataFrame, atomic_metrics: List[str],
                  accepted: List[Dict], rejected: List[Dict], background: str) -> str:
    metric_info = []
    for m in atomic_metrics:
        if m in df.columns:
            s = pd.to_numeric(df[m], errors="coerce").dropna()
            if len(s):
                metric_info.append({"name": m, "min": round(float(s.min()), 2),
                                    "max": round(float(s.max()), 2),
                                    "mean": round(float(s.mean()), 2)})
    parts = ["## 现有指标", "```json",
             json.dumps(metric_info, ensure_ascii=False, indent=2), "```"]
    if accepted:
        parts += ["", "## 本轮已采纳（无需重复）",
                  json.dumps([{"name": a["name"], "expression": a["expression"]}
                              for a in accepted], ensure_ascii=False)]
    if rejected:
        parts += ["", "## 已驳回（请勿再提，或修正后再提）",
                  json.dumps(rejected[-6:], ensure_ascii=False)]
    if background.strip():
        parts += ["", "## 业务背景", background.strip()]
    parts += ["", _OUTPUT_SPEC]
    return "\n".join(parts)


_OUTPUT_SPEC = """## 输出格式（严格 JSON）
{
  "formulas": [
    {"name": "派生指标名", "expression": "销售额 / 订单量", "purpose": "为什么有价值"}
  ],
  "decompositions": [
    {"target": "被分解的现有指标", "expression": "因子A * 因子B"}
  ],
  "done": false,
  "reasoning": "一句话"
}
说明：
- formulas 是新派生指标；decompositions 是「现有指标 = 因子相乘/相加」的恒等式，
  其表达式可引用你在 formulas 里刚提议的派生指标。
- 若已无更多有价值的派生指标，把 done 设为 true。"""


def _as_list(x):
    return x if isinstance(x, list) else []
