"""Report orchestration from facts, plan and insight candidates."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from pipeline.report_renderer import render_report


class ReportOrchestrator:
    def __init__(self, llm: Any = None):
        self.llm = llm

    def run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        structured = build_structured_report(state)
        html = render_report(structured)
        return {"structured_report": structured, "html": html}


def build_structured_report(state: Dict[str, Any]) -> Dict[str, Any]:
    schema = state.get("schema", {})
    data = state.get("data", {})
    facts = state.get("facts", {})
    config = state.get("config", {})
    plan = state.get("analysis_plan", {})
    candidates = state.get("insight_candidates", []) or state.get("final_insights", []) or []
    appendix = build_evidence_tables(facts)
    evidence_ids = [t["id"] for t in appendix[:3]]
    methods = [m.get("name") for m in plan.get("modules", []) if m.get("name")]

    title = config.get("report_title") or "数据分析报告"
    subtitle = f"{plan.get('goal') or '围绕核心指标、趋势、异常和归因生成的经营分析报告'}"
    row_count = data.get("summary", {}).get("rows", "-")

    sections = [
        {
            "heading": "一页纸结论",
            "scope": _scope(data, schema),
            "blocks": [
                _conclusion_block(c, appendix) for c in candidates[:4]
            ] or [{
                "type": "paragraph",
                "text": "当前 facts 中没有检测到需要优先关注的显著洞察，建议持续监控核心指标。",
            }],
        },
        {
            "heading": "关键发现",
            "scope": _scope(data, schema),
            "blocks": _key_finding_blocks(candidates, appendix),
        },
        {
            "heading": "趋势与异常",
            "scope": "基于配置中的时间维度和分析指标计算趋势、单指标异动、跨指标背离和维度切片异常。",
            "blocks": _trend_anomaly_blocks(facts),
        },
        {
            "heading": "归因与下钻",
            "scope": "基于可计算的派生指标、维度切片和贡献度结果解释变化来源；缺少成本、活动、库存等字段时不做强因果判断。",
            "blocks": _attribution_blocks(facts),
        },
        {
            "heading": "行动建议",
            "scope": "建议仅基于当前数据可支持的趋势、异常、阈值和归因事实。",
            "blocks": [{
                "type": "actions",
                "items": _actions(candidates, facts),
            }],
        },
    ]

    return {
        "title": title,
        "subtitle": subtitle,
        "meta": {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "file_name": config.get("file_name", ""),
            "row_count": row_count,
            "methods": methods,
            "evidence_ids": evidence_ids,
        },
        "sections": sections,
        "appendix_tables": appendix,
    }


def build_evidence_tables(facts: Dict[str, Any]) -> List[Dict[str, Any]]:
    tables: List[Dict[str, Any]] = []
    trends = facts.get("trends", [])
    if trends:
        tables.append({
            "id": "A1",
            "title": "核心指标趋势与最新变化",
            "columns": ["指标", "趋势", "最新值", "上期值", "环比%", "事实ID"],
            "rows": [{
                "指标": t.get("display_name", t.get("metric")),
                "趋势": t.get("overall_trend"),
                "最新值": t.get("latest"),
                "上期值": t.get("previous"),
                "环比%": t.get("change_pct"),
                "事实ID": t.get("id"),
            } for t in trends],
        })
    anomalies = facts.get("anomalies", []) + facts.get("cross_anomalies", []) + facts.get("dimension_anomalies", [])
    if anomalies:
        tables.append({
            "id": "A2",
            "title": "异常与背离事实",
            "columns": ["类型", "对象", "周期/切片", "严重度", "说明", "事实ID"],
            "rows": [_anomaly_row(a) for a in anomalies],
        })
    fences = facts.get("fence_violations", [])
    if fences:
        tables.append({
            "id": "A3",
            "title": "规则与阈值越界",
            "columns": ["指标", "越界数", "越界率%", "阈值", "事实ID"],
            "rows": [{
                "指标": f.get("display_name", f.get("metric")),
                "越界数": f.get("violation_count"),
                "越界率%": f.get("violation_rate"),
                "阈值": _bounds(f.get("bounds", {})),
                "事实ID": f.get("id"),
            } for f in fences],
        })
    attrs = facts.get("attributions", [])
    if attrs:
        tables.append({
            "id": "A4",
            "title": "归因与贡献",
            "columns": ["指标", "方法", "主要贡献", "贡献占比%", "说明", "事实ID"],
            "rows": [_attr_row(a) for a in attrs],
        })
    metrics = facts.get("metrics", {})
    if metrics:
        tables.append({
            "id": "A5",
            "title": "指标描述统计",
            "columns": ["指标", "计数", "均值", "中位数", "最小值", "最大值"],
            "rows": [{
                "指标": name,
                "计数": s.get("count"),
                "均值": s.get("mean"),
                "中位数": s.get("median"),
                "最小值": s.get("min"),
                "最大值": s.get("max"),
            } for name, s in metrics.items()],
        })
    return tables


def _conclusion_block(candidate: Dict[str, Any], tables: List[Dict[str, Any]]) -> Dict[str, Any]:
    evidence = _evidence_for_refs(candidate.get("evidence_fact_ids") or candidate.get("refs", []), tables)
    return {
        "type": "conclusion",
        "title": _type_label(candidate.get("type", "insight")),
        "text": _with_evidence(candidate.get("claim", ""), evidence),
        "confidence": candidate.get("confidence", "medium"),
        "evidence_ids": evidence,
    }


def _key_finding_blocks(candidates: List[Dict[str, Any]], tables: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    blocks = []
    for c in candidates[:6]:
        blocks.append(_conclusion_block(c, tables))
        if c.get("action_hint"):
            blocks.append({"type": "paragraph", "text": f"建议方向：{c.get('action_hint')}"})
    return blocks or [{"type": "paragraph", "text": "暂无显著关键发现。"}]


def _trend_anomaly_blocks(facts: Dict[str, Any]) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = []
    trends = facts.get("trends", [])
    if trends:
        blocks.append({
            "type": "table",
            "columns": ["指标", "趋势", "最新值", "上期值", "环比%"],
            "rows": [{
                "指标": t.get("display_name", t.get("metric")),
                "趋势": t.get("overall_trend"),
                "最新值": t.get("latest"),
                "上期值": t.get("previous"),
                "环比%": t.get("change_pct"),
            } for t in trends[:12]],
        })
    anomalies = facts.get("anomalies", []) + facts.get("cross_anomalies", []) + facts.get("dimension_anomalies", [])
    if anomalies:
        blocks.append({
            "type": "table",
            "columns": ["类型", "对象", "周期/切片", "严重度", "说明"],
            "rows": [_anomaly_row(a) for a in anomalies[:12]],
        })
    if not blocks:
        blocks.append({"type": "paragraph", "text": "未检测到显著趋势或异常事实。"})
    return blocks


def _attribution_blocks(facts: Dict[str, Any]) -> List[Dict[str, Any]]:
    attrs = facts.get("attributions", [])
    if not attrs:
        return [{"type": "paragraph", "text": "当前 facts 中没有可用归因结果。"}]
    return [{
        "type": "table",
        "columns": ["指标", "方法", "主要贡献", "贡献占比%", "说明"],
        "rows": [_attr_row(a) for a in attrs[:12]],
    }]


def _actions(candidates: List[Dict[str, Any]], facts: Dict[str, Any]) -> List[str]:
    items = []
    for c in candidates[:5]:
        if c.get("action_hint"):
            items.append(c["action_hint"])
    if facts.get("fence_violations"):
        items.append("复核阈值越界样本，优先处理越界率较高或业务影响较大的指标。")
    if facts.get("dimension_anomalies"):
        items.append("对异常维度切片做样本回看，确认是业务变化还是数据质量问题。")
    return list(dict.fromkeys(items)) or ["持续监控核心指标，补充业务动作、活动、库存、成本等外部信息以增强归因。"]


def _scope(data: Dict[str, Any], schema: Dict[str, Any]) -> str:
    summary = data.get("summary", {})
    dims = ", ".join(d.get("display_name", d.get("name", "")) for d in schema.get("dimensions", [])[:5]) or "未配置维度"
    metrics = ", ".join(m.get("display_name", m.get("name", "")) for m in schema.get("metrics", [])[:5]) or "未配置指标"
    return f"本模块基于 {summary.get('rows', 'N/A')} 行数据；维度优先看 {dims}；指标优先看 {metrics}。"


def _evidence_for_refs(refs: List[str], tables: List[Dict[str, Any]]) -> List[str]:
    out = []
    for table in tables:
        for row in table.get("rows", []):
            if isinstance(row, dict) and row.get("事实ID") in refs and table["id"] not in out:
                out.append(table["id"])
    return out or ([tables[0]["id"]] if tables else [])


def _with_evidence(text: str, evidence: List[str]) -> str:
    if not evidence:
        return text
    return f"{text} [{' ,'.join('Data ' + e for e in evidence)}]"


def _anomaly_row(a: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "类型": a.get("type", "metric_anomaly"),
        "对象": a.get("display_name") or a.get("metric") or "/".join(a.get("metrics", [])),
        "周期/切片": a.get("period") or a.get("slice_value") or "",
        "严重度": a.get("severity", ""),
        "说明": a.get("detail") or _compact_anomaly(a),
        "事实ID": a.get("id"),
    }


def _attr_row(a: Dict[str, Any]) -> Dict[str, Any]:
    contribs = a.get("contributions", [])
    top = contribs[0] if contribs else {}
    top_contributors = a.get("top_contributors", [])
    if top_contributors and not top:
        top = {"factor": top_contributors[0].get("value"), "pct": top_contributors[0].get("share_pct"), "detail": "维度贡献占比最高。"}
    return {
        "指标": a.get("metric"),
        "方法": a.get("method"),
        "主要贡献": top.get("factor", ""),
        "贡献占比%": top.get("pct", ""),
        "说明": top.get("detail", ""),
        "事实ID": a.get("id"),
    }


def _compact_anomaly(a: Dict[str, Any]) -> str:
    if a.get("change_pct") is not None:
        return f"环比变化 {a.get('change_pct'):+.1f}%"
    if a.get("z") is not None:
        return f"切片均值 {a.get('slice_mean')}，整体均值 {a.get('overall_mean')}，z={a.get('z')}"
    return "检测到异常或背离。"


def _bounds(bounds: Dict[str, Any]) -> str:
    return f"{bounds.get('min', '-')} 至 {bounds.get('max', '-')}"


def _type_label(kind: str) -> str:
    return {
        "metric_anomaly": "指标异动",
        "cross_anomaly": "跨指标背离",
        "dimension_anomaly": "维度异常",
        "rule_check": "规则阈值",
        "attribution": "归因发现",
        "trend": "趋势变化",
    }.get(kind, "关键洞察")
