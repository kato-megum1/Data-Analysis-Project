"""C-line executable analysis planner."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


class AnalysisPlannerAgent:
    def __init__(self, llm: Any = None, root: Path | None = None):
        self.llm = llm
        self.root = root or Path(__file__).resolve().parents[1]

    def plan(self, config: Dict[str, Any], intent: Dict[str, Any]) -> Dict[str, Any]:
        if self.llm is not None:
            try:
                return normalize_plan(self._llm_plan(config, intent), config, intent)
            except Exception as e:
                plan = heuristic_plan(config, intent)
                plan.setdefault("warnings", []).append(f"AnalysisPlanner LLM 不可用，已使用确定性兜底: {e}")
                return plan
        return heuristic_plan(config, intent)

    def _llm_plan(self, config: Dict[str, Any], intent: Dict[str, Any]) -> Dict[str, Any]:
        workflow = (self.root / "workflow_specs" / "report_workflow.md").read_text(encoding="utf-8")
        skill = (self.root / "workflow_specs" / "report_skills" / "03_analysis_planning.md").read_text(encoding="utf-8")
        compact_config = {
            "dimensions": config.get("dimensions", []),
            "metrics": config.get("metrics", []),
            "formulas": config.get("formulas", []),
            "primary_metrics": config.get("primary_metrics", []),
            "fences": config.get("fences", []),
            "anomalies": config.get("anomalies", []),
            "drill_order": config.get("drill_order", []),
        }
        system = "你是分析计划 Agent。严格按 skill 输出 JSON，只使用已配置字段。"
        user = json.dumps({"workflow": workflow, "skill": skill, "intent": intent, "config": compact_config}, ensure_ascii=False)
        return self.llm.structured_call(system, user, temperature=0.15, max_tokens=2048)


def heuristic_plan(config: Dict[str, Any], intent: Dict[str, Any]) -> Dict[str, Any]:
    metrics = [m.get("name") for m in config.get("metrics", []) if m.get("name")]
    metrics += [f.get("name") for f in config.get("formulas", []) if f.get("name")]
    dims = [d.get("name") for d in config.get("dimensions", []) if d.get("name")]
    primary = [m for m in config.get("primary_metrics", []) if m in metrics] or metrics[:3]
    focus = [m for m in intent.get("focus_metrics", []) if m in metrics] or primary
    methods = intent.get("primary_methods", [])
    modules = []
    for method in methods:
        modules.append({
            "name": method,
            "metrics": focus[:6],
            "dimensions": dims[:5],
            "reason": _module_reason(method),
        })
    requirements = ["period_comparison", "metric_summary"]
    if "anomaly_detection" in methods:
        requirements.append("anomaly_table")
    if "dimension_drilldown" in methods:
        requirements.append("dimension_contribution")
    if "attribution_analysis" in methods:
        requirements.append("attribution_table")
    return {
        "goal": intent.get("analysis_goal", "生成数据分析报告"),
        "business_domain": intent.get("business_domain", "general"),
        "primary_metric": primary[0] if primary else "",
        "modules": modules,
        "evidence_requirements": list(dict.fromkeys(requirements)),
        "limitations": [],
        "warnings": [],
    }


def normalize_plan(out: Dict[str, Any], config: Dict[str, Any], intent: Dict[str, Any]) -> Dict[str, Any]:
    fallback = heuristic_plan(config, intent)
    if not isinstance(out, dict):
        return fallback
    known_metrics = {m.get("name") for m in config.get("metrics", [])} | {f.get("name") for f in config.get("formulas", [])}
    known_dims = {d.get("name") for d in config.get("dimensions", [])}
    modules = []
    for mod in out.get("modules", []) if isinstance(out.get("modules"), list) else []:
        if not isinstance(mod, dict) or not mod.get("name"):
            continue
        modules.append({
            "name": mod.get("name"),
            "metrics": [m for m in mod.get("metrics", []) if m in known_metrics],
            "dimensions": [d for d in mod.get("dimensions", []) if d in known_dims],
            "reason": mod.get("reason", ""),
        })
    return {
        "goal": out.get("goal") or fallback["goal"],
        "business_domain": out.get("business_domain") or fallback["business_domain"],
        "primary_metric": out.get("primary_metric") if out.get("primary_metric") in known_metrics else fallback["primary_metric"],
        "modules": modules or fallback["modules"],
        "evidence_requirements": out.get("evidence_requirements", fallback["evidence_requirements"]),
        "limitations": out.get("limitations", []) if isinstance(out.get("limitations", []), list) else [],
        "warnings": out.get("warnings", []) if isinstance(out.get("warnings", []), list) else [],
    }


def _module_reason(method: str) -> str:
    return {
        "baseline_comparison": "建立核心指标的对比基线。",
        "trend_analysis": "识别指标随时间的方向和幅度。",
        "anomaly_detection": "发现超出正常波动的指标或切片。",
        "cross_analysis": "检查相关指标是否出现背离或共振。",
        "dimension_drilldown": "定位关键维度贡献和异常切片。",
        "attribution_analysis": "解释变化可能来自哪些驱动因素。",
        "rule_check": "检查阈值、围栏和业务规则健康度。",
    }.get(method, "根据用户意图补充分析模块。")
