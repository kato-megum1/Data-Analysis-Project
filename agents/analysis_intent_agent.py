"""B-line analysis intent selection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


class AnalysisIntentAgent:
    def __init__(self, llm: Any = None, root: Path | None = None):
        self.llm = llm
        self.root = root or Path(__file__).resolve().parents[1]

    def infer(self, dataset_profile: Dict[str, Any], background: str = "") -> Dict[str, Any]:
        if self.llm is not None:
            try:
                out = self._llm_infer(dataset_profile, background)
                return normalize_intent(out, dataset_profile)
            except Exception as e:
                intent = heuristic_intent(dataset_profile, background)
                intent.setdefault("warnings", []).append(f"AnalysisIntent LLM 不可用，已使用确定性兜底: {e}")
                return intent
        return heuristic_intent(dataset_profile, background)

    def _llm_infer(self, dataset_profile: Dict[str, Any], background: str) -> Dict[str, Any]:
        workflow = (self.root / "workflow_specs" / "report_workflow.md").read_text(encoding="utf-8")
        skill = (self.root / "workflow_specs" / "report_skills" / "01_intent_selection.md").read_text(encoding="utf-8")
        expert_index = (self.root / "workflow_specs" / "expert_library" / "INDEX.md").read_text(encoding="utf-8")
        compact = {
            "file_name": dataset_profile.get("file_name", ""),
            "row_count": dataset_profile.get("row_count"),
            "numeric_columns": dataset_profile.get("numeric_columns", []),
            "date_columns": dataset_profile.get("date_columns", []),
            "category_columns": dataset_profile.get("category_columns", []),
            "background": background,
        }
        system = "你是数据分析意图识别 Agent。严格按 skill 输出 JSON。"
        user = json.dumps({
            "workflow": workflow,
            "skill": skill,
            "expert_index": expert_index,
            "dataset_profile": compact,
        }, ensure_ascii=False)
        return self.llm.structured_call(system, user, temperature=0.15, max_tokens=2048)


def heuristic_intent(dataset_profile: Dict[str, Any], background: str = "") -> Dict[str, Any]:
    text = " ".join([
        dataset_profile.get("file_name", ""),
        background or "",
        *dataset_profile.get("numeric_columns", []),
        *dataset_profile.get("category_columns", []),
    ]).lower()
    sales_keys = ("sales", "amount", "total amt", "qty", "rate", "tax", "retail", "销售", "金额", "订单")
    domain = "sales_retail" if any(k in text for k in sales_keys) else "general"
    methods: List[str] = ["baseline_comparison"]
    if dataset_profile.get("date_columns") and dataset_profile.get("numeric_columns"):
        methods.extend(["trend_analysis", "anomaly_detection"])
    if dataset_profile.get("category_columns") and dataset_profile.get("numeric_columns"):
        methods.append("dimension_drilldown")
    if len(dataset_profile.get("numeric_columns", [])) >= 2:
        methods.extend(["cross_analysis", "attribution_analysis"])
    methods.append("rule_check")
    focus_metrics = _pick_focus_metrics(dataset_profile.get("numeric_columns", []), domain)
    return {
        "analysis_goal": background or ("生成零售经营分析报告" if domain == "sales_retail" else "生成数据分析报告"),
        "business_domain": domain,
        "primary_methods": list(dict.fromkeys(methods)),
        "focus_metrics": focus_metrics,
        "focus_dimensions": (dataset_profile.get("date_columns", []) + dataset_profile.get("category_columns", []))[:5],
        "comparison": "latest_vs_previous" if dataset_profile.get("date_columns") else "overall_baseline",
        "reason": "基于字段类型、文件名和用户背景自动选择分析方式。",
        "confidence": 0.72,
        "warnings": [],
    }


def normalize_intent(out: Dict[str, Any], dataset_profile: Dict[str, Any]) -> Dict[str, Any]:
    fallback = heuristic_intent(dataset_profile)
    if not isinstance(out, dict):
        return fallback
    methods = [m for m in out.get("primary_methods", []) if isinstance(m, str)]
    if not methods:
        methods = fallback["primary_methods"]
    valid_metrics = set(dataset_profile.get("numeric_columns", []))
    valid_dims = set(dataset_profile.get("date_columns", []) + dataset_profile.get("category_columns", []))
    return {
        "analysis_goal": out.get("analysis_goal") or fallback["analysis_goal"],
        "business_domain": out.get("business_domain") or fallback["business_domain"],
        "primary_methods": methods,
        "focus_metrics": [m for m in out.get("focus_metrics", []) if m in valid_metrics] or fallback["focus_metrics"],
        "focus_dimensions": [d for d in out.get("focus_dimensions", []) if d in valid_dims] or fallback["focus_dimensions"],
        "comparison": out.get("comparison") or fallback["comparison"],
        "reason": out.get("reason", fallback["reason"]),
        "confidence": float(out.get("confidence", fallback["confidence"]) or 0.0),
        "warnings": out.get("warnings", []) if isinstance(out.get("warnings", []), list) else [],
    }


def _pick_focus_metrics(metrics: List[str], domain: str) -> List[str]:
    preferred = ["total amt", "sales", "revenue", "amount", "qty", "rate", "tax", "销售", "金额", "数量"]
    out = []
    for key in preferred:
        for metric in metrics:
            if metric not in out and key in metric.lower():
                out.append(metric)
    return (out or metrics)[:6]
