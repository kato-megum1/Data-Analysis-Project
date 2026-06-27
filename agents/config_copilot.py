"""Natural language config adjustment via safe patches."""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List

from pipeline.schema import parse_schema


SUPPORTED_OPS = {
    "set_field_type", "set_metric_agg", "add_formula", "remove_formula",
    "upsert_fence", "remove_fence", "upsert_anomaly_threshold",
    "set_drill_order", "set_primary_metrics", "set_metric_group",
    "rename_display_name",
}


class ConfigCopilot:
    def __init__(self, llm: Any = None):
        self.llm = llm

    def propose_patch(self, message: str, current_config: Dict[str, Any],
                      metric_system: Dict[str, Any]) -> Dict[str, Any]:
        patch: List[Dict[str, Any]] = []
        warnings: List[str] = []

        if self.llm is not None:
            try:
                raw = self._llm_patch(message, current_config, metric_system)
                patch = normalize_patch(raw.get("patch", []))
            except Exception as e:
                warnings.append(f"LLM 配置助手不可用，已使用规则解析: {e}")

        if not patch:
            patch = heuristic_patch(message, current_config)
            if not patch:
                warnings.append("未识别到可执行的配置修改，请换一种更具体的说法。")

        updated, apply_warnings = apply_patch_to_config(current_config, patch)
        warnings.extend(apply_warnings)
        return {
            "reply": build_reply(patch, warnings),
            "patch": patch,
            "updated_config": updated,
            "warnings": warnings,
        }

    def _llm_patch(self, message: str, current_config: Dict[str, Any],
                   metric_system: Dict[str, Any]) -> Dict[str, Any]:
        import json

        system = (
            "你是配置对话助手。只输出 JSON，不要重写完整配置。"
            "把用户自然语言转换为 patch 数组。"
            f"允许操作: {sorted(SUPPORTED_OPS)}。"
            "所有字段名/指标名必须来自 current_config 或 metric_system。"
        )
        user = json.dumps({
            "message": message,
            "current_config": compact_config(current_config),
            "metric_system": metric_system,
            "output_schema": {"patch": [{"op": "string"}]},
        }, ensure_ascii=False)
        return self.llm.structured_call(system, user, temperature=0.1, max_tokens=1024)


def compact_config(config: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "dimensions": config.get("dimensions", []),
        "metrics": config.get("metrics", []),
        "formulas": config.get("formulas", []),
        "fences": config.get("fences", []),
        "anomalies": config.get("anomalies", []),
        "drill_order": config.get("drill_order", []),
        "primary_metrics": config.get("primary_metrics", []),
        "metric_groups": config.get("metric_groups", {}),
    }


def normalize_patch(items: Any) -> List[Dict[str, Any]]:
    out = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and item.get("op") in SUPPORTED_OPS:
            out.append(item)
    return out


def heuristic_patch(message: str, config: Dict[str, Any]) -> List[Dict[str, Any]]:
    msg = message.strip()
    patch: List[Dict[str, Any]] = []
    known = known_names(config)

    primary_names = []
    for name in known:
        if name and re.search(re.escape(name) + r".{0,8}(核心|重点|主要)", msg):
            primary_names.append(name)
    if primary_names:
        patch.append({"op": "set_primary_metrics", "value": primary_names})

    fence_match = re.search(r"([\w\u4e00-\u9fff]{1,20}?)(?:阈值|围栏).*?(-?\d+(?:\.\d+)?)\s*%?\s*(?:到|至|-|~)\s*(-?\d+(?:\.\d+)?)\s*%?", msg)
    if fence_match:
        metric = resolve_name(fence_match.group(1), known) or fence_match.group(1)
        if metric:
            lo = parse_number(fence_match.group(2))
            hi = parse_number(fence_match.group(3))
            if "%" in fence_match.group(0) or lo > 1 or hi > 1:
                lo, hi = lo / 100, hi / 100
            patch.append({"op": "upsert_fence", "metric": metric, "min": lo, "max": hi})

    if re.search(r"不要|移除|删除|不分析", msg):
        for name in known:
            if name and name in msg:
                patch.append({"op": "remove_metric", "metric": name})

    if re.search(r"下钻|顺序", msg):
        order = [name for name in known_dimension_names(config) if name in msg]
        if order:
            patch.append({"op": "set_drill_order", "value": order})

    return [p for p in patch if p.get("op") != "remove_metric"] + [
        {"op": "set_field_type", "field": p["metric"], "type": "ignore"}
        for p in patch if p.get("op") == "remove_metric"
    ]


