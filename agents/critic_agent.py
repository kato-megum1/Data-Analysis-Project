"""Independent structured quality gate for facts-backed insights."""

from __future__ import annotations

from typing import Any, Dict, List, Set

from state import collect_fact_ids


class CriticAgent:
    def __init__(self, llm: Any = None):
        self.llm = llm

    def review(self, facts: Dict[str, Any], insights: List[Dict[str, Any]]) -> Dict[str, Any]:
        if self.llm is not None:
            try:
                out = self._llm_review(facts, insights)
                return normalize_review(out, facts, insights)
            except Exception as e:
                fallback = deterministic_review(facts, insights)
                fallback.setdefault("warnings", []).append(f"Critic LLM 不可用，已使用确定性审查: {e}")
                return fallback
        return deterministic_review(facts, insights)

    def _llm_review(self, facts: Dict[str, Any], insights: List[Dict[str, Any]]) -> Dict[str, Any]:
        import json

        system = (
            "你是独立 Critic Agent。只审查 insights 是否被 facts 支撑，"
            "输出 JSON verdicts。不要改写事实，不要写报告。"
            "status 只能是 pass/revise/reject。"
        )
        user = json.dumps({"facts": compact_facts(facts), "insights": insights}, ensure_ascii=False)
        return self.llm.structured_call(system, user, temperature=0.1, max_tokens=2048)


def deterministic_review(facts: Dict[str, Any], insights: List[Dict[str, Any]]) -> Dict[str, Any]:
    fact_ids = collect_fact_ids(facts)
    verdicts = []
    for insight in insights:
        refs = insight.get("refs", [])
        missing = [ref for ref in refs if ref not in fact_ids]
        if not refs or missing:
            verdicts.append({
                "insight_id": insight.get("id", ""),
                "status": "reject",
                "issue": f"缺少有效 facts 引用: {missing or refs}",
                "suggested_confidence": "低",
            })
            continue
        confidence = insight.get("confidence", "中")
        issue = ""
        for ref in refs:
            fact = find_fact(facts, ref)
            if fact and fact.get("points", 99) < 4 and "趋势" in insight.get("claim", ""):
                confidence = "中低"
                issue = "样本点不足，趋势判断需降低置信度。"
        verdicts.append({
            "insight_id": insight.get("id", ""),
            "status": "revise" if issue else "pass",
            "issue": issue,
            "suggested_confidence": confidence,
        })
    return {"verdicts": verdicts, "warnings": []}


def normalize_review(out: Dict[str, Any], facts: Dict[str, Any],
                     insights: List[Dict[str, Any]]) -> Dict[str, Any]:
    valid_ids = {i.get("id") for i in insights}
    verdicts = []
    for v in out.get("verdicts", []) if isinstance(out, dict) else []:
        if v.get("insight_id") in valid_ids and v.get("status") in {"pass", "revise", "reject"}:
            verdicts.append({
                "insight_id": v.get("insight_id"),
                "status": v.get("status"),
                "issue": v.get("issue", ""),
                "suggested_confidence": v.get("suggested_confidence", ""),
            })
    seen = {v["insight_id"] for v in verdicts}
    for i in insights:
        if i.get("id") not in seen:
            verdicts.append({"insight_id": i.get("id"), "status": "pass", "issue": "", "suggested_confidence": i.get("confidence", "中")})
    return {"verdicts": verdicts, "warnings": out.get("warnings", []) if isinstance(out, dict) else []}


def apply_verdicts(insights: List[Dict[str, Any]], review: Dict[str, Any]) -> List[Dict[str, Any]]:
    verdict_by_id = {v["insight_id"]: v for v in review.get("verdicts", [])}
    final = []
    for insight in insights:
        verdict = verdict_by_id.get(insight.get("id"), {"status": "pass"})
        if verdict["status"] == "reject":
            continue
        item = {**insight}
        if verdict["status"] == "revise":
            if verdict.get("suggested_confidence"):
                item["confidence"] = verdict["suggested_confidence"]
            if verdict.get("issue"):
                item["review_note"] = verdict["issue"]
        final.append(item)
    return final


def compact_facts(facts: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "metrics": facts.get("metrics", {}),
        "fence_violations": facts.get("fence_violations", []),
        "trends": facts.get("trends", []),
        "anomalies": facts.get("anomalies", []),
        "cross_anomalies": facts.get("cross_anomalies", []),
        "dimension_anomalies": facts.get("dimension_anomalies", []),
        "attributions": facts.get("attributions", []),
    }


def find_fact(facts: Dict[str, Any], fact_id: str) -> Dict[str, Any] | None:
    if fact_id.startswith("m_"):
        metric = fact_id[2:]
        return facts.get("metrics", {}).get(metric)
    for group in ("fence_violations", "trends", "anomalies", "cross_anomalies", "dimension_anomalies", "attributions"):
        for item in facts.get(group, []):
            if item.get("id") == fact_id:
                return item
    return None
