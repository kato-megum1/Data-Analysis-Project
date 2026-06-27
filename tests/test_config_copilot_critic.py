"""Config copilot and critic gate tests."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.config_copilot import ConfigCopilot, apply_patch_to_config  # noqa: E402
from agents.critic_agent import CriticAgent, apply_verdicts  # noqa: E402


CONFIG = {
    "dimensions": [{"idx": 0, "name": "日期"}, {"idx": 1, "name": "地区"}],
    "metrics": [{"idx": 2, "name": "销售额", "agg": "sum"}, {"idx": 3, "name": "成本", "agg": "sum"}],
    "formulas": [{"name": "利润率", "expression": "销售额 / 成本"}],
    "fences": [],
    "anomalies": [],
    "drill_order": ["日期", "地区"],
}


def test_config_chat_updates_fence_and_primary():
    out = ConfigCopilot().propose_patch("把销售额设为核心指标，利润率阈值改成 15% 到 60%", CONFIG, {})
    assert "销售额" in out["updated_config"]["primary_metrics"]
    fence = out["updated_config"]["fences"][0]
    assert fence["name"] == "利润率"
    assert abs(fence["min"] - 0.15) < 1e-9
    assert abs(fence["max"] - 0.6) < 1e-9


def test_illegal_patch_warns_but_keeps_config_parseable():
    updated, warnings = apply_patch_to_config(CONFIG, [{"op": "unknown"}])
    assert updated["metrics"]
    assert isinstance(warnings, list)


def test_critic_rejects_missing_refs():
    insights = [{"id": "ins_1", "claim": "销售额下降", "refs": ["a_missing"], "confidence": "高"}]
    review = CriticAgent().review({"anomalies": []}, insights)
    assert review["verdicts"][0]["status"] == "reject"
    assert apply_verdicts(insights, review) == []


def test_critic_revises_short_trend():
    facts = {"trends": [{"id": "t_销售额", "metric": "销售额", "points": 3}], "metrics": {}}
    insights = [{"id": "ins_1", "claim": "销售额趋势下降", "refs": ["t_销售额"], "confidence": "高"}]
    review = CriticAgent().review(facts, insights)
    final = apply_verdicts(insights, review)
    assert review["verdicts"][0]["status"] == "revise"
    assert final[0]["confidence"] == "中低"


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
