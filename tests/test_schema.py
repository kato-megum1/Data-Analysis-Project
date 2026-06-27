"""
Skill 1 (Schema) 单元测试 —— 锚定解析正确性。

运行：python tests/test_schema.py   （无需 pytest）
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import schema  # noqa: E402

SAMPLE_CONFIG = {
    "dimensions": [
        {"idx": 0, "name": "日期", "displayName": "日期"},
        {"idx": 1, "name": "地区", "displayName": "区域"},
    ],
    "metrics": [
        {"idx": 4, "name": "订单量", "displayName": "订单量", "agg": "sum"},
        {"idx": 5, "name": "销售额", "displayName": "销售额", "agg": "sum"},
        {"idx": 6, "name": "成本", "displayName": "成本", "agg": "sum"},
    ],
    "formulas": [
        {"name": "利润", "expression": "销售额 - 成本"},
        {"name": "利润率", "expression": "利润 / 销售额"},
    ],
    "fences": [{"name": "利润率", "min": 0.1, "max": 0.8}],
    "anomalies": [{"name": "销售额", "downThreshold": 20, "upThreshold": 30}],
    "drill_order": ["地区"],
}


def test_basic_parse():
    s = schema.parse_schema(SAMPLE_CONFIG)
    assert [d["name"] for d in s["dimensions"]] == ["日期", "地区"]
    assert [m["name"] for m in s["metrics"]] == ["订单量", "销售额", "成本"]
    # displayName 覆盖 name
    assert s["dimensions"][1]["display_name"] == "区域"
    # agg 默认/覆盖
    assert s["metrics"][0]["agg"] == "sum"


def test_formula_parts():
    s = schema.parse_schema(SAMPLE_CONFIG)
    parts = {f["name"]: f["parts"] for f in s["formulas"]}
    assert parts["利润"] == ["销售额", "成本"]
    assert parts["利润率"] == ["利润", "销售额"]


def test_analysis_metrics_includes_derived():
    s = schema.parse_schema(SAMPLE_CONFIG)
    assert s["analysis_metrics"] == ["订单量", "销售额", "成本", "利润", "利润率"]
    assert s["derived_metric_names"] == ["利润", "利润率"]
    assert s["fence_metric_names"] == ["利润率"]


def test_anomaly_thresholds():
    s = schema.parse_schema(SAMPLE_CONFIG)
    assert s["anomaly_thresholds"]["销售额"] == {"down": 20, "up": 30}


def test_drill_order_default():
    cfg = dict(SAMPLE_CONFIG)
    cfg = {**cfg, "drill_order": []}
    s = schema.parse_schema(cfg)
    # 缺省下钻顺序 = 全部维度
    assert s["drill_order"] == ["日期", "地区"]


def test_warnings_on_unknown_refs():
    bad = {
        "dimensions": [{"idx": 0, "name": "日期"}],
        "metrics": [{"idx": 1, "name": "销售额"}],
        "formulas": [{"name": "毛利", "expression": "收入 - 成本"}],  # 收入/成本未知
        "fences": [{"name": "不存在指标", "min": 0, "max": 1}],
        "anomalies": [{"name": "幽灵指标", "downThreshold": 10}],
        "drill_order": ["不存在维度"],
    }
    s = schema.parse_schema(bad)
    joined = " ".join(s["warnings"])
    assert "不存在指标" in joined
    assert "幽灵指标" in joined
    assert "不存在维度" in joined
    assert "收入" in joined and "成本" in joined


def test_empty_config():
    s = schema.parse_schema({})
    assert s["dimensions"] == []
    assert s["metrics"] == []
    assert s["analysis_metrics"] == []


def test_run_wraps_state():
    from state import new_state
    st = new_state(SAMPLE_CONFIG)
    schema.run(st)
    assert st["schema"]["analysis_metrics"]
    assert st["errors"] == []


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
