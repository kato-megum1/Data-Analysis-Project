"""Convert low-level facts into report-ready insight candidates."""

from __future__ import annotations

from typing import Any, Dict, List


class InsightEngine:
    def build(self, state: Dict[str, Any], analysis_plan: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
        facts = state.get("facts", {})
        candidates: List[Dict[str, Any]] = []
        candidates.extend(_metric_anomaly_candidates(facts))
        candidates.extend(_cross_candidates(facts))
        candidates.extend(_dimension_candidates(facts))
        candidates.extend(_fence_candidates(facts))
        candidates.extend(_attribution_candidates(facts))
        candidates.extend(_trend_candidates(facts))
        candidates.sort(key=lambda x: x.get("priority", 0), reverse=True)
        return candidates[:12]


def _metric_anomaly_candidates(facts: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for item in facts.get("anomalies", []):
        change = item.get("change_pct")
        out.append({
            "id": f"ins_{item.get('id')}",
            "type": "metric_anomaly",
            "priority": 95 if item.get("severity") == "high" else 82,
            "claim": f"{item.get('display_name', item.get('metric'))}在{item.get('period', '最新期')}出现显著异动，环比 {change:+.1f}%。" if isinstance(change, (int, float)) else item.get("detail", ""),
            "evidence_fact_ids": [item.get("id")],
            "confidence": "high" if item.get("confidence") == "high" else "medium",
            "action_hint": "优先按时间、维度切片和相关指标复核该异动。",
        })
    return out


def _cross_candidates(facts: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [{
        "id": f"ins_{item.get('id')}",
        "type": "cross_anomaly",
        "priority": 88,
        "claim": item.get("detail", "发现跨指标异常关系。"),
        "evidence_fact_ids": [item.get("id")],
        "confidence": "medium",
        "action_hint": "将相关指标放在同一业务链路中复核。",
    } for item in facts.get("cross_anomalies", [])]


def _dimension_candidates(facts: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for item in facts.get("dimension_anomalies", []):
        out.append({
            "id": f"ins_{item.get('id')}",
            "type": "dimension_anomaly",
            "priority": 78 if item.get("severity") == "medium" else 86,
            "claim": item.get("detail") or f"{item.get('dimension')}={item.get('slice_value')} 在 {item.get('display_name', item.get('metric'))} 上偏离整体水平。",
            "evidence_fact_ids": [item.get("id")],
            "confidence": "medium",
            "action_hint": "优先检查该维度切片的业务动作、样本量和数据质量。",
        })
    return out


def _fence_candidates(facts: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [{
        "id": f"ins_{item.get('id')}",
        "type": "rule_check",
        "priority": 84,
        "claim": f"{item.get('display_name', item.get('metric'))}存在 {item.get('violation_count')} 条阈值越界，越界率 {item.get('violation_rate')}%。",
        "evidence_fact_ids": [item.get("id")],
        "confidence": "high",
        "action_hint": "检查越界样本的维度分布，并确认阈值是否需要调整。",
    } for item in facts.get("fence_violations", [])]


def _attribution_candidates(facts: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for item in facts.get("attributions", []):
        contribs = item.get("contributions", [])
        if not contribs:
            continue
        top = contribs[0]
        out.append({
            "id": f"ins_{item.get('id')}",
            "type": "attribution",
            "priority": 86,
            "claim": f"{item.get('metric')} 的变化主要由 {top.get('factor')} 解释，贡献占比约 {top.get('pct')}%。",
            "evidence_fact_ids": [item.get("id")],
            "confidence": "medium",
            "action_hint": "沿主要贡献因子继续下钻到维度和样本。",
        })
    return out


def _trend_candidates(facts: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for item in facts.get("trends", []):
        change = item.get("change_pct")
        if not isinstance(change, (int, float)) or abs(change) < 10:
            continue
        direction = "明显上升" if change > 0 else "明显下降"
        out.append({
            "id": f"ins_{item.get('id')}",
            "type": "trend",
            "priority": 70 + min(20, abs(change) / 2),
            "claim": f"{item.get('display_name', item.get('metric'))}最新一期{direction}，环比 {change:+.1f}%。",
            "evidence_fact_ids": [item.get("id")],
            "confidence": "medium",
            "action_hint": "结合异常检测和维度贡献判断是否需要行动。",
        })
    return out