def apply_patch_to_config(config: Dict[str, Any], patch: List[Dict[str, Any]]) -> tuple[Dict[str, Any], List[str]]:
    updated = copy.deepcopy(config)
    warnings: List[str] = []

    for op in patch:
        try:
            apply_one(updated, op, warnings)
        except Exception as e:
            warnings.append(f"操作 {op.get('op')} 未应用: {e}")

    try:
        parse_schema(updated)
    except Exception as e:
        warnings.append(f"配置校验失败: {e}")
    return updated, warnings


def apply_one(config: Dict[str, Any], op: Dict[str, Any], warnings: List[str]) -> None:
    kind = op.get("op")
    if kind == "set_field_type":
        field = op.get("field")
        target = op.get("type")
        move_field(config, field, target)
    elif kind == "set_metric_agg":
        for metric in config.get("metrics", []):
            if metric["name"] == op.get("metric"):
                metric["agg"] = op.get("agg", metric.get("agg", "sum"))
    elif kind == "add_formula":
        upsert_by_name(config.setdefault("formulas", []), {"name": op.get("name"), "expression": op.get("expression")})
    elif kind == "remove_formula":
        config["formulas"] = [f for f in config.get("formulas", []) if f.get("name") != op.get("name")]
    elif kind == "upsert_fence":
        upsert_by_name(config.setdefault("fences", []), {"name": op.get("metric"), "min": op.get("min"), "max": op.get("max")})
    elif kind == "remove_fence":
        config["fences"] = [f for f in config.get("fences", []) if f.get("name") != op.get("metric")]
    elif kind == "upsert_anomaly_threshold":
        upsert_by_name(config.setdefault("anomalies", []), {
            "name": op.get("metric"),
            "downThreshold": op.get("downThreshold"),
            "upThreshold": op.get("upThreshold"),
        })
    elif kind == "set_drill_order":
        config["drill_order"] = [x for x in op.get("value", []) if x in known_dimension_names(config)]
    elif kind == "set_primary_metrics":
        config["primary_metrics"] = [x for x in op.get("value", []) if x in known_names(config)]
    elif kind == "set_metric_group":
        config.setdefault("metric_groups", {}).setdefault(op.get("group", "其他指标"), [])
        config["metric_groups"][op.get("group", "其他指标")] = op.get("metrics", [])
    elif kind == "rename_display_name":
        for item in config.get("dimensions", []) + config.get("metrics", []):
            if item.get("name") == op.get("field"):
                item["displayName"] = op.get("displayName", item.get("displayName", item.get("name")))


def move_field(config: Dict[str, Any], field: str, target: str) -> None:
    dims = config.setdefault("dimensions", [])
    metrics = config.setdefault("metrics", [])
    found = None
    for coll in (dims, metrics):
        for item in list(coll):
            if item.get("name") == field:
                found = item
                coll.remove(item)
                break
    if not found:
        return
    if target == "dimension":
        dims.append({"idx": found.get("idx"), "name": field, "displayName": found.get("displayName", field), "type": "dimension"})
    elif target == "metric":
        metrics.append({"idx": found.get("idx"), "name": field, "displayName": found.get("displayName", field), "agg": found.get("agg", "sum")})


def upsert_by_name(items: List[Dict[str, Any]], item: Dict[str, Any]) -> None:
    name = item.get("name")
    if not name:
        return
    for idx, old in enumerate(items):
        if old.get("name") == name:
            items[idx] = {**old, **{k: v for k, v in item.items() if v is not None}}
            return
    items.append({k: v for k, v in item.items() if v is not None})


def known_dimension_names(config: Dict[str, Any]) -> List[str]:
    return [d.get("name", "") for d in config.get("dimensions", [])]


def known_names(config: Dict[str, Any]) -> List[str]:
    names = [d.get("name", "") for d in config.get("dimensions", [])]
    names += [m.get("name", "") for m in config.get("metrics", [])]
    names += [f.get("name", "") for f in config.get("formulas", [])]
    return names


def resolve_name(text: str, names: List[str]) -> str:
    for name in names:
        if name and name in text:
            return name
    return ""


def parse_number(text: str) -> float:
    return float(text)


def build_reply(patch: List[Dict[str, Any]], warnings: List[str]) -> str:
    if patch and not warnings:
        return f"已应用 {len(patch)} 项配置修改。"
    if patch:
        return f"已尝试应用 {len(patch)} 项配置修改，其中有 {len(warnings)} 条提示需要确认。"
    return "我没有找到可以安全执行的配置修改。请指定字段、指标或阈值。"
