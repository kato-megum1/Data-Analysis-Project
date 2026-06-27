"""
Skill 1：Schema 解析（纯代码，无 LLM）

输入：state["config"]（用户配置，来自 config_page.html 或 config.json）
输出：state["schema"]（标准化的数据集元信息）

schema 契约（见 REDESIGN_SPEC.md §3）：
{
  "dimensions": [{"name", "display_name", "idx", "type"}],
  "metrics":    [{"name", "display_name", "idx", "agg", "type"}],
  "formulas":   [{"name", "expression", "parts"}],
  "fences":     [{"name", "display_name", "min", "max"}],
  "anomaly_thresholds": {"<metric>": {"down": float|None, "up": float|None}},
  "drill_order": ["<dim>", ...],
  "analysis_metrics": ["<base+derived metric>", ...],   # 趋势/异动/归因的对象
  "fence_metric_names": ["<metric>", ...],
  "derived_metric_names": ["<formula>", ...]
}
"""

import re
from typing import Any, Dict, List

from state import log_error

# 公式表达式里需要剔除的关键字（非列名）
_KEYWORDS = {"and", "or", "not", "if", "else", "sum", "avg", "count", "max", "min"}
# 匹配中英文/下划线/数字组成的标识符（列名）
_IDENT_RE = re.compile(r"[A-Za-z_一-鿿][A-Za-z0-9_一-鿿]*")


def run(state: Dict[str, Any]) -> Dict[str, Any]:
    """流水线入口：解析 config → 写入 state["schema"]。失败则降级为空 schema。"""
    config = state.get("config") or {}
    try:
        state["schema"] = parse_schema(config)
    except Exception as e:  # 解析失败不应中断整条流水线
        log_error(state, "schema", e)
        state["schema"] = {}
    return state


def parse_schema(config: Dict[str, Any]) -> Dict[str, Any]:
    """把用户配置解析为标准化 schema（纯函数，便于单测）。"""
    dimensions = _parse_dimensions(config.get("dimensions", []))
    metrics = _parse_metrics(config.get("metrics", []))
    formulas = _parse_formulas(config.get("formulas", []))

    base_metric_names = [m["name"] for m in metrics]
    derived_names = [f["name"] for f in formulas if f["name"]]
    # 已知名集合：用于校验 fence / anomaly 引用的指标是否存在
    known_metrics = set(base_metric_names) | set(derived_names)

    fences = _parse_fences(config.get("fences", []), metrics, formulas)
    anomaly_thresholds = _parse_anomaly_thresholds(config.get("anomalies", []))

    # 趋势/异动/归因的分析对象 = 原始指标 + 派生指标（围栏只是正交标记，不排除）
    analysis_metrics = base_metric_names + derived_names

    drill_order = [d for d in (config.get("drill_order") or []) if d] \
        or [d["name"] for d in dimensions]

    schema = {
        "dimensions": dimensions,
        "metrics": metrics,
        "formulas": formulas,
        "fences": fences,
        "anomaly_thresholds": anomaly_thresholds,
        "drill_order": drill_order,
        "analysis_metrics": analysis_metrics,
        "fence_metric_names": [f["name"] for f in fences],
        "derived_metric_names": derived_names,
        "primary_metrics": [m for m in config.get("primary_metrics", []) if m in analysis_metrics],
        "metric_groups": config.get("metric_groups", {}) if isinstance(config.get("metric_groups", {}), dict) else {},
        "metric_system": config.get("metric_system", {}) if isinstance(config.get("metric_system", {}), dict) else {},
        # 业务背景 / 字段说明（供 Interpreter/Report 使用，可选）
        "business_context": config.get("background", "") or config.get("business_context", ""),
    }

    schema["warnings"] = _validate(schema, known_metrics, dimensions)
    return schema


# ---------------------------------------------------------------- 解析子函数

def _parse_dimensions(raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    dims = []
    for d in raw:
        name = d.get("name", "")
        if not name:
            continue
        dims.append({
            "idx": d.get("idx"),
            "name": name,
            "display_name": d.get("displayName") or d.get("display_name") or name,
            "type": "category",
        })
    return dims


def _parse_metrics(raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    metrics = []
    for m in raw:
        name = m.get("name", "")
        if not name:
            continue
        metrics.append({
            "idx": m.get("idx"),
            "name": name,
            "display_name": m.get("displayName") or m.get("display_name") or name,
            "type": "numeric",
            "agg": m.get("agg", "sum"),
        })
    return metrics


def _parse_formulas(raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    formulas = []
    for f in raw:
        expr = f.get("expression", "")
        formulas.append({
            "name": f.get("name", ""),
            "expression": expr,
            "parts": _extract_parts(expr),
        })
    return formulas


def _parse_fences(raw: List[Dict[str, Any]],
                  metrics: List[Dict[str, Any]],
                  formulas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    display_map = {m["name"]: m["display_name"] for m in metrics}
    display_map.update({f["name"]: f["name"] for f in formulas if f["name"]})
    fences = []
    for f in raw:
        name = f.get("name") or f.get("metric") or ""
        if not name:
            continue
        fences.append({
            "name": name,
            "display_name": display_map.get(name, name),
            "min": f.get("min"),
            "max": f.get("max"),
        })
    return fences


def _parse_anomaly_thresholds(raw: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    thresholds = {}
    for a in raw:
        name = a.get("name") or a.get("metric") or ""
        if not name:
            continue
        thresholds[name] = {
            "down": a.get("downThreshold"),
            "up": a.get("upThreshold"),
        }
    return thresholds


def _extract_parts(expression: str) -> List[str]:
    """提取公式表达式里引用的列名（剔除运算关键字）。"""
    parts = _IDENT_RE.findall(expression or "")
    return [p for p in parts if p.lower() not in _KEYWORDS]


def _validate(schema: Dict[str, Any], known_metrics: set,
              dimensions: List[Dict[str, Any]]) -> List[str]:
    """轻量校验：引用了不存在的指标/维度时给出告警（不抛异常）。"""
    warnings: List[str] = []
    dim_names = {d["name"] for d in dimensions}

    # 围栏指标必须存在
    for f in schema["fences"]:
        if f["name"] not in known_metrics:
            warnings.append(f"围栏指标 '{f['name']}' 不在指标/派生指标中，将被忽略")

    # 异动阈值指标必须存在
    for name in schema["anomaly_thresholds"]:
        if name not in known_metrics:
            warnings.append(f"异动阈值指标 '{name}' 不在指标/派生指标中")

    # 公式引用的列必须是已知指标（派生可引用其他派生/原始指标）
    for f in schema["formulas"]:
        for part in f["parts"]:
            if part not in known_metrics:
                warnings.append(f"公式 '{f['name']}' 引用了未知列 '{part}'")

    # 下钻顺序里的维度必须存在
    for d in schema["drill_order"]:
        if d not in dim_names:
            warnings.append(f"下钻维度 '{d}' 不在已配置维度中")

    return warnings


# ---------------------------------------------------------------- 工具函数

def display_name(schema: Dict[str, Any], name: str) -> str:
    """按指标/派生指标名取展示名，找不到则原样返回。"""
    for m in schema.get("metrics", []):
        if m["name"] == name:
            return m["display_name"]
    for f in schema.get("formulas", []):
        if f["name"] == name:
            return name
    return name
