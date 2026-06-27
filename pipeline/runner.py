"""新架构流水线编排入口。"""

import os
from typing import Any, Dict

from agents.analysis_planner_agent import AnalysisPlannerAgent
from agents.critic_agent import CriticAgent, apply_verdicts
from agents.insight_engine import InsightEngine
from agents.report_orchestrator import ReportOrchestrator
from state import new_state
from pipeline import anomaly, attribution, etl, metric, schema, trend
from pipeline.report import build_context, save_context


def run_analysis(config: Dict[str, Any], output_dir: str,
                 session_id: str | None = None,
                 llm: Any = None) -> Dict[str, Any]:
    os.makedirs(output_dir, exist_ok=True)
    state = new_state(config)

    state = schema.run(state)
    state["analysis_plan"] = AnalysisPlannerAgent(llm=llm).plan(config, config.get("analysis_intent", {}))

    for step in (etl.run, metric.run, trend.run, anomaly.run, attribution.run):
        state = step(state)

    state["insight_candidates"] = InsightEngine().build(state, state["analysis_plan"])
    state["insights"] = [
        {
            "id": item["id"],
            "refs": item.get("evidence_fact_ids", []),
            "claim": item.get("claim", ""),
            "confidence": {"high": "高", "medium": "中", "low": "低"}.get(item.get("confidence"), item.get("confidence", "中")),
            "recommendation": item.get("action_hint", ""),
        }
        for item in state["insight_candidates"]
    ]
    state["critic_review"] = CriticAgent(llm=llm).review(state.get("facts", {}), state["insights"])
    state["final_insights"] = apply_verdicts(state["insights"], state["critic_review"])
    report_result = ReportOrchestrator(llm=llm).run(state)
    state["structured_report"] = report_result["structured_report"]
    html = report_result["html"]

    stem = session_id or "report"
    report_path = os.path.join(output_dir, f"{stem}.html")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)

    context = build_context(state, config)
    context_path = os.path.join(output_dir, f"{stem}_context.json")
    save_context(context, context_path)

    facts = state.get("facts", {})
    return {
        "state": state,
        "context": context,
        "report_path": report_path,
        "context_path": context_path,
        "summary": {
            "total": len(state.get("insights", [])),
            "anomalies": len(facts.get("anomalies", [])),
            "fences": len(facts.get("fence_violations", [])),
            "key_insights": [i["claim"] for i in state.get("final_insights", [])[:3]],
            "selected_reviewers": [],
            "analysis_methods": [m.get("name") for m in state.get("analysis_plan", {}).get("modules", [])],
            "critic_revisions": sum(1 for v in state.get("critic_review", {}).get("verdicts", []) if v.get("status") == "revise"),
            "critic_rejections": sum(1 for v in state.get("critic_review", {}).get("verdicts", []) if v.get("status") == "reject"),
            "errors": state.get("errors", []),
        },
    }
