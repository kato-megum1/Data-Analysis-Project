"""
新架构报告与问答兜底：只消费 state.facts，不调用 LLM。
"""

import html
import json
import os
from datetime import datetime
from typing import Any, Dict, List


def build_insights(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    facts = state.get("facts", {})
    insights: List[Dict[str, Any]] = []

    for a in facts.get("anomalies", []):
        insights.append({
            "id": f"ins_{a['id']}",
            "refs": [a["id"]],
            "claim": f"{a['display_name']}最新一期异动，环比 {a.get('change_pct', 0):+.1f}%。",
            "confidence": "高" if a.get("confidence") == "high" else "中",
            "recommendation": "优先核查该指标的口径、分维度贡献和近期业务动作。",
        })
    for f in facts.get("fence_violations", []):
        insights.append({
            "id": f"ins_{f['id']}",
            "refs": [f["id"]],
            "claim": f"{f['display_name']}存在 {f['violation_count']} 条围栏越界，越界率 {f['violation_rate']}%。",
            "confidence": "高",
            "recommendation": "检查越界样本对应维度，并确认阈值是否仍然适用。",
        })
    for x in facts.get("cross_anomalies", [])[:3]:
        insights.append({
            "id": f"ins_{x['id']}",
            "refs": [x["id"]],
            "claim": x.get("detail", "发现跨指标方向背离。"),
            "confidence": "中",
            "recommendation": "将背离指标放在同一业务链路中核对。",
        })
    for t in sorted(facts.get("trends", []), key=lambda item: abs(item.get("change_pct") or 0), reverse=True)[:3]:
        if t.get("change_pct") is None:
            continue
        insights.append({
            "id": f"ins_{t['id']}",
            "refs": [t["id"]],
            "claim": f"{t['display_name']}最新一期{t['overall_trend']}，环比 {t['change_pct']:+.1f}%。",
            "confidence": "中",
            "recommendation": "结合时间粒度和维度贡献判断是否需要行动。",
        })
    return insights


def build_context(state: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    schema = state.get("schema", {})
    data = state.get("data", {})
    facts = state.get("facts", {})
    return {
        "meta": {
            "file_name": config.get("file_name", ""),
            "analysis_time": datetime.now().isoformat(timespec="seconds"),
            "architecture": "state+facts",
        },
        "schema": {
            "dimensions": schema.get("dimensions", []),
            "metrics": schema.get("metrics", []),
            "formulas": schema.get("formulas", []),
            "drill_order": schema.get("drill_order", []),
        },
        "data_profile": data.get("summary", {}),
        "facts": facts,
        "analysis_intent": state.get("config", {}).get("analysis_intent", {}),
        "analysis_plan": state.get("analysis_plan", {}),
        "insight_candidates": state.get("insight_candidates", []),
        "structured_report": state.get("structured_report", {}),
        "insights": state.get("insights", []),
        "critic_review": state.get("critic_review", {}),
        "final_insights": state.get("final_insights", []),
        "errors": state.get("errors", []),
    }


def save_context(context: Dict[str, Any], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(context, f, ensure_ascii=False, indent=2)


def generate_html(state: Dict[str, Any]) -> str:
    schema = state.get("schema", {})
    summary = state.get("data", {}).get("summary", {})
    facts = state.get("facts", {})
    insights = state.get("final_insights") or state.get("insights", [])
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>数据分析报告</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif;margin:0;background:#f6f7f9;color:#202124;line-height:1.7}}
.wrap{{max-width:1080px;margin:0 auto;padding:32px 20px}}
.header{{border-bottom:3px solid #1a73e8;padding-bottom:18px;margin-bottom:24px}}
h1{{font-size:28px;margin:0 0 8px;color:#1a73e8}} h2{{font-size:20px;margin:0 0 14px;color:#1a73e8}}
.meta{{color:#5f6368;font-size:13px}} .section{{background:#fff;border:1px solid #dadce0;border-radius:8px;padding:22px;margin-bottom:18px}}
table{{width:100%;border-collapse:collapse;font-size:13px}} th,td{{border-bottom:1px solid #e0e0e0;padding:8px 10px;text-align:left}} th{{background:#f8f9fa;color:#5f6368}}
.num{{text-align:right;font-variant-numeric:tabular-nums}} .badge{{display:inline-block;border-radius:12px;padding:2px 8px;font-size:12px;background:#e8f0fe;color:#1a73e8}}
.danger{{background:#fce8e6;color:#c5221f}} .ok{{background:#e6f4ea;color:#188038}} .warn{{background:#fef7e0;color:#b06000}}
pre{{white-space:pre-wrap;background:#f8f9fa;border:1px solid #dadce0;border-radius:6px;padding:12px;font-size:12px}}
</style>
</head>
<body><div class="wrap">
<div class="header"><h1>数据分析报告</h1><div class="meta">生成时间：{generated} | 数据行数：{summary.get('rows', 'N/A')} | 新架构：state + facts</div></div>
{_section('经营摘要', _business_summary_html(insights, facts, schema))}
{_section('核心洞察', _insights_html(insights))}
{_section('数据概览', _overview_html(summary, schema))}
{_section('趋势事实', _trends_html(facts.get('trends', [])))}
{_section('异动事实', _anomalies_html(facts))}
{_section('围栏事实', _fences_html(facts.get('fence_violations', [])))}
{_section('归因事实', _attribution_html(facts.get('attributions', [])))}
{_section('指标统计', _stats_html(facts.get('metrics', {})))}
{_section('质量审查', _critic_html(state.get('critic_review', {})))}
{_section('运行记录', _errors_html(state.get('errors', [])))}
</div></body></html>"""


def answer_question(context: Dict[str, Any], question: str) -> str:
    facts = context.get("facts", {})
    summary = context.get("data_profile", {})
    q = question.lower()
    if any(k in q for k in ("异常", "异动", "anomaly")):
        anomalies = facts.get("anomalies", [])
        if not anomalies:
            return "本次分析未检测到单指标异动。"
        return "；".join(
            f"{a['display_name']}在{a.get('period','最新期')}环比{a.get('change_pct',0):+.1f}%，{a.get('detail','')}"
            for a in anomalies[:5]
        )
    if any(k in q for k in ("趋势", "trend", "变化")):
        trends = facts.get("trends", [])
        if not trends:
            return "当前上下文里没有可用趋势事实。"
        top = sorted(trends, key=lambda t: abs(t.get("change_pct") or 0), reverse=True)[:5]
        return "；".join(f"{t['display_name']}最新环比{t.get('change_pct')}%，整体{t.get('overall_trend')}" for t in top)
    if any(k in q for k in ("围栏", "阈值", "越界")):
        fences = facts.get("fence_violations", [])
        return "未发现围栏越界。" if not fences else "；".join(
            f"{f['display_name']}越界{f['violation_count']}条，越界率{f['violation_rate']}%" for f in fences
        )
    if any(k in q for k in ("统计", "均值", "最大", "最小")):
        metrics = facts.get("metrics", {})
        rows = []
        for name, s in list(metrics.items())[:6]:
            rows.append(f"{name}: 均值{s.get('mean')}, 最小{s.get('min')}, 最大{s.get('max')}")
        return "；".join(rows) if rows else "当前上下文里没有指标统计。"
    return (
        f"本次数据共 {summary.get('rows', 0)} 行、{summary.get('columns', 0)} 列，"
        f"生成 {len(context.get('insights', []))} 条洞察、"
        f"{len(facts.get('anomalies', []))} 条异动、"
        f"{len(facts.get('fence_violations', []))} 条围栏越界。"
    )


def _section(title: str, body: str) -> str:
    return f'<section class="section"><h2>{html.escape(title)}</h2>{body}</section>'


def _insights_html(insights: List[Dict[str, Any]]) -> str:
    if not insights:
        return '<p><span class="badge ok">平稳</span> 暂无需要优先关注的洞察。</p>'
    items = "".join(
    f"<li><strong>{html.escape(i['claim'])}</strong><br><span class='meta'>置信度：{html.escape(i['confidence'])} | 建议：{html.escape(i['recommendation'])} | refs: {html.escape(', '.join(i['refs']))}{' | 审查提示：' + html.escape(i.get('review_note', '')) if i.get('review_note') else ''}</span></li>"
        for i in insights
    )
    return f"<ol>{items}</ol>"


def _business_summary_html(insights: List[Dict[str, Any]], facts: Dict[str, Any],
                           schema: Dict[str, Any]) -> str:
    primary = schema.get("primary_metrics") or []
    metric_count = len(facts.get("metrics", {}))
    anomaly_count = len(facts.get("anomalies", []))
    fence_count = len(facts.get("fence_violations", []))
    lead = "本报告基于已确认的指标体系和确定性 facts 自动生成。"
    if insights:
        lead += f" 当前最值得关注的是：{html.escape(insights[0]['claim'])}"
    rows = [
        ("核心指标", ", ".join(primary) if primary else "未指定，使用全部分析指标"),
        ("指标数量", metric_count),
        ("异动数量", anomaly_count),
        ("围栏越界", fence_count),
    ]
    table = "<table><tbody>" + "".join(
        f"<tr><th>{html.escape(str(k))}</th><td>{html.escape(str(v))}</td></tr>"
        for k, v in rows
    ) + "</tbody></table>"
    return f"<p>{lead}</p>{table}"


def _overview_html(summary: Dict[str, Any], schema: Dict[str, Any]) -> str:
    rows = [
        ("行数", summary.get("rows")),
        ("列数", summary.get("columns")),
        ("时间范围", summary.get("date_range")),
        ("时间粒度", summary.get("granularity")),
        ("维度", ", ".join(d.get("display_name", d.get("name", "")) for d in schema.get("dimensions", []))),
        ("指标", ", ".join(m.get("display_name", m.get("name", "")) for m in schema.get("metrics", []))),
        ("派生指标", ", ".join(schema.get("derived_metric_names", []))),
    ]
    return "<table><tbody>" + "".join(f"<tr><th>{html.escape(str(k))}</th><td>{html.escape(str(v))}</td></tr>" for k, v in rows) + "</tbody></table>"


def _trends_html(trends: List[Dict[str, Any]]) -> str:
    if not trends:
        return "<p>暂无趋势事实。</p>"
    rows = "".join(
        f"<tr><td>{html.escape(t['display_name'])}</td><td>{html.escape(t.get('overall_trend',''))}</td><td class='num'>{t.get('latest')}</td><td class='num'>{t.get('change_pct')}</td><td>{t.get('points')}</td></tr>"
        for t in trends
    )
    return f"<table><thead><tr><th>指标</th><th>趋势</th><th>最新值</th><th>环比%</th><th>点数</th></tr></thead><tbody>{rows}</tbody></table>"


def _anomalies_html(facts: Dict[str, Any]) -> str:
    anomalies = facts.get("anomalies", []) + facts.get("cross_anomalies", []) + facts.get("dimension_anomalies", [])
    if not anomalies:
        return '<p><span class="badge ok">正常</span> 未检测到显著异动。</p>'
    return "<pre>" + html.escape(json.dumps(anomalies, ensure_ascii=False, indent=2)) + "</pre>"


def _fences_html(fences: List[Dict[str, Any]]) -> str:
    if not fences:
        return '<p><span class="badge ok">正常</span> 未发现围栏越界。</p>'
    rows = "".join(
        f"<tr><td>{html.escape(f['display_name'])}</td><td class='num'>{f['violation_count']}</td><td class='num'>{f['violation_rate']}</td><td>{html.escape(str(f.get('bounds')))}</td></tr>"
        for f in fences
    )
    return f"<table><thead><tr><th>指标</th><th>越界数</th><th>越界率%</th><th>阈值</th></tr></thead><tbody>{rows}</tbody></table>"


def _attribution_html(items: List[Dict[str, Any]]) -> str:
    if not items:
        return "<p>暂无归因事实。</p>"
    return "<pre>" + html.escape(json.dumps(items[:12], ensure_ascii=False, indent=2)) + "</pre>"


def _stats_html(stats: Dict[str, Dict[str, Any]]) -> str:
    if not stats:
        return "<p>暂无统计事实。</p>"
    rows = "".join(
        f"<tr><td>{html.escape(name)}</td><td class='num'>{s.get('count')}</td><td class='num'>{s.get('mean')}</td><td class='num'>{s.get('median')}</td><td class='num'>{s.get('std')}</td><td class='num'>{s.get('min')}</td><td class='num'>{s.get('max')}</td></tr>"
        for name, s in stats.items()
    )
    return f"<table><thead><tr><th>指标</th><th>计数</th><th>均值</th><th>中位数</th><th>标准差</th><th>最小</th><th>最大</th></tr></thead><tbody>{rows}</tbody></table>"


def _errors_html(errors: List[Dict[str, Any]]) -> str:
    if not errors:
        return '<p><span class="badge ok">OK</span> 所有步骤完成。</p>'
    return "<pre>" + html.escape(json.dumps(errors, ensure_ascii=False, indent=2)) + "</pre>"


def _critic_html(review: Dict[str, Any]) -> str:
    verdicts = review.get("verdicts", []) if isinstance(review, dict) else []
    if not verdicts:
        return "<p>未运行质量审查。</p>"
    rows = "".join(
        f"<tr><td>{html.escape(v.get('insight_id', ''))}</td><td>{html.escape(v.get('status', ''))}</td><td>{html.escape(v.get('suggested_confidence', ''))}</td><td>{html.escape(v.get('issue', ''))}</td></tr>"
        for v in verdicts
    )
    return f"<table><thead><tr><th>洞察</th><th>裁决</th><th>置信度</th><th>说明</th></tr></thead><tbody>{rows}</tbody></table>"
