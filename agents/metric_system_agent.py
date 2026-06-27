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
        base = enrich_config_for_analysis(base, df, profile)
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
        "field_profile": config.get("field_profile", []),
        "metric_dimension_matrix": config.get("metric_dimension_matrix", []),
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


def enrich_config_for_analysis(config: Dict[str, Any], df: pd.DataFrame,
                               profile: Dict[str, Any]) -> Dict[str, Any]:
    """Add deterministic analysis-ready defaults without overriding LLM/user choices."""
    out = {**config}
    out = sanitize_field_roles(out, profile)
    out["field_profile"] = build_field_profile(profile, out)
    out["formulas"] = merge_by_name(out.get("formulas", []), suggest_formulas(out, df))
    out["fences"] = merge_by_name(out.get("fences", []), suggest_fences(out, df))
    out["anomalies"] = merge_by_name(out.get("anomalies", []), suggest_anomaly_rules(out))
    out["metric_dimension_matrix"] = build_metric_dimension_matrix(out, profile)
    return out


def sanitize_field_roles(config: Dict[str, Any], profile: Dict[str, Any]) -> Dict[str, Any]:
    """Keep identifiers out of metrics and put usable low-cardinality codes into dimensions."""
    out = {**config}
    by_name = {c["name"]: c for c in profile.get("columns", [])}
    dims = []
    metrics = []
    dim_names = {d.get("name") for d in dims}
    metric_names = set()

    for dim in out.get("dimensions", []):
        name = dim.get("name")
        col = by_name.get(name, {})
        if _is_quantity_metric(name or "", col):
            metrics.append({"idx": col.get("idx"), "name": name, "displayName": dim.get("displayName", name), "agg": "sum"})
            metric_names.add(name)
            continue
        dims.append(dict(dim))
        dim_names.add(name)

    for metric in out.get("metrics", []):
        name = metric.get("name")
        col = by_name.get(name, {})
        if name in metric_names:
            continue
        if _is_identifier_like(name or "", col):
            if col.get("unique_count", 0) <= 30 and name not in dim_names and not _is_index_like(name or ""):
                dims.append({"idx": col.get("idx"), "name": name, "displayName": metric.get("displayName", name), "type": "dimension"})
                dim_names.add(name)
            continue
        metrics.append(metric)
        metric_names.add(name)

    # Date dimensions used for time trend should prefer transaction/order dates over DOB.
    dims.sort(key=lambda d: (_dimension_priority(d.get("name", ""), by_name.get(d.get("name", ""), {})), by_name.get(d.get("name", ""), {}).get("unique_count", 999999)))
    out["dimensions"] = dims
    out["metrics"] = metrics
    out["drill_order"] = [d["name"] for d in dims if d.get("name")]
    primary = [m for m in out.get("primary_metrics", []) if m in {x.get("name") for x in metrics}]
    out["primary_metrics"] = primary
    return out


