"""
FormulaDiscovery（有界 agentic loop）+ formula_verifier（确定性工具）单元测试。
不依赖真实 LLM：用脚本化 StubLLM 复现多轮"提议→验证→修正"。

运行：python tests/test_formula_discovery.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

from agents.formula_discovery import discover_formulas  # noqa: E402
from utils.formula_parser import FormulaParser  # noqa: E402
from utils.formula_verifier import check_identity, verify_formula  # noqa: E402


def _df():
    # 订单量无 0，避免除零；销售额/成本随行变化
    return pd.DataFrame({
        "订单量": [100, 120, 150, 80, 200],
        "销售额": [20000.0, 30000.0, 33000.0, 12000.0, 50000.0],
        "成本": [8000.0, 9000.0, 12000.0, 5000.0, 21000.0],
    })


def _df_with_zero():
    return pd.DataFrame({
        "订单量": [100, 0, 150, 0],
        "销售额": [20000.0, 30000.0, 33000.0, 12000.0],
    })


class ScriptedLLM:
    """按顺序返回预设 payload；用尽后重复最后一个。可塞入异常以测降级。"""
    def __init__(self, payloads):
        self.payloads = payloads
        self.calls = 0

    def structured_call(self, system, user, **kw):
        p = self.payloads[min(self.calls, len(self.payloads) - 1)]
        self.calls += 1
        if isinstance(p, Exception):
            raise p
        return p


# ===================================================== verify_formula

def test_verify_valid_ratio():
    v = verify_formula(_df(), "销售额 / 订单量")
    assert v["parses"] and v["sane"] and not v["constant"]
    assert v["stats"]["min"] > 0


def test_verify_constant_rejected():
    v = verify_formula(_df(), "订单量 - 订单量")
    assert v["parses"] and v["constant"] and not v["sane"]


def test_verify_parse_error():
    v = verify_formula(_df(), "销售额 / 幽灵列")
    assert not v["parses"] and v["error"]


def test_verify_div_by_zero_unsane():
    v = verify_formula(_df_with_zero(), "销售额 / 订单量")
    # 一半行除零 → inf_rate 高 → 不健康
    assert v["parses"] and not v["sane"]
    assert v["stats"]["inf_rate"] >= 0.05


# ===================================================== check_identity

def test_identity_holds():
    df = _df()
    df["客单价"] = FormulaParser(df).eval_formula("销售额 / 订单量")
    chk = check_identity(df, "订单量 * 客单价", "销售额")
    assert chk["holds"] and chk["max_rel_err"] <= 0.01


def test_identity_fails():
    chk = check_identity(_df(), "订单量 + 成本", "销售额")
    assert not chk["holds"]


# ===================================================== discovery loop

def test_discover_accepts_metric_and_decomposition():
    payloads = [
        {  # 第一轮：提议 客单价（好）+ 一个坏公式 + 销售额的乘法分解
            "formulas": [
                {"name": "客单价", "expression": "销售额 / 订单量", "purpose": "AOV"},
                {"name": "坏指标", "expression": "销售额 / 不存在列"},
            ],
            "decompositions": [
                {"target": "销售额", "expression": "订单量 * 客单价"},
            ],
            "done": False,
        },
        {"formulas": [], "decompositions": [], "done": True},  # 第二轮：收工
    ]
    out = discover_formulas(_df(), ["订单量", "销售额", "成本"], ScriptedLLM(payloads))

    names = [f["name"] for f in out["formulas"]]
    assert "客单价" in names                                   # 好公式被采纳
    assert any(r["name"] == "坏指标" for r in out["rejected"])  # 坏公式被驳回
    # 乘法分解被确定性验证通过
    assert len(out["decompositions"]) == 1
    assert out["decompositions"][0]["target"] == "销售额"
    assert out["decompositions"][0]["max_rel_err"] <= 0.01
    assert out["iterations"] == 2


def test_discover_rejects_unproven_decomposition():
    payloads = [{
        "formulas": [],
        "decompositions": [{"target": "销售额", "expression": "订单量 + 成本"}],  # 不成立
        "done": True,
    }]
    out = discover_formulas(_df(), ["订单量", "销售额", "成本"], ScriptedLLM(payloads))
    assert out["decompositions"] == []
    assert any("分解" in r["name"] for r in out["rejected"])


def test_discover_respects_max_iters():
    payloads = [
        {"formulas": [{"name": "m1", "expression": "销售额 + 成本"}], "done": False},
        {"formulas": [{"name": "m2", "expression": "销售额 - 成本"}], "done": False},
        {"formulas": [{"name": "m3", "expression": "销售额 * 2"}], "done": False},
    ]
    out = discover_formulas(_df(), ["订单量", "销售额", "成本"],
                            ScriptedLLM(payloads), max_iters=2)
    assert out["iterations"] == 2
    names = [f["name"] for f in out["formulas"]]
    assert names == ["m1", "m2"]          # 第 3 轮未触达


def test_discover_stops_when_no_progress():
    # 始终只提议同一个会被驳回的公式 → 无进展 → 提前终止
    payloads = [{"formulas": [{"name": "坏", "expression": "1 / 0"}],
                 "decompositions": [], "done": False}]
    out = discover_formulas(_df(), ["订单量", "销售额"], ScriptedLLM(payloads), max_iters=5)
    assert out["iterations"] == 1          # 第一轮无进展即停
    assert out["formulas"] == []


def test_discover_survives_llm_failure():
    out = discover_formulas(_df(), ["订单量", "销售额"],
                            ScriptedLLM([RuntimeError("api down")]))
    assert out["formulas"] == []
    assert any("LLM 调用失败" in r["reason"] for r in out["rejected"])


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
