"""
Skill 2 (ETL) + Skill 3 (Metric) 单元测试 —— 用内存 DataFrame，不依赖文件/网络。

运行：python tests/test_etl_metric.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

from pipeline import etl, metric, schema  # noqa: E402

# 最小 schema：1 时间维 + 1 类别维 + 2 指标 + 1 派生 + 1 围栏
CONFIG = {
    "dimensions": [
        {"idx": 0, "name": "日期"},
        {"idx": 1, "name": "地区"},
    ],
    "metrics": [
        {"idx": 2, "name": "销售额", "agg": "sum"},
        {"idx": 3, "name": "成本", "agg": "sum"},
    ],
    "formulas": [
        {"name": "利润", "expression": "销售额 - 成本"},
        {"name": "利润率", "expression": "利润 / 销售额"},
    ],
    "fences": [{"name": "利润率", "min": 0.1, "max": 0.8}],
}


def _raw_df():
    # 注意：含两行同维度组合(2024-01-01/华东)，验证聚合求和
    return pd.DataFrame({
        "日期": ["2024-01-01", "2024-01-01", "2024-01-02", "2024-01-02"],
        "地区": ["华东", "华东", "华东", "华南"],
        "销售额": [100.0, 100.0, 200.0, 50.0],
        "成本": [50.0, 50.0, 40.0, 49.0],
    })


def _schema():
    return schema.parse_schema(CONFIG)


# ----------------------------------------------------------- ETL

def test_etl_aggregates_duplicate_dims():
    df = etl.transform(_raw_df(), _schema())
    # (2024-01-01,华东) 两行合并 → 销售额 200
    row = df[(df["地区"] == "华东") & (df["日期"] == pd.Timestamp("2024-01-01"))]
    assert len(row) == 1
    assert row["销售额"].iloc[0] == 200.0
    assert len(df) == 3  # 3 个唯一维度组合


def test_etl_date_parsed_and_sorted():
    df = etl.transform(_raw_df(), _schema())
    assert pd.api.types.is_datetime64_any_dtype(df["日期"])
    # 按时间升序
    assert list(df["日期"]) == sorted(df["日期"])


def test_etl_summary():
    df = etl.transform(_raw_df(), _schema())
    summary = etl.build_summary(df, _schema())
    assert summary["date_range"] == ["2024-01-01", "2024-01-02"]
    assert summary["granularity"] == "day"
    assert summary["null_count"] == 0


def test_etl_text_dim_not_dateified():
    df = etl.transform(_raw_df(), _schema())
    # 地区是文本维度，不能被误转成日期
    assert df["地区"].dtype == object


# ----------------------------------------------------------- Metric

def _run_to_metric():
    from state import new_state
    df = etl.transform(_raw_df(), _schema())
    st = new_state(CONFIG, df=df)
    st["schema"] = _schema()
    st["data"] = {"df": df, "summary": {}}
    metric.run(st)
    return st


def test_metric_derived_columns():
    st = _run_to_metric()
    df = st["data"]["df"]
    assert "利润" in df.columns and "利润率" in df.columns
    # (2024-01-01,华东): 销售额200 成本100 → 利润100 利润率0.5
    row = df[(df["地区"] == "华东") & (df["日期"] == pd.Timestamp("2024-01-01"))].iloc[0]
    assert row["利润"] == 100.0
    assert abs(row["利润率"] - 0.5) < 1e-9


def test_metric_formula_types():
    st = _run_to_metric()
    ft = st["data"]["formula_types"]
    assert ft["利润"] == "additive"
    assert ft["利润率"] == "multiplicative"


def test_metric_stats():
    st = _run_to_metric()
    stats = st["facts"]["metrics"]
    assert set(stats) >= {"销售额", "成本", "利润", "利润率"}
    assert stats["销售额"]["count"] == 3
    assert stats["销售额"]["max"] == 200.0


def test_metric_fence_violations():
    st = _run_to_metric()
    fv = st["facts"]["fence_violations"]
    assert len(fv) == 1
    f = fv[0]
    assert f["id"] == "f_利润率"
    # (2024-01-02,华南): 销售额50 成本49 → 利润率0.02 < 0.1 越界
    assert f["violation_count"] == 1
    assert f["samples"][0]["side"] == "min"
    assert f["samples"][0]["dims"]["地区"] == "华南"


def test_metric_handles_empty_df():
    from state import new_state
    st = new_state(CONFIG, df=pd.DataFrame())
    st["schema"] = _schema()
    st["data"] = {"df": pd.DataFrame(), "summary": {}}
    metric.run(st)
    # 空数据应降级、不抛异常
    assert any(e["step"] == "metric" for e in st["errors"])


if __name__ == "__main__":
    funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in funcs:
        try:
            fn()
            print(f"  ✅ {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  ❌ {fn.__name__}: {e}")
        except Exception as e:
            print(f"  💥 {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(funcs)} passed")
    sys.exit(0 if passed == len(funcs) else 1)
