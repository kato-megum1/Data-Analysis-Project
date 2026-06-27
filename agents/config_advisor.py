"""
ConfigAdvisor (Layer 0, 🤖 LLM + 启发式兜底)

定位：分析流水线之前的「配置草拟」助手。
  原始数据 + 字段说明 + 业务背景  →  配置草稿（dimensions/metrics/formulas/fences/anomalies）
草稿交给前端配置向导，由人工修改确认后定稿，再进入 Step 1 (Schema 解析)。

设计原则（见 REDESIGN_SPEC.md）：
  - 零业务硬编码：不认识任何具体列名/行业，全部从数据特征推断。
  - LLM 用结构化输出（llm.structured_call），失败则自动降级到纯代码启发式。
  - 输出格式与「人工填写的 config」完全一致，下游 Step 1 不区分来源。
  - 草稿只是建议，formulas/fences/anomalies 这类业务规则交给人/LLM，
    启发式兜底只做能确定性判断的部分（维度 vs 指标、下钻顺序）。
"""

import re
from typing import Any, Dict, List, Optional

import pandas as pd

_DATE_RE = re.compile(r"^\s*\d{4}[-/.]\d{1,2}[-/.]\d{1,2}")


class ConfigAdvisor:
    """看原始数据，草拟一份分析配置。"""

    def __init__(self, llm: Any = None):
        # llm 需实现 structured_call(system, user) -> dict；为空则只用启发式
        self.llm = llm

    def suggest(self, df: pd.DataFrame, field_doc: str = "",
                background: str = "") -> Dict[str, Any]:
        """返回配置草稿。优先 LLM，失败/空则启发式兜底。"""
        profile = profile_columns(df)

        if self.llm is not None:
            try:
                draft = self._llm_suggest(profile, field_doc, background)
                draft = normalize_draft(draft, df)
                if draft.get("dimensions") or draft.get("metrics"):
                    draft["source"] = "llm"
                    return draft
            except Exception as e:
                heur = heuristic_suggest(df, profile)
                heur["reasoning"] = f"LLM 不可用，已启发式兜底（{e}）。" + heur["reasoning"]
                heur["source"] = "heuristic_fallback"
                return heur

        draft = heuristic_suggest(df, profile)
        draft["source"] = "heuristic"
        return draft

    # ------------------------------------------------------------ LLM 路径

    def _llm_suggest(self, profile: Dict[str, Any], field_doc: str,
                     background: str) -> Dict[str, Any]:
        system = (
            "你是资深数据工程师。根据给定的数据列画像，推断这张表应如何配置分析："
            "区分维度与指标、推荐派生公式、围栏阈值、异动阈值、下钻顺序。"
            "只依据数据本身和用户提供的背景，不要臆造不存在的列。"
            "严格输出 JSON 对象，不要输出多余文字。"
        )
        user = _build_user_prompt(profile, field_doc, background)
        return self.llm.structured_call(system, user, temperature=0.2, max_tokens=2048)


# ==================================================================== 纯函数

def profile_columns(df: pd.DataFrame) -> Dict[str, Any]:
    """计算每列的画像（dtype/基数/缺失/样本/数值范围），供 LLM 与启发式共用。"""
    cols: List[Dict[str, Any]] = []
    n = len(df)
    for i, col in enumerate(df.columns):
        s = df[col]
        nunique = int(s.nunique(dropna=True))
        info: Dict[str, Any] = {
            "idx": i,
            "name": str(col),
            "dtype": _dtype_label(s),
            "rows": n,
            "null_count": int(s.isna().sum()),
            "unique_count": nunique,
            "unique_ratio": round(nunique / n, 4) if n else 0.0,
            "samples": [_scalar(v) for v in s.dropna().head(5).tolist()],
        }
        # 类日期文本（此阶段日期尚未转 datetime，datetime 转换在 ETL 做）
        info["is_datelike"] = (info["dtype"] == "datetime"
                               or _samples_look_like_date(info["samples"]))
        if pd.api.types.is_numeric_dtype(s) and s.notna().any():
            info["min"] = _scalar(s.min())
            info["max"] = _scalar(s.max())
            info["mean"] = round(float(s.mean()), 4)
            info["is_integer"] = bool((s.dropna() % 1 == 0).all())
        cols.append(info)
    return {"columns": cols, "total_rows": n, "column_count": len(df.columns)}