def build_field_profile(profile: Dict[str, Any], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    dims = {d.get("name") for d in config.get("dimensions", [])}
    metrics = {m.get("name") for m in config.get("metrics", [])}
    rows = []
    for col in profile.get("columns", []):
        name = col["name"]
        if name in dims:
            role, confidence = "dimension", 0.86
            reason = "低基数、日期或文本字段，适合作为分组维度。"
        elif name in metrics:
            role, confidence = "metric", 0.86
            reason = "数值字段，适合作为分析指标。"
        else:
            role, confidence = "ignore", 0.62
            reason = "疑似 ID、索引或高基数字段，默认不参与分析。"
        rows.append({
            "idx": col.get("idx"),
            "name": name,
            "dtype": col.get("dtype"),
            "unique_count": col.get("unique_count"),
            "unique_ratio": col.get("unique_ratio"),
            "null_count": col.get("null_count"),
            "samples": col.get("samples", []),
            "recommended_role": role,
            "confidence": confidence,
            "reason": reason,
        })
    return rows


def suggest_formulas(config: Dict[str, Any], df: pd.DataFrame) -> List[Dict[str, Any]]:
    names = {str(c): str(c) for c in df.columns}
    lower = {str(c).lower(): str(c) for c in df.columns}

    def find(*patterns: str) -> str:
        for pattern in patterns:
            for name in names:
                if re.search(pattern, name, re.I):
                    return name
            for low, name in lower.items():
                if pattern.lower() in low:
                    return name
        return ""

    total = find(r"total\s*amt", r"sales", r"revenue", r"amount", "销售", "金额")
    qty = find(r"^qty$", r"quantity", "数量", "销量")
    rate = find(r"^rate$", "单价", "价格")
    tax = find(r"^tax$", "税")
    cost = find("cost", "成本")
    mrp = find(r"^mrp$", "标价", "原价")

    formulas: List[Dict[str, Any]] = []
    if total and qty:
        formulas.append({"name": "avg_order_value", "displayName": "客单价", "expression": f"{total} / {qty}"})
    if total and tax:
        formulas.append({"name": "net_amount", "displayName": "税前金额", "expression": f"{total} - {tax}"})
        formulas.append({"name": "tax_rate", "displayName": "税率", "expression": f"{tax} / ({total} - {tax})"})
    if total and cost:
        formulas.append({"name": "gross_margin", "displayName": "毛利额", "expression": f"{total} - {cost}"})
        formulas.append({"name": "gross_margin_rate", "displayName": "毛利率", "expression": f"({total} - {cost}) / {total}"})
    if mrp and rate:
        formulas.append({"name": "discount_rate", "displayName": "折扣率", "expression": f"({mrp} - {rate}) / {mrp}"})
    return formulas


def suggest_fences(config: Dict[str, Any], df: pd.DataFrame) -> List[Dict[str, Any]]:
    metric_names = [m.get("name") for m in config.get("metrics", [])] + [f.get("name") for f in config.get("formulas", [])]
    fences = []
    for name in metric_names:
        low = (name or "").lower()
        if any(key in low for key in ("tax_rate", "discount_rate", "gross_margin_rate", "ratio", "率", "margin_rate")):
            fences.append({"name": name, "min": 0, "max": 1})
        elif name in df.columns and pd.api.types.is_numeric_dtype(df[name]) and (df[name] < 0).any():
            fences.append({"name": name, "min": 0, "max": None})
    return fences


def suggest_anomaly_rules(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    metrics = [m.get("name") for m in config.get("metrics", [])]
    metrics += [f.get("name") for f in config.get("formulas", [])]
    primary = config.get("primary_metrics") or metrics[:6]
    return [
        {"name": name, "downThreshold": 20, "upThreshold": 30}
        for name in primary if name
    ]


def build_metric_dimension_matrix(config: Dict[str, Any], profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    card = {c["name"]: c.get("unique_count", 0) for c in profile.get("columns", [])}
    rows = []
    for dim in config.get("dimensions", []):
        dim_name = dim.get("name")
        dim_card = card.get(dim_name, 0)
        for metric in config.get("metrics", []) + [{"name": f.get("name"), "displayName": f.get("displayName", f.get("name"))} for f in config.get("formulas", [])]:
            metric_name = metric.get("name")
            if not dim_name or not metric_name:
                continue
            if dim_card <= 1:
                score, reason = 0.2, "维度取值过少，拆解信息有限。"
            elif dim_card <= 30:
                score, reason = 0.9, "维度基数适中，适合做分组对比和下钻。"
            elif dim_card <= 200:
                score, reason = 0.65, "维度基数较高，适合排行或 TopN 分析。"
            else:
                score, reason = 0.35, "维度基数过高，建议谨慎用于下钻。"
            rows.append({
                "dimension": dim_name,
                "metric": metric_name,
                "score": score,
                "recommended": score >= 0.6,
                "reason": reason,
            })
    return rows


def merge_by_name(base: List[Dict[str, Any]], extra: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged = []
    seen = set()
    for item in (base or []) + (extra or []):
        name = item.get("name")
        if not name or name in seen:
            continue
        seen.add(name)
        merged.append(item)
    return merged


def _is_identifier_like(name: str, col: Dict[str, Any]) -> bool:
    low = name.lower()
    if _is_index_like(name):
        return True
    if any(key in low for key in (" id", "id", "编号", "transaction")):
        return True
    if "code" in low and col.get("is_integer"):
        return True
    return False


def _is_index_like(name: str) -> bool:
    low = name.lower()
    return low.startswith("unnamed") or low in {"index", "idx"}


def _dimension_priority(name: str, col: Dict[str, Any]) -> int:
    low = name.lower()
    if col.get("is_datelike") and any(key in low for key in ("tran", "order", "date", "日期", "交易")) and "dob" not in low:
        return 0
    if col.get("is_datelike"):
        return 5
    if any(key in low for key in ("cat", "category", "品类", "subcat", "store", "city", "gender")):
        return 1
    if "code" in low:
        return 3
    return 2


def _is_quantity_metric(name: str, col: Dict[str, Any]) -> bool:
    low = name.lower()
    return col.get("dtype") == "numeric" and any(key in low for key in ("qty", "quantity", "销量", "数量", "件数"))
