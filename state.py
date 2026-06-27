"""
统一的 state 对象 —— 贯穿整条分析流水线。

约定：
- 每个步骤签名为 run(state: dict) -> dict，只读自己需要的键、只写自己负责的键。
- facts 是唯一事实来源（全部由确定性 skill 产出，可单测、可验证）。
- agent（LLM）产出的 insight 通过 refs 锚定到 facts 中的 id（grounding）。

详见 REDESIGN_SPEC.md §3。
"""

from typing import Any, Dict, Set


def new_state(config: Dict[str, Any], df: Any = None) -> Dict[str, Any]:
    """构造初始 state。config 为用户配置（config.json 解析后的 dict）。"""
    return {
        "config": config or {},
        "schema": {},
        "data": {"df": df, "summary": {}},
        "facts": {
            "metrics": {},              # 描述统计：{metric: {mean, std, ...}}
            "fence_violations": [],     # 围栏越界
            "trends": [],               # 趋势
            "anomalies": [],            # 单指标异动
            "cross_anomalies": [],      # 跨指标关联异常
            "dimension_anomalies": [],  # 维度切片异常
            "attributions": [],         # 归因分解
        },
        "insights": [],                 # Interpreter(LLM) 产出
        "review": {},                   # Critic(LLM) 产出
        "report_md": "",                # Report(LLM) 产出
        "errors": [],                   # 各步降级/异常记录
    }


def log_error(state: Dict[str, Any], step: str, error: Any) -> Dict[str, Any]:
    """记录某一步的异常/降级，不中断流水线。"""
    state.setdefault("errors", []).append({"step": step, "error": str(error)})
    return state


def collect_fact_ids(facts: Dict[str, Any]) -> Set[str]:
    """
    收集所有可被引用的 fact id，供 grounding 校验使用
    （insight.refs 中的每个 id 都必须命中这里）。

    - 列表型 facts：取每个元素的 "id"
    - metrics：以 "m_<指标名>" 作为引用 id
    """
    ids: Set[str] = set()
    for group in ("fence_violations", "trends", "anomalies",
                  "cross_anomalies", "dimension_anomalies", "attributions"):
        for item in facts.get(group, []):
            if isinstance(item, dict) and "id" in item:
                ids.add(item["id"])
    for name in facts.get("metrics", {}):
        ids.add(f"m_{name}")
    return ids
