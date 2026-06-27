"""Metric system drafting for one-table analysis.

The agent is conservative by default: deterministic heuristics create a safe
config, optional LLM output is normalized and verified before it can enable
derived metrics or rules.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

import pandas as pd

from agents.config_advisor import heuristic_suggest, normalize_draft, profile_columns
from utils.formula_verifier import verify_formula


TEMPLATES = {
    "retail": {
        "keywords": ["销售", "订单", "成本", "利润", "gmv", "revenue", "sales", "cost", "profit"],
        "groups": {
            "收入": ["销售", "收入", "营收", "gmv", "sales", "revenue"],
            "成本": ["成本", "费用", "cost", "expense"],
            "利润": ["利润", "毛利", "profit", "margin"],
            "规模": ["订单", "销量", "用户", "order", "volume"],
        },
    },
    "growth": {
        "keywords": ["uv", "pv", "dau", "mau", "留存", "转化", "活跃", "跳出"],
        "groups": {
            "流量": ["uv", "pv", "访问", "访客", "traffic"],
            "活跃": ["dau", "mau", "活跃", "active"],
            "效率": ["转化", "跳出", "留存", "conversion", "bounce", "retention"],
        },
    },
    "finance": {
        "keywords": ["收入", "成本", "费用", "利润", "预算", "现金", "roi"],
        "groups": {
            "收入": ["收入", "营收", "revenue"],
            "成本费用": ["成本", "费用", "cost", "expense"],
            "利润回报": ["利润", "roi", "profit", "return"],
        },
    },
    "general": {"keywords": [], "groups": {"核心指标": []}},
}


class MetricSystemAgent:
    def __init__(self, llm: Any = None):
        self.llm = llm

    def draft(self, df: pd.DataFrame, field_doc: str = "", background: str = "") -> Dict[str, Any]:
        profile = profile_columns(df)
        base = heuristic_suggest(df, profile)
        source = "heuristic"
        warnings: List[str] = []

        if self.llm is not None:
            try:
                llm_draft = self._llm_draft(profile, field_doc, background)
                normalized = normalize_draft(llm_draft, df)
                if normalized.get("dimensions") or normalized.get("metrics"):
                    base = normalized
                    source = "llm"
            except Exception as e:
                warnings.append(f"LLM 指标体系建议不可用，已使用启发式配置: {e}")
                source = "heuristic_fallback"

        base = self._ensure_minimum_config(base, df, profile)
        template = infer_template(profile, background, field_doc)
        base, disabled_formulas = verify_and_filter_formulas(base, df)
        warnings.extend(disabled_formulas)

        metric_system = build_metric_system(base, profile, template, warnings, source)
        base["metric_system"] = metric_system
        base["primary_metrics"] = metric_system["primary_metrics"]
        base["metric_groups"] = metric_system["metric_groups"]
        base["source"] = source
        base["warnings"] = warnings
        return {
            "metric_system": metric_system,
            "recommended_config": base,
            "warnings": warnings,
            "source": source,
        }

    def _llm_draft(self, profile: Dict[str, Any], field_doc: str, background: str) -> Dict[str, Any]:
        import json

        system = (
            "你是指标体系设计 Agent。根据单表字段画像、字段说明和业务背景，"
            "输出保守、可验证的分析配置 JSON。只使用真实存在的列名；"
            "派生公式只能引用真实指标列；不确定内容放到 warnings。"
        )
        user = json.dumps({
            "profile": profile,
            "field_doc": field_doc[:2000],
            "background": background,
            "required_keys": [
                "dimensions", "metrics", "formulas", "fences", "anomalies",
                "drill_order", "primary_metrics", "metric_groups", "warnings",
            ],
        }, ensure_ascii=False, indent=2)
        return self.llm.structured_call(system, user, temperature=0.2, max_tokens=2048)

    def _ensure_minimum_config(self, draft: Dict[str, Any], df: pd.DataFrame,
                               profile: Dict[str, Any]) -> Dict[str, Any]:
        draft = {**draft}
        if not draft.get("metrics"):
            numeric = [c for c in profile["columns"] if c["dtype"] == "numeric"]
            draft["metrics"] = [
                {"idx": c["idx"], "name": c["name"], "displayName": c["name"], "agg": "avg" if not c.get("is_integer") and -1 <= c.get("min", 0) <= c.get("max", 0) <= 1 else "sum"}
                for c in numeric
            ]
        if not draft.get("dimensions"):
            date_like = [c for c in profile["columns"] if c.get("is_datelike")]
            draft["dimensions"] = [
                {"idx": c["idx"], "name": c["name"], "displayName": c["name"], "type": "dimension"}
                for c in date_like[:1]
            ]
        draft.setdefault("formulas", [])
        draft.setdefault("fences", [])
        draft.setdefault("anomalies", [])
        draft.setdefault("drill_order", [d["name"] for d in draft.get("dimensions", [])])
        return normalize_draft(draft, df)


def infer_template(profile: Dict[str, Any], background: str = "", field_doc: str = "") -> str:
    text = " ".join([background or "", field_doc or ""] + [c["name"] for c in profile["columns"]]).lower()
    scores = {}
    for name, spec in TEMPLATES.items():
        scores[name] = sum(1 for kw in spec["keywords"] if kw.lower() in text)
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "general"


def verify_and_filter_formulas(config: Dict[str, Any], df: pd.DataFrame) -> Tuple[Dict[str, Any], List[str]]:
    valid = []
    warnings = []
    for formula in config.get("formulas", []):
        name = formula.get("name", "")
        expr = formula.get("expression", "")
        if not name or not expr:
            continue
        check = verify_formula(df, expr)
        if check.get("parses") and check.get("sane"):
            valid.append(formula)
        else:
            warnings.append(f"派生指标 '{name}' 未启用：公式无法在样本上稳定计算（{check.get('error') or '结果不健康'}）")
    out = {**config, "formulas": valid}
    return out, warnings


def build_metric_system(config: Dict[str, Any], profile: Dict[str, Any],
                        template: str, warnings: List[str], source: str) -> Dict[str, Any]:
    metrics = config.get("metrics", [])
    formulas = config.get("formulas", [])
    groups = group_metrics(metrics + [{"name": f["name"], "displayName": f["name"]} for f in formulas], template)
    primary = pick_primary_metrics(metrics, formulas, groups)
    return {
        "template": template,
        "source": source,
        "dimensions": config.get("dimensions", []),
        "atomic_metrics": metrics,
        "derived_metrics": formulas,
        "primary_metrics": primary,
        "metric_groups": groups,
        "analysis_rules": {
            "fences": config.get("fences", []),
            "anomalies": config.get("anomalies", []),
            "drill_order": config.get("drill_order", []),
        },
        "warnings": warnings,
    }


def group_metrics(metrics: List[Dict[str, Any]], template: str) -> Dict[str, List[str]]:
    spec = TEMPLATES.get(template, TEMPLATES["general"])
    groups = {name: [] for name in spec["groups"]}
    unmatched = []
    for metric in metrics:
        name = metric.get("name", "")
        low = name.lower()
        matched = False
        for group, keys in spec["groups"].items():
            if any(k.lower() in low for k in keys):
                groups.setdefault(group, []).append(name)
                matched = True
                break
        if not matched:
            unmatched.append(name)
    if unmatched:
        groups.setdefault("其他指标", []).extend(unmatched)
    return {k: v for k, v in groups.items() if v}


def pick_primary_metrics(metrics: List[Dict[str, Any]], formulas: List[Dict[str, Any]],
                         groups: Dict[str, List[str]]) -> List[str]:
    names = [m["name"] for m in metrics] + [f["name"] for f in formulas]
    preferred_patterns = ["销售", "收入", "营收", "利润", "订单", "uv", "pv", "dau", "roi", "转化"]
    primary = []
    for pat in preferred_patterns:
        for name in names:
            if name not in primary and re.search(pat, name, re.I):
                primary.append(name)
            if len(primary) >= 6:
                return primary
    for group_metrics in groups.values():
        for name in group_metrics:
            if name not in primary:
                primary.append(name)
            if len(primary) >= 6:
                return primary
    return primary[:6]
