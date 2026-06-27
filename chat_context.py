"""
Chat Context Builder
从分析流水线提取完整上下文，供后续 LLM 问答使用
"""

import json
from datetime import datetime
from typing import Dict, Any, List


def build_chat_context(
    final_findings: Dict[str, Any],
    schema: Dict[str, Any],
    metrics_table: Dict[str, Any],
    etl_summary: Dict[str, Any],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """
    构建聊天上下文（JSON 可序列化）

    包含：数据概况、Schema、统计信息、分析发现、评审意见、汇总
    """
    # --- SCHEMA ---
    dimensions = [
        {"name": d.get("name", ""), "display_name": d.get("display_name", d.get("name", ""))}
        for d in schema.get("dimensions", [])
    ]
    metrics = [
        {"name": m.get("name", ""), "display_name": m.get("display_name", m.get("name", "")),
         "aggregation": m.get("aggregation", "sum")}
        for m in schema.get("metrics", [])
    ]
    derived_metrics = [
        {"name": f.get("name", ""), "expression": f.get("expression", "")}
        for f in schema.get("formulas", [])
    ]
    fence_metrics = [
        {"metric_name": fm.get("metric_name", ""),
         "display_name": fm.get("display_name", fm.get("metric_name", "")),
         "min": fm.get("min"),
         "max": fm.get("max")}
        for fm in schema.get("fence_metrics", [])
    ]
    anomaly_thresholds = schema.get("anomaly_thresholds", {})

    # --- DATA PROFILE ---
    data_profile = {
        "rows": etl_summary.get("rows", 0),
        "columns": etl_summary.get("columns", 0),
        "date_range": etl_summary.get("date_range"),
        "null_count": etl_summary.get("null_count", 0),
    }

    # --- STATISTICS ---
    statistics = metrics_table.get("stats", {})

    # --- FINDINGS --- (clean up for serialization)
    raw_findings = final_findings.get("findings", [])
    cleaned_findings = []
    for f in raw_findings:
        cf = {
            "id": f.get("id", ""),
            "metric": f.get("metric", ""),
            "display_name": f.get("display_name", f.get("metric", "")),
            "type": f.get("type"),
            "severity": f.get("severity"),
        }
        if "stats" in f:
            cf["stats"] = f["stats"]
        if "trend" in f:
            cf["trend"] = f["trend"]
        if "trend_insight" in f:
            cf["trend_insight"] = f["trend_insight"]
        if "anomaly" in f:
            cf["anomaly"] = f["anomaly"]
        if "anomaly_insight" in f:
            cf["anomaly_insight"] = f["anomaly_insight"]
        if "attribution" in f:
            attr = f["attribution"]
            cf["attribution"] = {
                "type": attr.get("type", "simple"),
                "expression": attr.get("expression"),
                "before": attr.get("before"),
                "after": attr.get("after"),
                "decomposition": attr.get("decomposition"),
                "insight": attr.get("insight", ""),
            }
            # Include drill_down summary (top contributors only, skip raw dataframes)
            if "drill_down" in attr:
                drill_summary = []
                for level in attr["drill_down"]:
                    drill_summary.append({
                        "level": level.get("level"),
                        "dimensions": level.get("dimensions", []),
                        "top_contributors": level.get("top_contributors", [])[:5],
                    })
                cf["attribution"]["drill_down_summary"] = drill_summary
        if "fence" in f:
            cf["fence"] = {
                "violation_count": f["fence"].get("violation_count", 0),
                "violation_rate": f["fence"].get("violation_rate", 0),
                "min_threshold": f["fence"].get("min_threshold"),
                "max_threshold": f["fence"].get("max_threshold"),
            }
        cleaned_findings.append(cf)

    # --- TIME SERIES (last 12 values per metric, lightweight) ---
    time_series = {}
    raw_df = metrics_table.get("df")
    if raw_df is not None:
        for metric_name in metrics_table.get("all_metric_names", []):
            if metric_name in raw_df.columns:
                ts = raw_df[metric_name].dropna().tail(12).tolist()
                time_series[metric_name] = [round(float(v), 2) for v in ts]

    context = {
        "meta": {
            "file_name": config.get("file_name", ""),
            "analysis_time": datetime.now().isoformat(),
        },
        "schema": {
            "dimensions": dimensions,
            "metrics": metrics,
            "derived_metrics": derived_metrics,
            "fence_metrics": fence_metrics,
            "anomaly_thresholds": anomaly_thresholds,
            "drill_order": schema.get("drill_order", []),
        },
        "data_profile": data_profile,
        "statistics": statistics,
        "findings": cleaned_findings,
        "reviews": {
            "data_review": final_findings.get("data_review", ""),
            "biz_reviews": final_findings.get("biz_reviews", {}),
            "rebuttal": final_findings.get("review_response", ""),
        },
        "analyst_report": final_findings.get("analysis_report", ""),
        "key_insights": final_findings.get("key_insights", []),
        "selected_reviewers": final_findings.get("selected_reviewers", []),
        "summary": {
            "total_findings": final_findings.get("total_findings", 0),
            "anomaly_count": final_findings.get("anomaly_count", 0),
            "fence_violation_count": final_findings.get("fence_violation_count", 0),
        },
        "time_series": time_series,
    }
    return context


def build_chat_prompt(context: Dict[str, Any], question: str) -> List[Dict[str, str]]:
    """
    将上下文 + 用户问题组装成 LLM 对话消息
    """
    # Build a concise summary of the analysis for the system prompt
    meta = context.get("meta", {})
    profile = context.get("data_profile", {})
    schema = context.get("schema", {})
    summary = context.get("summary", {})
    stats = context.get("statistics", {})
    findings = context.get("findings", [])
    reviews = context.get("reviews", {})

    # Compact findings summary
    finding_summaries = []
    for f in findings:
        parts = []
        parts.append(f"指标: {f.get('display_name', f.get('metric', ''))}")
        if f.get("type") == "fence_violation":
            parts.append(f"围栏越界(严重度:{f.get('severity','')})")
        if f.get("trend"):
            t = f["trend"]
            parts.append(f"趋势: {t.get('direction','')} {t.get('change_pct',0):.1f}%")
        if f.get("anomaly", {}).get("is_anomaly"):
            parts.append(f"异动: {f['anomaly'].get('confidence','')} 置信度")
        finding_summaries.append(" | ".join(parts))

    # Stats summary (first 3 metrics)
    stats_summary = []
    for name, s in list(stats.items())[:5]:
        stats_summary.append(
            f"{name}: 均值={s.get('mean','N/A')}, 中位数={s.get('median','N/A')}, "
            f"标准差={s.get('std','N/A')}, 最小={s.get('min','N/A')}, 最大={s.get('max','N/A')}"
        )

    system_content = f"""你是数据分析助手，已基于以下分析结果回答用户问题。如果问题超出分析范围，请说明限制。

## 数据概况
文件: {meta.get('file_name','')}
分析时间: {meta.get('analysis_time','')}
行数: {profile.get('rows',0)}, 列数: {profile.get('columns',0)}
时间范围: {profile.get('date_range','N/A')}

## 维度
{', '.join(d['display_name'] for d in schema.get('dimensions',[]))}

## 指标
{', '.join(m['display_name'] for m in schema.get('metrics',[]))}
{', '.join(dm['name'] for dm in schema.get('derived_metrics',[]))}

## 描述统计
{chr(10).join(stats_summary)}

## 分析发现 ({summary.get('total_findings',0)}个)
{chr(10).join(finding_summaries)}

## 评审意见
数据评审: {reviews.get('data_review','')[:200]}...
{chr(10).join(f'{name}: {text[:150]}...' for name, text in reviews.get('biz_reviews', {}).items())}

请用中文回答，引用具体的分析数据。回答要简洁，不超过300字，除非用户要求详细说明。"""

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": question},
    ]


def save_chat_context(context: Dict[str, Any], output_path: str):
    """保存聊天上下文到 JSON 文件"""
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(context, f, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    # Test with existing context file if available
    import os
    test_path = os.path.join(os.path.dirname(__file__), 'output', 'chat_context.json')
    if os.path.exists(test_path):
        with open(test_path, 'r', encoding='utf-8') as f:
            ctx = json.load(f)
        messages = build_chat_prompt(ctx, "销售额为什么下降了？")
        print(f"System prompt length: {len(messages[0]['content'])} chars")
        print(f"User question: {messages[1]['content']}")
    else:
        print("No chat_context.json found for testing")
