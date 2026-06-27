"""
ConfigAdvisor (Layer 0) 单元测试 —— 不依赖真实 LLM / 网络。

刻意使用「网站流量」数据集（与零售测试集结构完全不同），
验证配置草拟是泛用的、零业务硬编码。

运行：python tests/test_config_advisor.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

from agents.config_advisor import (  # noqa: E402
    ConfigAdvisor, heuristic_suggest, normalize_draft, profile_columns,
)
from utils.llm_client import extract_json  # noqa: E402


def _web_traffic_df():
    # 日期 | 页面 | 设备 | UV | PV | 跳出率  —— 18 行，基数比例贴近真实
    pages = ["/home", "/pricing", "/blog"]
    devices = ["mobile", "desktop"]
    rows = []
    for d in range(6):                      # 6 天
        for i in range(3):                  # 每天 3 条
            rows.append({
                "日期": f"2025-01-0{d+1}",
                "页面": pages[i % len(pages)],
                "设备": devices[i % len(devices)],
                "UV": 1000 + d * 50 + i * 30,
                "PV": 3500 + d * 120 + i * 80,
                "跳出率": round(0.40 + 0.03 * i, 2),
            })
    return pd.DataFrame(rows)


class StubLLM:
    """注入用的假 LLM：直接返回预设 dict。"""
    def __init__(self, payload=None, raise_exc=None):
        self.payload = payload
        self.raise_exc = raise_exc

    def structured_call(self, system, user, **kw):
        if self.raise_exc:
            raise self.raise_exc
        return self.payload


# ----------------------------------------------------------- extract_json

def test_extract_json_plain():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced():
    assert extract_json('```json\n{"a": 2}\n```') == {"a": 2}


def test_extract_json_embedded():
    assert extract_json('好的，结果如下：{"a": 3} 完毕') == {"a": 3}


# ----------------------------------------------------------- 列画像

def test_profile_detects_types():
    prof = profile_columns(_web_traffic_df())
    by = {c["name"]: c for c in prof["columns"]}
    assert by["设备"]["dtype"] == "text"
    assert by["UV"]["dtype"] == "numeric"
    assert by["UV"]["is_integer"] is True
    assert by["跳出率"]["is_integer"] is False


# ----------------------------------------------------------- 启发式（泛用）

def test_heuristic_classifies_web_traffic():
    df = _web_traffic_df()
    draft = heuristic_suggest(df)
    dims = {d["name"] for d in draft["dimensions"]}
    metrics = {m["name"] for m in draft["metrics"]}
    # 日期(类日期文本) + 页面/设备(低基数文本) → 维度
    assert dims == {"日期", "页面", "设备"}
    # UV/PV/跳出率 → 指标
    assert metrics == {"UV", "PV", "跳出率"}


def test_heuristic_ratio_uses_avg():
    draft = heuristic_suggest(_web_traffic_df())
    agg = {m["name"]: m["agg"] for m in draft["metrics"]}
    assert agg["跳出率"] == "avg"   # [0,1] 非整数 → 比率 → avg
    assert agg["UV"] == "sum"


def test_heuristic_drill_order_time_first():
    draft = heuristic_suggest(_web_traffic_df())
    # 时间维优先，其余按基数升序（设备2 < 页面3）
    assert draft["drill_order"][0] == "日期"
    assert draft["drill_order"].index("设备") < draft["drill_order"].index("页面")


def test_heuristic_leaves_business_rules_empty():
    draft = heuristic_suggest(_web_traffic_df())
    assert draft["formulas"] == [] and draft["fences"] == [] and draft["anomalies"] == []


# ----------------------------------------------------------- normalize

def test_normalize_filters_unknown_columns_and_fills_idx():
    df = _web_traffic_df()
    raw = {
        "dimensions": [{"name": "页面"}, {"name": "不存在的列"}, {"bad": 1}],
        "metrics": [{"name": "UV", "agg": "sum"}],
        "formulas": [{"name": "每访客页数", "expression": "PV / UV"}],
        "drill_order": ["页面", "幽灵维度"],
    }
    out = normalize_draft(raw, df)
    assert [d["name"] for d in out["dimensions"]] == ["页面"]   # 未知列/坏项被过滤
    assert out["dimensions"][0]["idx"] == 1                      # 按真实列序补 idx
    assert out["dimensions"][0]["displayName"] == "页面"         # 补默认 displayName
    # 派生指标名不要求是已有列
    assert out["formulas"][0]["name"] == "每访客页数"
    assert out["drill_order"] == ["页面"]                        # 幽灵维度被过滤


# ----------------------------------------------------------- Advisor 调度

def test_advisor_no_llm_uses_heuristic():
    out = ConfigAdvisor(llm=None).suggest(_web_traffic_df())
    assert out["source"] == "heuristic"
    assert {m["name"] for m in out["metrics"]} == {"UV", "PV", "跳出率"}


def test_advisor_uses_llm_when_available():
    df = _web_traffic_df()
    payload = {
        "dimensions": [{"name": "日期"}, {"name": "页面"}],
        "metrics": [{"name": "UV", "agg": "sum"}, {"name": "跳出率", "agg": "avg"}],
        "formulas": [{"name": "每访客页数", "expression": "PV / UV"}],
        "fences": [{"name": "跳出率", "min": 0.0, "max": 0.7}],
        "anomalies": [{"name": "UV", "downThreshold": 20, "upThreshold": 30}],
        "drill_order": ["日期", "页面"],
        "reasoning": "测试",
    }
    out = ConfigAdvisor(llm=StubLLM(payload)).suggest(df)
    assert out["source"] == "llm"
    assert out["formulas"][0]["expression"] == "PV / UV"
    assert out["dimensions"][0]["idx"] == 0   # 已补 idx


def test_advisor_falls_back_when_llm_raises():
    out = ConfigAdvisor(llm=StubLLM(raise_exc=RuntimeError("boom"))).suggest(_web_traffic_df())
    assert out["source"] == "heuristic_fallback"
    assert "boom" in out["reasoning"]
    assert out["metrics"]   # 兜底仍给出指标


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
