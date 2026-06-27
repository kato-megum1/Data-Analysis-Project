"""Deterministic HTML renderer for structured reports."""

from __future__ import annotations

import html
from datetime import datetime
from typing import Any, Dict, List


def render_report(report: Dict[str, Any]) -> str:
    title = report.get("title") or "数据分析报告"
    subtitle = report.get("subtitle") or "基于当前配置和 facts 自动生成"
    meta = report.get("meta", {})
    sections = report.get("sections", [])
    appendix = report.get("appendix_tables", [])
    generated = meta.get("generated_at") or datetime.now().strftime("%Y-%m-%d %H:%M")

    toc = "".join(
        f'<li><a href="#section-{idx}">{idx}. {esc(section.get("heading", ""))}</a></li>'
        for idx, section in enumerate(sections, 1)
    )
    body = "".join(_section_html(section, idx) for idx, section in enumerate(sections, 1))
    appendix_html = _appendix_html(appendix)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<style>
:root{{--page:#edf1f7;--paper:#fff;--ink:#111827;--soft:#344054;--muted:#667085;--line:#d9e0ea;--accent:#1d4ed8;--soft-bg:#f8fafc;--red:#b42318;--green:#157347;--amber:#b25e09}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--page);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",Arial,sans-serif;line-height:1.68;letter-spacing:0}}
.paper{{width:min(1160px,calc(100vw - 40px));margin:32px auto;background:var(--paper);border:1px solid var(--line);box-shadow:0 24px 80px rgba(16,24,40,.14)}}
.cover{{padding:52px 72px 32px;border-bottom:1px solid var(--line);background:linear-gradient(90deg,rgba(29,78,216,.08),rgba(255,255,255,0) 44%),#fff;position:relative}}
.cover:before{{content:"";position:absolute;left:0;right:0;top:0;height:6px;background:linear-gradient(90deg,#1d4ed8,#2563eb 42%,#0891b2 74%,#16a34a)}}
.kicker{{color:var(--accent);font-size:12px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;margin-bottom:14px}}
h1{{font-size:38px;line-height:1.16;margin:0;font-weight:820}} .subtitle{{max-width:820px;color:var(--soft);font-size:15px;margin:16px 0 0}}
.meta{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-top:28px}} .meta-card{{border:1px solid var(--line);border-radius:6px;padding:12px 14px;background:#fff}}
.meta-label{{color:var(--muted);font-size:12px;font-weight:650}} .meta-value{{margin-top:5px;font-size:14px;font-weight:780;overflow-wrap:anywhere}}
.content{{padding:32px 72px 64px}} .toc{{display:grid;grid-template-columns:160px 1fr;gap:18px;margin-bottom:32px;padding:18px 20px;border:1px solid var(--line);border-radius:6px;background:var(--soft-bg)}}
.toc h2{{font-size:15px;margin:0}} .toc ol{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px 22px;margin:0;padding-left:20px;color:var(--muted);font-size:13px}} .toc a{{color:var(--soft);text-decoration:none}}
section{{margin-top:28px;padding-top:30px;border-top:1px solid var(--line);break-inside:avoid}} section:first-of-type{{margin-top:0}}
h2{{display:flex;align-items:center;gap:10px;margin:0 0 16px;font-size:22px;line-height:1.32}} h2:before{{content:"";width:5px;height:22px;border-radius:3px;background:var(--accent);flex:0 0 auto}}
h3{{font-size:16px;margin:22px 0 10px}} p{{margin:0 0 12px;color:var(--soft);font-size:14px}}
.finding{{position:relative;margin:14px 0;padding:15px 18px 15px 20px;border:1px solid var(--line);border-radius:6px;background:#fff}} .finding:before{{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--accent)}}
.finding-title{{display:flex;justify-content:space-between;gap:12px;margin-bottom:8px;font-size:14px;font-weight:820}} .badge{{display:inline-flex;align-items:center;min-height:22px;padding:2px 8px;border-radius:999px;background:#e8efff;color:var(--accent);font-size:11px;font-weight:780;white-space:nowrap}}
.actions li,.bullets li{{margin-bottom:8px;color:var(--soft);font-size:14px}}
table{{width:100%;border-collapse:separate;border-spacing:0;margin:16px 0 20px;border:1px solid var(--line);border-radius:6px;overflow:hidden;font-size:13px}} th,td{{padding:9px 11px;border-right:1px solid var(--line);border-bottom:1px solid var(--line);text-align:left;vertical-align:top}} th:last-child,td:last-child{{border-right:0}} tr:last-child td{{border-bottom:0}} th{{background:#eef3fb;color:#24324b;font-weight:760}} td{{color:var(--soft);background:#fff}} tr:nth-child(even) td{{background:#fbfcff}} .num{{text-align:right;font-variant-numeric:tabular-nums}}
.scope{{padding:12px 14px;border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:6px;background:#f8fbff;color:var(--soft);font-size:14px}}
.footer{{display:flex;justify-content:space-between;gap:18px;border-top:1px solid var(--line);color:var(--muted);font-size:12px;padding:18px 72px;background:#fbfcff}}
@media print{{body{{background:#fff}}.paper{{width:100%;margin:0;border:0;box-shadow:none}}.cover,.content,.footer{{padding-left:28px;padding-right:28px}}section,.finding,table{{break-inside:avoid}}}}
@media(max-width:860px){{.paper{{width:min(100vw,calc(100vw - 20px));margin:10px auto}}.cover,.content,.footer{{padding-left:20px;padding-right:20px}}h1{{font-size:28px}}.meta{{grid-template-columns:1fr 1fr}}.toc{{grid-template-columns:1fr}}.toc ol{{grid-template-columns:1fr}}}}
</style>
</head>
<body><main class="paper">
<header class="cover">
<div class="kicker">Analysis Report</div>
<h1>{esc(title)}</h1>
<p class="subtitle">{esc(subtitle)}</p>
<div class="meta">
{_meta_card("生成时间", generated)}
{_meta_card("数据文件", meta.get("file_name", "-"))}
{_meta_card("记录数", meta.get("row_count", "-"))}
{_meta_card("分析方式", ", ".join(meta.get("methods", [])[:3]) or "-")}
</div>
</header>
<div class="content"><nav class="toc"><h2>目录</h2><ol>{toc}<li><a href="#appendix">附录数据</a></li></ol></nav>{body}{appendix_html}</div>
<footer class="footer"><span>报告由 Analysis Agent 生成，结论基于结构化 facts 和证据表。</span><span>可直接打印或另存为 PDF。</span></footer>
</main></body></html>"""


def _section_html(section: Dict[str, Any], idx: int) -> str:
    blocks = section.get("blocks", [])
    parts = [f'<section id="section-{idx}"><h2>{idx}. {esc(section.get("heading", ""))}</h2>']
    scope = section.get("scope")
    if scope:
        parts.append(f'<p class="scope"><strong>统计口径说明：</strong>{esc(scope)}</p>')
    for block in blocks:
        kind = block.get("type")
        if kind == "paragraph":
            parts.append(f"<p>{esc(block.get('text', ''))}</p>")
        elif kind == "conclusion":
            parts.append(_finding_html(block))
        elif kind == "bullets":
            parts.append("<ul class=\"bullets\">" + "".join(f"<li>{esc(x)}</li>" for x in block.get("items", [])) + "</ul>")
        elif kind == "actions":
            parts.append("<ol class=\"actions\">" + "".join(f"<li>{esc(x)}</li>" for x in block.get("items", [])) + "</ol>")
        elif kind == "table":
            parts.append(_table_html(block.get("columns", []), block.get("rows", [])))
    parts.append("</section>")
    return "\n".join(parts)


def _finding_html(block: Dict[str, Any]) -> str:
    confidence = block.get("confidence", "medium")
    evidence = ", ".join(f"Data {x}" for x in block.get("evidence_ids", []))
    return (
        '<div class="finding">'
        f'<div class="finding-title">{esc(block.get("title", "关键结论"))}<span class="badge">{esc(confidence)}</span></div>'
        f'<p>{esc(block.get("text", ""))}</p>'
        f'<p><span class="badge">{esc(evidence or "No evidence")}</span></p>'
        '</div>'
    )


def _appendix_html(tables: List[Dict[str, Any]]) -> str:
    parts = ['<section id="appendix"><h2>附录数据</h2>']
    if not tables:
        parts.append("<p>暂无附录证据表。</p>")
    for table in tables:
        parts.append(f'<h3>Data {esc(table.get("id", ""))}: {esc(table.get("title", ""))}</h3>')
        if table.get("note"):
            parts.append(f"<p>{esc(table.get('note'))}</p>")
        parts.append(_table_html(table.get("columns", []), table.get("rows", [])))
    parts.append("</section>")
    return "\n".join(parts)


def _table_html(columns: List[str], rows: List[Any]) -> str:
    if not columns:
        return "<p>暂无数据。</p>"
    head = "".join(f"<th>{esc(col)}</th>" for col in columns)
    body_rows = []
    for row in rows[:50]:
        if isinstance(row, dict):
            cells = [row.get(col, "") for col in columns]
        else:
            cells = list(row)[:len(columns)]
        body_rows.append("<tr>" + "".join(f"<td>{esc(_fmt(cell))}</td>" for cell in cells) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def _meta_card(label: str, value: Any) -> str:
    return f'<div class="meta-card"><div class="meta-label">{esc(label)}</div><div class="meta-value">{esc(_fmt(value))}</div></div>'


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def esc(value: Any) -> str:
    return html.escape(_fmt(value), quote=True)
