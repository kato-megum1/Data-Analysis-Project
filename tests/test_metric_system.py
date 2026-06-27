"""Metric System Agent tests."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

from agents.metric_system_agent import MetricSystemAgent  # noqa: E402


def _retail_df():
    return pd.DataFrame({
        "日期": ["2024-01-01", "2024-01-02", "2024-01-03"],
        "地区": ["华东", "华南", "华东"],
        "品类": ["食品", "服装", "食品"],
        "订单量": [10, 12, 9],
        "销售额": [1000.0, 1200.0, 900.0],
        "成本": [600.0, 700.0, 500.0],
    })


def _traffic_df():
    return pd.DataFrame({
        "date": ["2024-01-01", "2024-01-02", "2024-01-03"],
        "page": ["/", "/pricing", "/"],
        "UV": [100, 120, 140],
        "PV": [300, 360, 420],
        "bounce_rate": [0.42, 0.38, 0.35],
    })


def test_retail_metric_system():
    out = MetricSystemAgent().draft(_retail_df(), background="分析销售、订单和成本")
    cfg = out["recommended_config"]
    ms = out["metric_system"]
    assert ms["template"] == "retail"
    assert {"日期", "地区", "品类"} >= {d["name"] for d in cfg["dimensions"]}
    assert {"订单量", "销售额", "成本"} <= {m["name"] for m in cfg["metrics"]}
    assert "销售额" in ms["primary_metrics"]


def test_growth_ratio_uses_avg():
    out = MetricSystemAgent().draft(_traffic_df(), background="网站增长分析")
    cfg = out["recommended_config"]
    agg = {m["name"]: m["agg"] for m in cfg["metrics"]}
    assert out["metric_system"]["template"] == "growth"
    assert agg["bounce_rate"] == "avg"


def test_invalid_formula_from_llm_is_warning():
    class StubLLM:
        def structured_call(self, system, user, **kwargs):
            return {
                "dimensions": [{"name": "日期"}],
                "metrics": [{"name": "销售额", "agg": "sum"}],
                "formulas": [{"name": "坏公式", "expression": "销售额 / 不存在"}],
            }

    out = MetricSystemAgent(llm=StubLLM()).draft(_retail_df())
    assert out["recommended_config"]["formulas"] == []
    assert any("坏公式" in w for w in out["warnings"])


if __name__ == "__main__":
    funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in funcs:
        try:
            fn()
            print(f"  ✅ {fn.__name__}")
            passed += 1
        except Exception as e:
            print(f"  ❌ {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(funcs)} passed")
    sys.exit(0 if passed == len(funcs) else 1)
