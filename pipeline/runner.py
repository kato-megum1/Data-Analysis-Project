"""新架构流水线编排入口。"""

import os
from typing import Any, Dict

from agents.critic_agent import CriticAgent, apply_verdicts
from state import new_state
from pipeline import anomaly, attribution, etl, metric, schema, trend
from pipeline.report import build_context, build_insights, generate_html, save_context


def run_analysis(config: Dict[str, Any], output_dir: str,
                 session_id: str | None = None,
                 llm: Any = None) -> Dict[str, Any]:
    os.makedirs(output_dir, exist_ok=True)
    state = new_state(config)

    for step in (schema.run, etl.run, metric.run, trend.run, anomaly.run, attribution.run):
        state = step(state)

    state["insights"] = build_insights(state)
    state["critic_review"] = CriticAgent(llm=llm).review(state.get("facts", {}), state["insights"])
    state["final_insights"] = apply_verdicts(state["insights"], state["critic_review"])
    html = generate_html(state)

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
            "critic_revisions": sum(1 for v in state.get("critic_review", {}).get("verdicts", []) if v.get("status") == "revise"),
            "critic_rejections": sum(1 for v in state.get("critic_review", {}).get("verdicts", []) if v.get("status") == "reject"),
            "errors": state.get("errors", []),
        },
    }
