"""Render a report from a saved state/facts JSON file.

This intentionally runs only the report layer. It does not execute schema,
ETL, metric calculation, anomaly detection, attribution, or any LLM calls.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.report import build_context, build_insights, generate_html, save_context


def main() -> int:
    parser = argparse.ArgumentParser(description="Render report HTML from state/facts JSON.")
    parser.add_argument("input", help="Path to a JSON file containing state with facts.")
    parser.add_argument(
        "--output-dir",
        default="output/report_agent_test",
        help="Directory for generated HTML and context JSON.",
    )
    parser.add_argument("--stem", default="rich_facts_report", help="Output filename stem.")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with input_path.open("r", encoding="utf-8") as f:
        state = json.load(f)

    if not state.get("insights"):
        state["insights"] = build_insights(state)
    if not state.get("final_insights"):
        state["final_insights"] = state["insights"]

    html = generate_html(state)
    report_path = output_dir / f"{args.stem}.html"
    report_path.write_text(html, encoding="utf-8")

    context = build_context(state, state.get("config", {}))
    context_path = output_dir / f"{args.stem}_context.json"
    save_context(context, str(context_path))

    print(json.dumps({
        "report_path": str(report_path),
        "context_path": str(context_path),
        "insights": len(state.get("final_insights", [])),
        "anomalies": len(state.get("facts", {}).get("anomalies", [])),
        "cross_anomalies": len(state.get("facts", {}).get("cross_anomalies", [])),
        "dimension_anomalies": len(state.get("facts", {}).get("dimension_anomalies", [])),
        "fence_violations": len(state.get("facts", {}).get("fence_violations", [])),
        "attributions": len(state.get("facts", {}).get("attributions", [])),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
