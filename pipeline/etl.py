"""
Skill 2：ETL —— 加载 / 清洗 / 聚合（纯代码，无 LLM）

输入：state["config"]["file_path"]（数据文件） + state["schema"]
输出：state["data"] = {
        "df": <聚合后的 DataFrame，内存对象，不进 JSON/LLM>,
        "summary": {"rows", "columns", "date_range":[min,max]|None,
                    "granularity", "null_count", "dimensions", "metrics"}
      }

职责边界：只负责"把原始文件变成规整、按维度聚合好的分析底表"。
派生指标、统计、围栏判断都在 Skill 3 (metric) 做。
"""

import warnings
from typing import Any, Dict, List, Optional

import pandas as pd

from state import log_error

_AGG_MAP = {
    "sum": "sum", "avg": "mean", "mean": "mean",
    "count": "count", "max": "max", "min": "min",
}


def run(state: Dict[str, Any]) -> Dict[str, Any]:
    """流水线入口：读取文件 → 清洗 → 聚合 → 写入 state["data"]。"""
    schema = state.get("schema") or {}
    file_path = (state.get("config") or {}).get("file_path", "")
    try:
        if not file_path:
            raise ValueError("config.file_path 为空，无法加载数据")
        raw = read_file(file_path)
        df = transform(raw, schema)
        state["data"] = {"df": df, "summary": build_summary(df, schema)}
    except Exception as e:
        log_error(state, "etl", e)
        state["data"] = {"df": None, "summary": {}}
    return state


# ----------------------------------------------------------------- 读取

def read_file(file_path: str) -> pd.DataFrame:
    """读取 csv / xlsx / xls，csv 自动尝试多种编码。"""
    p = file_path.lower()
    if p.endswith(".csv"):
        for enc in ("utf-8", "utf-8-sig", "gbk", "gb2312", "latin-1"):
            try:
                return pd.read_csv(file_path, encoding=enc)
            except UnicodeDecodeError:
                continue
        return pd.read_csv(file_path, encoding="utf-8", errors="replace")
    if p.endswith((".xlsx", ".xls")):
        return pd.read_excel(file_path, engine="openpyxl")
    raise ValueError(f"不支持的文件格式: {file_path}")


# ----------------------------------------------------------------- 转换

def transform(raw: pd.DataFrame, schema: Dict[str, Any]) -> pd.DataFrame:
    """按 schema 重命名列 → 选列 → 清洗 → 按维度聚合。纯函数，便于单测。"""
    dims = schema.get("dimensions", [])
    metrics = schema.get("metrics", [])

    # 1. 按 idx 把原始列名映射为 schema 标准名
    rename = {}
    for c in dims + metrics:
        idx = c.get("idx")
        if isinstance(idx, int) and 0 <= idx < len(raw.columns):
            rename[raw.columns[idx]] = c["name"]
    df = raw.rename(columns=rename)

    # 2. 只保留相关列
    keep = [c["name"] for c in dims + metrics if c["name"] in df.columns]
    df = df[keep]

    # 3. 清洗
    df = _clean(df, dims, metrics)

    # 4. 按维度聚合
    df = _aggregate(df, dims, metrics)
    return df


def _clean(df: pd.DataFrame, dims: List[Dict], metrics: List[Dict]) -> pd.DataFrame:
    """去 Unnamed 列、指标转数值、日期型维度转 datetime、丢全空行。"""
    df = df.loc[:, ~df.columns.str.contains("^Unnamed", na=False)]

    metric_names = [m["name"] for m in metrics if m["name"] in df.columns]
    for name in metric_names:
        df[name] = pd.to_numeric(df[name], errors="coerce")

    for d in dims:
        name = d["name"]
        if name in df.columns and df[name].dtype == object:
            with warnings.catch_warnings():
                # 对非日期文本列尝试解析会发 "Could not infer format" 告警，静默之
                warnings.simplefilter("ignore", UserWarning)
                converted = pd.to_datetime(df[name], errors="coerce")
            # 仅当大部分能解析成日期时才认定为时间维度，避免误伤普通文本
            if converted.notna().mean() > 0.8:
                df[name] = converted

    if metric_names:
        df = df.dropna(subset=metric_names, how="all")
    return df


def _aggregate(df: pd.DataFrame, dims: List[Dict], metrics: List[Dict]) -> pd.DataFrame:
    """按全部维度分组聚合；无维度则整体聚合为单行。"""
    dim_names = [d["name"] for d in dims if d["name"] in df.columns]
    agg_map = {m["name"]: _AGG_MAP.get(m.get("agg", "sum"), "sum")
               for m in metrics if m["name"] in df.columns}
    if not agg_map:
        return df

    if dim_names:
        df = df.groupby(dim_names, as_index=False, dropna=False).agg(agg_map)
        # 若含时间维度，按时间排序，方便后续趋势/异动按序消费
        time_dim = _first_datetime_dim(df, dims)
        if time_dim:
            df = df.sort_values(time_dim).reset_index(drop=True)
    else:
        df = pd.DataFrame({k: [df[k].agg(v)] for k, v in agg_map.items()})
    return df


# ----------------------------------------------------------------- 摘要

def build_summary(df: pd.DataFrame, schema: Dict[str, Any]) -> Dict[str, Any]:
    date_range, granularity = _date_info(df, schema.get("dimensions", []))
    return {
        "rows": int(len(df)),
        "columns": int(len(df.columns)),
        "dimensions": [d["display_name"] for d in schema.get("dimensions", [])],
        "metrics": [m["display_name"] for m in schema.get("metrics", [])],
        "null_count": int(df.isnull().sum().sum()),
        "date_range": date_range,
        "granularity": granularity,
    }


def _first_datetime_dim(df: pd.DataFrame, dims: List[Dict]) -> Optional[str]:
    for d in dims:
        name = d["name"]
        if name in df.columns and pd.api.types.is_datetime64_any_dtype(df[name]):
            return name
    return None


def _date_info(df: pd.DataFrame, dims: List[Dict]):
    """返回 (date_range:[min,max]|None, granularity)。"""
    col = _first_datetime_dim(df, dims)
    if not col:
        return None, "none"
    s = df[col].dropna()
    if s.empty:
        return None, "unknown"
    date_range = [s.min().strftime("%Y-%m-%d"), s.max().strftime("%Y-%m-%d")]
    return date_range, _infer_granularity(s)


def _infer_granularity(s: pd.Series) -> str:
    """按相邻唯一日期的中位间隔推断粒度。"""
    uniq = pd.Series(sorted(pd.Series(s.unique())))
    if len(uniq) < 2:
        return "unknown"
    med_days = uniq.diff().dropna().dt.days.median()
    if med_days <= 1:
        return "day"
    if med_days <= 7:
        return "week"
    if med_days <= 31:
        return "month"
    if med_days <= 92:
        return "quarter"
    return "year"