def heuristic_suggest(df: pd.DataFrame, profile: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    纯代码启发式：仅做可确定性判断的部分。
      - 维度：日期列 / 类日期文本 / 低基数文本 / 低基数数值（状态码）
      - 指标：其余数值列（agg 默认 sum；疑似比率→avg）
      - 下钻顺序：时间维优先，其余按基数升序（粗→细）
      - formulas/fences/anomalies 留空（业务规则交给人/LLM）
    """
    profile = profile or profile_columns(df)
    dims: List[Dict[str, Any]] = []
    metrics: List[Dict[str, Any]] = []

    for c in profile["columns"]:
        name, idx = c["name"], c["idx"]
        if _is_dimension(c):
            dims.append({"idx": idx, "name": name, "displayName": name, "type": "dimension"})
        elif c["dtype"] == "numeric":
            metrics.append({"idx": idx, "name": name, "displayName": name,
                            "agg": _suggest_agg(c)})
        # 高基数文本（疑似 ID/自由文本）既不作维度也不作指标，留给人工决定

    drill_order = _suggest_drill_order(dims, profile)
    return {
        "dimensions": dims,
        "metrics": metrics,
        "formulas": [],
        "fences": [],
        "anomalies": [],
        "drill_order": drill_order,
        "reasoning": f"启发式分类：维度 {len(dims)} 个，指标 {len(metrics)} 个；"
                     f"公式/围栏/异动阈值需人工或 LLM 补充。",
    }


def normalize_draft(draft: Dict[str, Any], df: pd.DataFrame) -> Dict[str, Any]:
    """
    规整 LLM 返回的草稿，使其与人工配置同构：
      - 过滤掉非 dict / 缺 name / 引用了不存在列名的项
      - 按真实列顺序补 idx
      - 保证所有键存在且类型正确
    """
    valid_names = {str(c) for c in df.columns}
    name_to_idx = {str(c): i for i, c in enumerate(df.columns)}

    def _clean(items, need_existing_col):
        out = []
        for it in items if isinstance(items, list) else []:
            if not isinstance(it, dict) or not it.get("name"):
                continue
            if need_existing_col and it["name"] not in valid_names:
                continue
            out.append(it)
        return out

    dims = _clean(draft.get("dimensions"), True)
    for it in dims:
        it["idx"] = name_to_idx.get(it["name"], -1)
        it.setdefault("displayName", it["name"])
        it.setdefault("type", "dimension")

    metrics = _clean(draft.get("metrics"), True)
    for it in metrics:
        it["idx"] = name_to_idx.get(it["name"], -1)
        it.setdefault("displayName", it["name"])
        it.setdefault("agg", "sum")

    # 派生指标的 name 是新造的列名，不要求存在于原始列
    formulas = _clean(draft.get("formulas"), False)
    fences = _clean(draft.get("fences"), False)
    anomalies = _clean(draft.get("anomalies"), False)

    drill = draft.get("drill_order")
    drill = [d for d in drill if d in valid_names] if isinstance(drill, list) else []

    return {
        "dimensions": dims,
        "metrics": metrics,
        "formulas": formulas,
        "fences": fences,
        "anomalies": anomalies,
        "drill_order": drill,
        "reasoning": draft.get("reasoning", "") if isinstance(draft.get("reasoning"), str) else "",
    }


# ------------------------------------------------------------ 启发式判定细节

def _is_dimension(c: Dict[str, Any]) -> bool:
    dtype = c["dtype"]
    if dtype == "datetime":
        return True
    if dtype == "text":
        if c.get("is_datelike"):
            return True
        return c["unique_ratio"] <= 0.5            # 低基数文本 → 维度
    if dtype == "numeric":
        # 低基数整数（状态码/布尔/分桶）→ 维度
        return c.get("is_integer", False) and c["unique_count"] <= 10 and c["unique_ratio"] < 0.1
    return False


def _suggest_agg(c: Dict[str, Any]) -> str:
    """疑似比率（取值落在 [-1,1] 且非整数）→ avg；否则 sum。"""
    lo, hi = c.get("min"), c.get("max")
    if lo is not None and hi is not None and not c.get("is_integer", False):
        if -1.0 <= lo and hi <= 1.0:
            return "avg"
    return "sum"


def _suggest_drill_order(dims: List[Dict[str, Any]], profile: Dict[str, Any]) -> List[str]:
    card = {c["name"]: c["unique_count"] for c in profile["columns"]}
    is_time = {c["name"]: c.get("is_datelike", False) for c in profile["columns"]}
    time_dims = [d["name"] for d in dims if is_time.get(d["name"])]
    non_time = [d["name"] for d in dims if not is_time.get(d["name"])]
    non_time.sort(key=lambda nm: card.get(nm, 0))   # 基数升序：粗→细
    return time_dims + non_time


# ------------------------------------------------------------ 小工具

def _dtype_label(s: pd.Series) -> str:
    if pd.api.types.is_datetime64_any_dtype(s):
        return "datetime"
    if pd.api.types.is_numeric_dtype(s):
        return "numeric"
    return "text"


def _samples_look_like_date(samples: List[Any]) -> bool:
    if not samples:
        return False
    hits = sum(1 for v in samples if isinstance(v, str) and _DATE_RE.match(v))
    return hits >= max(1, len(samples) - 1)   # 允许一个噪声


def _scalar(x: Any) -> Any:
    if isinstance(x, pd.Timestamp):
        return x.strftime("%Y-%m-%d")
    if pd.isna(x):
        return None
    if hasattr(x, "item"):
        return x.item()
    return x


def _build_user_prompt(profile: Dict[str, Any], field_doc: str, background: str) -> str:
    import json
    parts = ["## 数据列画像", "```json",
             json.dumps(profile, ensure_ascii=False, indent=2), "```"]
    if field_doc.strip():
        parts += ["", "## 字段说明", field_doc.strip()]
    if background.strip():
        parts += ["", "## 业务背景与分析诉求", background.strip()]
    parts += ["", _OUTPUT_SPEC]
    return "\n".join(parts)


_OUTPUT_SPEC = """## 输出格式（严格 JSON）
{
  "dimensions": [{"name": "列名", "displayName": "显示名", "type": "dimension"}],
  "metrics":    [{"name": "列名", "displayName": "显示名", "agg": "sum|avg|count|max|min"}],
  "formulas":   [{"name": "派生指标名", "expression": "列A - 列B"}],
  "fences":     [{"name": "指标名", "min": 数值, "max": 数值}],
  "anomalies":  [{"name": "指标名", "downThreshold": 百分比, "upThreshold": 百分比}],
  "drill_order": ["维度1", "维度2"],
  "reasoning": "一句话说明判断依据"
}
规则：
- dimensions/metrics 的 name 必须是数据中真实存在的列名。
- 金额/计数类指标 agg 用 sum，比率类用 avg。
- formulas 的 expression 只能引用上面声明的列名，支持 + - * / ( )。
- 无法判断的部分留空数组。"""
